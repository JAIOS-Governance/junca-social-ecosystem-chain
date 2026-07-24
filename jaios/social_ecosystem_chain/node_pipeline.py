"""Deterministic node execution pipeline from mempool to finalized storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .finality import FinalityCertificate
from .mempool import BlockCandidate, TransactionPool
from .protocol_kernel import (
    BlockTransition,
    ProtocolConfig,
    SignatureVerifier,
    execute_block,
)
from .state_store import PersistentStateStore, StoredBlock


class NodePipelineError(ValueError):
    """Raised when proposal execution or finalization violates a node invariant."""


@dataclass(frozen=True)
class ExecutedProposal:
    height: int
    parent_hash: str
    block_hash: str
    candidate: BlockCandidate
    transition: BlockTransition

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-executed-proposal/v1",
            "height": self.height,
            "parent_hash": self.parent_hash,
            "block_hash": self.block_hash,
            "candidate_digest": self.candidate.candidate_digest,
            "state_root": self.transition.state_root,
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
        self.config = config
        self.pool = pool
        self.store = store
        self.signature_verifier = signature_verifier

    def execute_candidate(self) -> ExecutedProposal:
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
        header = {
            "candidate_digest": candidate.candidate_digest,
            "chain_id": self.config.chain_id,
            "height": height,
            "parent_hash": head.block_hash,
            "state_root": transition.state_root,
        }
        block_hash = "0x" + hashlib.sha256(
            b"JUNCA_BLOCK_HEADER_V1\x00"
            + json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ExecutedProposal(
            height=height,
            parent_hash=head.block_hash,
            block_hash=block_hash,
            candidate=candidate,
            transition=transition,
        )

    def commit_finalized(
        self,
        proposal: ExecutedProposal,
        certificate: FinalityCertificate,
    ) -> StoredBlock:
        current = self.store.head()
        if proposal.height != current.height + 1 or proposal.parent_hash != current.block_hash:
            raise NodePipelineError("proposal no longer extends the current head")
        if certificate.height != proposal.height or certificate.block_hash != proposal.block_hash:
            raise NodePipelineError("certificate does not bind the executed proposal")
        stored = self.store.commit_finalized_block(
            height=proposal.height,
            block_hash=proposal.block_hash,
            parent_hash=proposal.parent_hash,
            transition=proposal.transition,
            certificate=certificate,
        )
        self.pool.remove_included(proposal.candidate.transactions)
        return stored
