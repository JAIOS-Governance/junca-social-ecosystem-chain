"""Deterministic node execution pipeline from mempool to finalized storage."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .finality import FinalityCertificate
from .mempool import BlockCandidate, TransactionPool
from .protocol_kernel import (
    BlockTransition,
    ProtocolConfig,
    ProtocolTransitionError,
    SignatureVerifier,
    compute_finalized_block_hash,
    compute_legacy_block_hash,
    compute_transition_root,
    execute_block,
    validate_transition_transaction_binding,
)
from .state_store import PersistentStateStore, StoredBlock


class NodePipelineError(ValueError):
    """Raised when proposal execution or finalization violates a node invariant."""


@dataclass(frozen=True)
class ExecutedProposal:
    height: int
    parent_hash: str
    block_hash: str
    block_timestamp: int | None
    candidate: BlockCandidate
    transition: BlockTransition
    transition_root: str
    header_version: int

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-executed-proposal/v2",
            "height": self.height,
            "parent_hash": self.parent_hash,
            "block_hash": self.block_hash,
            "timestamp": self.block_timestamp,
            "candidate_digest": self.candidate.candidate_digest,
            "state_root": self.transition.state_root,
            "transition_root": self.transition_root,
            "header_version": self.header_version,
            "receipt_commitment_status": (
                "COMMITTED"
                if self.header_version == 2
                else "COMPATIBILITY_PENDING_ACTIVATION"
            ),
            "transaction_count": len(self.candidate.transactions),
            "execution_status": "EXECUTED_NOT_FINALIZED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


class NodeExecutionPipeline:
    def __init__(
        self,
        *,
        config: ProtocolConfig,
        pool: TransactionPool,
        store: PersistentStateStore,
        signature_verifier: SignatureVerifier,
    ) -> None:
        if store.chain_id != config.chain_id:
            raise NodePipelineError("store and protocol chain_id mismatch")
        if not callable(signature_verifier):
            raise NodePipelineError("signature verifier is required")
        activation_height = store.bind_block_header_v2_activation(
            config.block_header_v2_activation_height
        )
        self.config = replace(
            config,
            block_header_v2_activation_height=activation_height,
        )
        self.pool = pool
        self.store = store
        self.signature_verifier = signature_verifier

    def execute_candidate(
        self, *, block_timestamp: int | None = None
    ) -> ExecutedProposal:
        if (
            block_timestamp is not None
            and (
                isinstance(block_timestamp, bool)
                or not isinstance(block_timestamp, int)
                or block_timestamp <= 0
            )
        ):
            raise NodePipelineError("block timestamp must be a positive integer")
        head = self.store.head()
        accounts = self.store.accounts_at()
        candidate = self.pool.build_candidate(
            accounts,
            current_base_fee=head.base_fee_per_gas,
        )
        transition = execute_block(
            self.config,
            parent_base_fee=head.base_fee_per_gas,
            parent_gas_used=head.gas_used,
            accounts=accounts,
            transactions=candidate.transactions,
            signature_verifier=self.signature_verifier,
        )
        height = head.height + 1
        try:
            validate_transition_transaction_binding(
                self.config,
                transactions=candidate.transactions,
                transition=transition,
                candidate_gas_used=candidate.gas_used,
            )
            transition_root = compute_transition_root(transition)
            if self._uses_v2_header(height):
                header_version = 2
                block_hash = compute_finalized_block_hash(
                    chain_id=self.config.chain_id,
                    height=height,
                    parent_hash=head.block_hash,
                    transition=transition,
                    block_timestamp=block_timestamp,
                )
            else:
                header_version = 1
                block_hash = compute_legacy_block_hash(
                    chain_id=self.config.chain_id,
                    height=height,
                    parent_hash=head.block_hash,
                    state_root=transition.state_root,
                    candidate_digest=candidate.candidate_digest,
                    block_timestamp=block_timestamp,
                )
        except ProtocolTransitionError as exc:
            raise NodePipelineError(f"proposal commitment failed: {exc}") from exc
        return ExecutedProposal(
            height=height,
            parent_hash=head.block_hash,
            block_hash=block_hash,
            block_timestamp=block_timestamp,
            candidate=candidate,
            transition=transition,
            transition_root=transition_root,
            header_version=header_version,
        )

    def commit_finalized(
        self,
        proposal: ExecutedProposal,
        certificate: FinalityCertificate,
    ) -> StoredBlock:
        current = self.store.head()
        if proposal.height != current.height + 1 or proposal.parent_hash != current.block_hash:
            raise NodePipelineError("proposal no longer extends the current head")
        try:
            validate_transition_transaction_binding(
                self.config,
                transactions=proposal.candidate.transactions,
                transition=proposal.transition,
                candidate_gas_used=proposal.candidate.gas_used,
            )
            expected_transition_root = compute_transition_root(proposal.transition)
            expected_header_version = 2 if self._uses_v2_header(proposal.height) else 1
            if expected_header_version == 2:
                expected_block_hash = compute_finalized_block_hash(
                    chain_id=self.config.chain_id,
                    height=proposal.height,
                    parent_hash=proposal.parent_hash,
                    transition=proposal.transition,
                    block_timestamp=proposal.block_timestamp,
                )
            else:
                expected_block_hash = compute_legacy_block_hash(
                    chain_id=self.config.chain_id,
                    height=proposal.height,
                    parent_hash=proposal.parent_hash,
                    state_root=proposal.transition.state_root,
                    candidate_digest=proposal.candidate.candidate_digest,
                    block_timestamp=proposal.block_timestamp,
                )
        except ProtocolTransitionError as exc:
            raise NodePipelineError(f"proposal commitment failed: {exc}") from exc
        if proposal.transition_root != expected_transition_root:
            raise NodePipelineError("proposal transition_root commitment mismatch")
        if proposal.header_version != expected_header_version:
            raise NodePipelineError("proposal block header version mismatch")
        if proposal.block_hash != expected_block_hash:
            raise NodePipelineError("proposal block_hash commitment mismatch")
        if certificate.height != proposal.height or certificate.block_hash != proposal.block_hash:
            raise NodePipelineError("certificate does not bind the executed proposal")
        stored = self.store.commit_finalized_block(
            height=proposal.height,
            block_hash=proposal.block_hash,
            parent_hash=proposal.parent_hash,
            transition=proposal.transition,
            certificate=certificate,
            block_timestamp=proposal.block_timestamp,
            header_version=proposal.header_version,
        )
        self.pool.remove_included(proposal.candidate.transactions)
        return stored

    def _uses_v2_header(self, height: int) -> bool:
        activation = self.config.block_header_v2_activation_height
        return activation is not None and height >= activation
