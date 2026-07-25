"""Finalized fork choice, Byzantine peer controls, and snapshot catch-up."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence


class ConsensusSyncError(ValueError):
    """Raised when synchronization evidence violates a safety invariant."""


@dataclass(frozen=True)
class FinalizedClaim:
    peer_id: str
    chain_id: int
    genesis_hash: str
    height: int
    block_hash: str
    parent_hash: str
    state_root: str
    signed_power: int
    total_power: int

    def __post_init__(self) -> None:
        if not self.peer_id or self.chain_id <= 0 or self.height < 0:
            raise ConsensusSyncError("finalized claim identity is invalid")
        for field in ("genesis_hash", "block_hash", "parent_hash", "state_root"):
            _hash(getattr(self, field), field)
        if (
            self.signed_power <= 0
            or self.total_power <= 0
            or self.signed_power > self.total_power
            or self.signed_power * 3 <= self.total_power * 2
        ):
            raise ConsensusSyncError("finalized claim lacks strict two-thirds quorum")


@dataclass(frozen=True)
class PeerDiscipline:
    faults: int = 0
    quarantined: bool = False


class FinalizedForkChoice:
    """Chooses only certified finalized tips and halts on conflicting finality."""

    def __init__(
        self,
        *,
        chain_id: int,
        genesis_hash: str,
        expected_total_power: int,
        quarantine_threshold: int = 3,
    ) -> None:
        if chain_id <= 0 or expected_total_power <= 0 or quarantine_threshold <= 0:
            raise ConsensusSyncError("fork-choice policy values must be positive")
        _hash(genesis_hash, "genesis_hash")
        self.chain_id = chain_id
        self.genesis_hash = genesis_hash.lower()
        self.expected_total_power = expected_total_power
        self.quarantine_threshold = quarantine_threshold
        self._claims: dict[str, FinalizedClaim] = {}
        self._canonical: dict[int, FinalizedClaim] = {}
        self._discipline: dict[str, PeerDiscipline] = {}
        self._safety_halt: tuple[int, str, str] | None = None

    @property
    def safety_halted(self) -> bool:
        return self._safety_halt is not None

    @property
    def head(self) -> FinalizedClaim | None:
        return self._canonical[max(self._canonical)] if self._canonical else None

    @property
    def observed_peer_count(self) -> int:
        return len(self._claims)

    def observe(self, claim: FinalizedClaim) -> FinalizedClaim:
        if self.safety_halted:
            raise ConsensusSyncError("fork choice is safety halted")
        if claim.chain_id != self.chain_id:
            return self._fault(claim.peer_id, "claim chain_id mismatch")
        if claim.genesis_hash.lower() != self.genesis_hash:
            return self._fault(claim.peer_id, "claim genesis mismatch")
        if claim.total_power != self.expected_total_power:
            return self._fault(claim.peer_id, "claim validator power mismatch")
        if self.discipline(claim.peer_id).quarantined:
            raise ConsensusSyncError("peer is quarantined")
        previous = self._claims.get(claim.peer_id)
        if previous is not None and claim.height < previous.height:
            return self._fault(claim.peer_id, "peer finalized height regressed")
        existing = self._canonical.get(claim.height)
        if existing is not None and existing.block_hash.lower() != claim.block_hash.lower():
            self._safety_halt = (
                claim.height,
                existing.block_hash.lower(),
                claim.block_hash.lower(),
            )
            raise ConsensusSyncError("conflicting valid finality certificates detected")
        previous_height = self._canonical.get(claim.height - 1)
        if (
            previous_height is not None
            and claim.parent_hash.lower() != previous_height.block_hash.lower()
        ):
            return self._fault(claim.peer_id, "finalized parent linkage mismatch")
        self._claims[claim.peer_id] = claim
        if existing is None:
            self._canonical[claim.height] = claim
        return self.head

    def record_protocol_fault(self, peer_id: str) -> PeerDiscipline:
        current = self.discipline(peer_id)
        faults = current.faults + 1
        updated = PeerDiscipline(
            faults=faults,
            quarantined=faults >= self.quarantine_threshold,
        )
        self._discipline[peer_id] = updated
        return updated

    def discipline(self, peer_id: str) -> PeerDiscipline:
        return self._discipline.get(peer_id, PeerDiscipline())

    def evidence(self) -> dict[str, object]:
        head = self.head
        return {
            "schema_version": "junca-finalized-fork-choice/v1",
            "chain_id": self.chain_id,
            "head_height": None if head is None else head.height,
            "head_hash": None if head is None else head.block_hash,
            "observed_peer_count": len(self._claims),
            "quarantined_peer_count": sum(
                item.quarantined for item in self._discipline.values()
            ),
            "safety_halted": self.safety_halted,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _fault(self, peer_id: str, message: str):
        self.record_protocol_fault(peer_id)
        raise ConsensusSyncError(message)


@dataclass(frozen=True)
class SnapshotDescriptor:
    chain_id: int
    height: int
    block_hash: str
    state_root: str
    checkpoint_digest: str
    chunk_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.chain_id <= 0 or self.height < 0 or not self.chunk_hashes:
            raise ConsensusSyncError("snapshot descriptor identity is invalid")
        for field in ("block_hash", "state_root", "checkpoint_digest"):
            _hash(getattr(self, field), field)
        for value in self.chunk_hashes:
            _hash(value, "chunk_hash")


@dataclass(frozen=True)
class CatchupResult:
    mode: str
    target_height: int
    verified_bytes: int
    status: str


class SnapshotCatchup:
    """Verifies a snapshot only against a canonical finalized claim."""

    def __init__(self, *, chain_id: int, threshold: int = 2048) -> None:
        if chain_id <= 0 or threshold <= 0:
            raise ConsensusSyncError("snapshot catch-up policy is invalid")
        self.chain_id = chain_id
        self.threshold = threshold

    def choose_mode(self, *, local_height: int, remote_height: int) -> str:
        if local_height < 0 or remote_height < local_height:
            raise ConsensusSyncError("catch-up heights are invalid")
        return "SNAPSHOT" if remote_height - local_height >= self.threshold else "BLOCK_RANGE"

    def verify(
        self,
        *,
        descriptor: SnapshotDescriptor,
        chunks: Sequence[bytes],
        finalized: FinalizedClaim,
    ) -> CatchupResult:
        if descriptor.chain_id != self.chain_id or finalized.chain_id != self.chain_id:
            raise ConsensusSyncError("snapshot chain_id mismatch")
        if (
            descriptor.height != finalized.height
            or descriptor.block_hash.lower() != finalized.block_hash.lower()
            or descriptor.state_root.lower() != finalized.state_root.lower()
        ):
            raise ConsensusSyncError("snapshot does not bind the finalized claim")
        if len(chunks) != len(descriptor.chunk_hashes):
            raise ConsensusSyncError("snapshot chunk count mismatch")
        verified_bytes = 0
        for expected, chunk in zip(descriptor.chunk_hashes, chunks, strict=True):
            if not isinstance(chunk, bytes) or len(chunk) > 2 * 1024 * 1024:
                raise ConsensusSyncError("snapshot chunk is invalid or oversized")
            actual = "0x" + hashlib.sha256(chunk).hexdigest()
            if actual != expected.lower():
                raise ConsensusSyncError("snapshot chunk digest mismatch")
            verified_bytes += len(chunk)
        checkpoint = _checkpoint_digest(descriptor, chunks)
        if checkpoint != descriptor.checkpoint_digest.lower():
            raise ConsensusSyncError("snapshot checkpoint digest mismatch")
        return CatchupResult("SNAPSHOT", descriptor.height, verified_bytes, "VERIFIED")


def evaluate_sync_acceptance(
    *,
    fork_choice: FinalizedForkChoice,
    local_height: int,
    minimum_peers: int,
    maximum_lag: int,
    restart_recovered: bool,
    snapshot_verified: bool,
) -> dict[str, object]:
    if minimum_peers < 2 or maximum_lag < 0 or local_height < 0:
        raise ConsensusSyncError("sync acceptance policy is invalid")
    head = fork_choice.head
    gates = {
        "finalized_head_present": head is not None,
        "peer_quorum": fork_choice.observed_peer_count >= minimum_peers,
        "within_finalized_lag": head is not None and head.height - local_height <= maximum_lag,
        "no_safety_halt": not fork_choice.safety_halted,
        "restart_recovery": restart_recovered is True,
        "snapshot_integrity": snapshot_verified is True,
    }
    failed = tuple(name for name, passed in gates.items() if not passed)
    return {
        "schema_version": "junca-sync-acceptance/v1",
        "state": "ACCEPTED" if not failed else "BLOCKED",
        "gates": gates,
        "failed_gates": failed,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def build_snapshot_descriptor(
    *,
    chain_id: int,
    height: int,
    block_hash: str,
    state_root: str,
    chunks: Sequence[bytes],
) -> SnapshotDescriptor:
    chunk_hashes = tuple("0x" + hashlib.sha256(chunk).hexdigest() for chunk in chunks)
    provisional = SnapshotDescriptor(
        chain_id=chain_id,
        height=height,
        block_hash=block_hash,
        state_root=state_root,
        checkpoint_digest="0x" + ("0" * 64),
        chunk_hashes=chunk_hashes,
    )
    return SnapshotDescriptor(
        chain_id=chain_id,
        height=height,
        block_hash=block_hash,
        state_root=state_root,
        checkpoint_digest=_checkpoint_digest(provisional, chunks),
        chunk_hashes=chunk_hashes,
    )


def _checkpoint_digest(descriptor: SnapshotDescriptor, chunks: Sequence[bytes]) -> str:
    body = (
        f"{descriptor.chain_id}:{descriptor.height}:"
        f"{descriptor.block_hash.lower()}:{descriptor.state_root.lower()}:"
        + ":".join(descriptor.chunk_hashes)
    ).encode("ascii")
    digest = hashlib.sha256(b"JUNCA_SNAPSHOT_CHECKPOINT_V1\x00" + body)
    for chunk in chunks:
        digest.update(chunk)
    return "0x" + digest.hexdigest()


def _hash(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ConsensusSyncError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise ConsensusSyncError(f"{field} must be a 32-byte hex value") from exc
