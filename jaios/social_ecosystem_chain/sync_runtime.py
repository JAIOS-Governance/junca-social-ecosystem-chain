"""Authenticated peer synchronization orchestration for JUNCA validators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .consensus_sync import (
    ConsensusSyncError,
    FinalizedClaim,
    FinalizedForkChoice,
    SnapshotCatchup,
    SnapshotDescriptor,
)
from .wire_protocol import (
    AuthenticatedPeerSession,
    MessageType,
    SnapshotManifest,
    WireProtocolError,
    validate_block_range,
)
from .sync_finality import (
    CertifiedFinalityVerifier,
    SyncFinalityError,
    proof_from_payload,
)


class SyncRuntimeError(ValueError):
    """Raised when authenticated synchronization input fails closed."""


@dataclass(frozen=True)
class SyncPlan:
    peer_id: str
    mode: str
    local_height: int
    target_height: int
    request_frame: bytes


@dataclass(frozen=True)
class BlockRangeAcceptance:
    peer_id: str
    start_height: int
    end_height: int
    block_count: int
    terminal_hash: str
    terminal_state_root: str
    status: str = "VERIFIED"


class ValidatorSyncRuntime:
    """Binds authenticated wire sessions to finalized fork choice and catch-up."""

    def __init__(
        self,
        *,
        chain_id: int,
        genesis_hash: str,
        expected_total_power: int,
        finality_verifier: CertifiedFinalityVerifier,
        snapshot_threshold: int = 2048,
        quarantine_threshold: int = 3,
    ) -> None:
        if not isinstance(finality_verifier, CertifiedFinalityVerifier):
            raise SyncRuntimeError("certified finality verifier is required")
        if finality_verifier.chain_id != chain_id:
            raise SyncRuntimeError("finality verifier chain_id mismatch")
        if finality_verifier.schedule.at_height(0).total_power != expected_total_power:
            raise SyncRuntimeError("initial validator power mismatch")
        self.finality_verifier = finality_verifier
        self.fork_choice = FinalizedForkChoice(
            chain_id=chain_id,
            genesis_hash=genesis_hash,
            expected_total_power=expected_total_power,
            quarantine_threshold=quarantine_threshold,
            power_resolver=lambda height: finality_verifier.schedule.at_height(
                height
            ).total_power,
        )
        self.snapshot = SnapshotCatchup(
            chain_id=chain_id,
            threshold=snapshot_threshold,
        )
        self._sessions: dict[str, AuthenticatedPeerSession] = {}
        self._status_sequences: dict[str, int] = {}
        self._plans: dict[str, SyncPlan] = {}

    def register(self, session: AuthenticatedPeerSession) -> str:
        peer_id = session.remote.node_id
        if peer_id in self._sessions:
            raise SyncRuntimeError("peer session is already registered")
        if session.local.chain_id != self.fork_choice.chain_id:
            raise SyncRuntimeError("peer session chain_id mismatch")
        if session.local.genesis_hash.lower() != self.fork_choice.genesis_hash:
            raise SyncRuntimeError("peer session genesis mismatch")
        self._sessions[peer_id] = session
        return peer_id

    def receive_status(self, peer_id: str, frame: bytes) -> FinalizedClaim:
        session = self._session(peer_id)
        faults_before = self.fork_choice.discipline(peer_id).faults
        try:
            envelope = session.receive(frame)
            if envelope.message_type is not MessageType.STATUS:
                raise SyncRuntimeError("expected authenticated STATUS frame")
            required = {
                "chain_id",
                "genesis_hash",
                "height",
                "block_hash",
                "parent_hash",
                "state_root",
                "signed_power",
                "total_power",
            }
            if set(envelope.payload) != required:
                raise SyncRuntimeError("STATUS fields are invalid")
            if envelope.sequence <= self._status_sequences.get(peer_id, -1):
                raise SyncRuntimeError("STATUS sequence did not advance")
            claim = FinalizedClaim(peer_id=peer_id, **envelope.payload)
            self.fork_choice.observe(claim)
            self._status_sequences[peer_id] = envelope.sequence
            return claim
        except (WireProtocolError, ConsensusSyncError, SyncRuntimeError) as exc:
            if self.fork_choice.discipline(peer_id).faults == faults_before:
                self.fork_choice.record_protocol_fault(peer_id)
            raise SyncRuntimeError(str(exc)) from exc

    def plan(
        self,
        *,
        peer_id: str,
        local_height: int,
        target_height: int,
    ) -> SyncPlan:
        session = self._session(peer_id)
        claim = self.fork_choice.head
        if claim is None or claim.height != target_height:
            raise SyncRuntimeError("target is not the canonical finalized head")
        if local_height >= target_height:
            raise SyncRuntimeError("catch-up target must advance local height")
        mode = self.snapshot.choose_mode(
            local_height=local_height,
            remote_height=target_height,
        )
        if mode == "SNAPSHOT":
            message_type = MessageType.GET_SNAPSHOT
            payload = {"height": target_height}
        else:
            message_type = MessageType.GET_BLOCK_RANGE
            payload = {
                "start_height": local_height + 1,
                "limit": min(512, target_height - local_height),
            }
        plan = SyncPlan(
            peer_id=peer_id,
            mode=mode,
            local_height=local_height,
            target_height=target_height,
            request_frame=session.send(message_type, payload),
        )
        self._plans[peer_id] = plan
        return plan

    def receive_block_range(
        self,
        *,
        peer_id: str,
        frame: bytes,
        local_hash: str,
    ) -> BlockRangeAcceptance:
        plan = self._plan(peer_id, "BLOCK_RANGE")
        session = self._session(peer_id)
        try:
            envelope = session.receive(frame)
            if envelope.message_type is not MessageType.BLOCK_RANGE:
                raise SyncRuntimeError("expected authenticated BLOCK_RANGE frame")
            if set(envelope.payload) != {"blocks", "finality_proofs"}:
                raise SyncRuntimeError("BLOCK_RANGE fields are invalid")
            blocks = envelope.payload["blocks"]
            raw_proofs = envelope.payload["finality_proofs"]
            if (
                not isinstance(blocks, list)
                or not isinstance(raw_proofs, list)
                or len(blocks) != len(raw_proofs)
            ):
                raise SyncRuntimeError("BLOCK_RANGE proof count is invalid")
            validate_block_range(blocks, requested_start=plan.local_height + 1)
            certificates = [
                self.finality_verifier.verify(proof_from_payload(item))
                for item in raw_proofs
            ]
            for block, certificate in zip(blocks, certificates, strict=True):
                if (
                    certificate.height != block["height"]
                    or certificate.block_hash != block["block_hash"].lower()
                    or certificate.certificate_hash
                    != block["certificate_hash"].lower()
                ):
                    raise SyncRuntimeError(
                        "BLOCK_RANGE certificate does not bind the block"
                    )
            first = blocks[0]
            last = blocks[-1]
            if first["parent_hash"].lower() != local_hash.lower():
                raise SyncRuntimeError("BLOCK_RANGE is not anchored to local head")
            if last["height"] > plan.target_height:
                raise SyncRuntimeError("BLOCK_RANGE exceeds finalized target")
            finalized = self.fork_choice.head
            if (
                last["height"] == plan.target_height
                and finalized is not None
                and (
                    last["block_hash"].lower() != finalized.block_hash.lower()
                    or last["state_root"].lower() != finalized.state_root.lower()
                )
            ):
                raise SyncRuntimeError("BLOCK_RANGE terminal finality mismatch")
            del self._plans[peer_id]
            return BlockRangeAcceptance(
                peer_id=peer_id,
                start_height=first["height"],
                end_height=last["height"],
                block_count=len(blocks),
                terminal_hash=last["block_hash"].lower(),
                terminal_state_root=last["state_root"].lower(),
            )
        except (WireProtocolError, SyncFinalityError, SyncRuntimeError) as exc:
            self.fork_choice.record_protocol_fault(peer_id)
            raise SyncRuntimeError(str(exc)) from exc

    def receive_snapshot(
        self,
        *,
        peer_id: str,
        frame: bytes,
        chunks: Sequence[bytes],
    ):
        plan = self._plan(peer_id, "SNAPSHOT")
        session = self._session(peer_id)
        try:
            envelope = session.receive(frame)
            if envelope.message_type is not MessageType.SNAPSHOT_MANIFEST:
                raise SyncRuntimeError("expected authenticated SNAPSHOT_MANIFEST frame")
            required = {
                "chain_id",
                "height",
                "block_hash",
                "state_root",
                "checkpoint_digest",
                "chunk_hashes",
            }
            if set(envelope.payload) != required:
                raise SyncRuntimeError("SNAPSHOT_MANIFEST fields are invalid")
            payload = dict(envelope.payload)
            payload["chunk_hashes"] = tuple(payload["chunk_hashes"])
            manifest = SnapshotManifest(**payload)
            manifest.verify_chunks(chunks)
            descriptor = SnapshotDescriptor(**payload)
            finalized = self.fork_choice.head
            if finalized is None or descriptor.height != plan.target_height:
                raise SyncRuntimeError("snapshot target is no longer canonical")
            result = self.snapshot.verify(
                descriptor=descriptor,
                chunks=chunks,
                finalized=finalized,
            )
            del self._plans[peer_id]
            return result
        except (WireProtocolError, ConsensusSyncError, SyncRuntimeError) as exc:
            self.fork_choice.record_protocol_fault(peer_id)
            raise SyncRuntimeError(str(exc)) from exc

    def evidence(self) -> dict[str, object]:
        evidence = self.fork_choice.evidence()
        evidence.update(
            {
                "schema_version": "junca-validator-sync-runtime/v1",
                "authenticated_session_count": len(self._sessions),
                "active_plan_count": len(self._plans),
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            }
        )
        return evidence

    def _session(self, peer_id: str) -> AuthenticatedPeerSession:
        if self.fork_choice.discipline(peer_id).quarantined:
            raise SyncRuntimeError("peer is quarantined")
        try:
            return self._sessions[peer_id]
        except KeyError as exc:
            raise SyncRuntimeError("peer session is not registered") from exc

    def _plan(self, peer_id: str, mode: str) -> SyncPlan:
        try:
            plan = self._plans[peer_id]
        except KeyError as exc:
            raise SyncRuntimeError("peer has no active catch-up plan") from exc
        if plan.mode != mode:
            raise SyncRuntimeError("catch-up response mode mismatch")
        return plan
