"""Fail-closed peer selection and finalized block import coordination."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import os
from typing import Callable, Iterable

from .finality import FinalityCertificate
from .node_pipeline import ExecutedProposal, NodeExecutionPipeline, NodePipelineError
from .state_store import PersistentStateStore, StoredBlock


class PeerSyncError(ValueError):
    """Raised when peer or import evidence violates a synchronization invariant."""


class RecoveryAction(str, Enum):
    CLEAN = "CLEAN"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    COMMIT_CONFIRMED = "COMMIT_CONFIRMED"


@dataclass(frozen=True)
class PeerAdvertisement:
    peer_id: str
    chain_id: int
    genesis_hash: str
    finalized_height: int
    finalized_hash: str
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if not self.peer_id:
            raise PeerSyncError("peer_id is required")
        if self.chain_id <= 0 or self.finalized_height < 0 or self.protocol_version != 1:
            raise PeerSyncError("peer advertisement contains invalid protocol values")
        _hash(self.genesis_hash, "genesis_hash")
        _hash(self.finalized_hash, "finalized_hash")


@dataclass(frozen=True)
class PeerRecord:
    advertisement: PeerAdvertisement
    fault_score: int = 0

    @property
    def eligible(self) -> bool:
        return self.fault_score < 3


class PeerRegistry:
    """Identity-bound peer registry with deterministic sync-source selection."""

    def __init__(self, *, chain_id: int, genesis_hash: str) -> None:
        if chain_id <= 0:
            raise PeerSyncError("chain_id must be positive")
        _hash(genesis_hash, "genesis_hash")
        self.chain_id = chain_id
        self.genesis_hash = genesis_hash.lower()
        self._peers: dict[str, PeerRecord] = {}

    def observe(self, advertisement: PeerAdvertisement) -> PeerRecord:
        if advertisement.chain_id != self.chain_id:
            raise PeerSyncError("peer chain_id mismatch")
        if advertisement.genesis_hash.lower() != self.genesis_hash:
            raise PeerSyncError("peer genesis mismatch")
        current = self._peers.get(advertisement.peer_id)
        fault_score = 0 if current is None else current.fault_score
        if current is not None and advertisement.finalized_height < current.advertisement.finalized_height:
            raise PeerSyncError("peer finalized height regressed")
        record = PeerRecord(advertisement=advertisement, fault_score=fault_score)
        self._peers[advertisement.peer_id] = record
        return record

    def record_fault(self, peer_id: str) -> PeerRecord:
        current = self._require(peer_id)
        updated = PeerRecord(current.advertisement, current.fault_score + 1)
        self._peers[peer_id] = updated
        return updated

    def select_source(self, *, local_height: int) -> PeerRecord:
        candidates = [
            record
            for record in self._peers.values()
            if record.eligible and record.advertisement.finalized_height > local_height
        ]
        if not candidates:
            raise PeerSyncError("no eligible peer is ahead of the local finalized head")
        return min(
            candidates,
            key=lambda record: (
                -record.advertisement.finalized_height,
                record.fault_score,
                record.advertisement.peer_id,
            ),
        )

    def evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-peer-registry-evidence/v1",
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "peer_count": len(self._peers),
            "eligible_peer_count": sum(record.eligible for record in self._peers.values()),
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _require(self, peer_id: str) -> PeerRecord:
        try:
            return self._peers[peer_id]
        except KeyError as exc:
            raise PeerSyncError("unknown peer") from exc


class RecoveryJournal:
    """Durable single-flight import journal with fsync and atomic replacement."""

    def __init__(self, path: str | Path, *, chain_id: int) -> None:
        self.path = Path(path)
        self.chain_id = chain_id

    def begin(self, *, peer_id: str, proposal: ExecutedProposal) -> None:
        if self.read() is not None:
            raise PeerSyncError("an import recovery record is already active")
        self._write(
            {
                "schema_version": "junca-block-import-journal/v1",
                "chain_id": self.chain_id,
                "status": "PREPARED",
                "peer_id": peer_id,
                "height": proposal.height,
                "parent_hash": proposal.parent_hash,
                "block_hash": proposal.block_hash,
                "state_root": proposal.transition.state_root,
            }
        )

    def mark_committed(self, block: StoredBlock) -> None:
        record = self.read()
        if record is None or record["block_hash"] != block.block_hash:
            raise PeerSyncError("recovery journal does not bind the committed block")
        record["status"] = "COMMITTED"
        self._write(record)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
            _fsync_directory(self.path.parent)

    def read(self) -> dict[str, object] | None:
        if not self.path.exists():
            return None
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PeerSyncError("recovery journal is unreadable") from exc
        required = {
            "schema_version",
            "chain_id",
            "status",
            "peer_id",
            "height",
            "parent_hash",
            "block_hash",
            "state_root",
            "record_digest",
        }
        if set(record) != required:
            raise PeerSyncError("recovery journal fields are invalid")
        supplied = record.pop("record_digest")
        expected = _digest(record)
        record["record_digest"] = supplied
        if supplied != expected or record["chain_id"] != self.chain_id:
            raise PeerSyncError("recovery journal integrity failure")
        return record

    def recover(self, store: PersistentStateStore) -> RecoveryAction:
        record = self.read()
        if record is None:
            return RecoveryAction.CLEAN
        head = store.head()
        if head.height == record["height"] and head.block_hash == record["block_hash"]:
            self.clear()
            return RecoveryAction.COMMIT_CONFIRMED
        if head.height + 1 == record["height"] and head.block_hash == record["parent_hash"]:
            return RecoveryAction.RETRY_REQUIRED
        raise PeerSyncError("journal does not reconcile with finalized state")

    def _write(self, record: dict[str, object]) -> None:
        body = dict(record)
        body.pop("record_digest", None)
        body["record_digest"] = _digest(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        _fsync_directory(self.path.parent)


FaultInjector = Callable[[str], None]


class SynchronizedBlockImporter:
    """Imports one finalized proposal from a selected identity-bound peer."""

    def __init__(
        self,
        *,
        registry: PeerRegistry,
        pipeline: NodeExecutionPipeline,
        journal: RecoveryJournal,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.registry = registry
        self.pipeline = pipeline
        self.journal = journal
        self.fault_injector = fault_injector or (lambda _: None)

    def import_finalized(
        self,
        *,
        peer_id: str,
        proposal: ExecutedProposal,
        certificate: FinalityCertificate,
    ) -> StoredBlock:
        selected = self.registry.select_source(local_height=self.pipeline.store.head_height)
        if selected.advertisement.peer_id != peer_id:
            raise PeerSyncError("block source is not the selected synchronization peer")
        if selected.advertisement.finalized_height < proposal.height:
            raise PeerSyncError("peer did not advertise the imported finalized height")
        self.journal.begin(peer_id=peer_id, proposal=proposal)
        self.fault_injector("after_journal_prepare")
        try:
            stored = self.pipeline.commit_finalized(proposal, certificate)
        except (NodePipelineError, ValueError):
            self.registry.record_fault(peer_id)
            raise
        self.fault_injector("after_state_commit")
        self.journal.mark_committed(stored)
        self.fault_injector("after_journal_commit")
        self.journal.clear()
        return stored


def _digest(body: dict[str, object]) -> str:
    return "0x" + hashlib.sha256(
        b"JUNCA_BLOCK_IMPORT_JOURNAL_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise PeerSyncError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise PeerSyncError(f"{field} must be a 32-byte hex value") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
