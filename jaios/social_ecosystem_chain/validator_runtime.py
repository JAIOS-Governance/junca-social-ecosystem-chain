"""Live validator coordination across execution, signing and finality.

The runtime never accepts private key material. Consensus votes are produced
through an injected KMS/HSM signer and verified again before they can advance
the finalized state store.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Mapping

from .finality import FinalityCertificate, FinalityStateMachine, FinalityVote
from .node_pipeline import ExecutedProposal, NodeExecutionPipeline
from .state_store import StoredBlock
from .sync_finality import ValidatorSet, ValidatorSetSchedule


class ValidatorRuntimeError(ValueError):
    """Raised when live validator coordination violates a safety invariant."""


ConsensusSigner = Callable[[str, bytes], bytes]
ConsensusSignatureVerifier = Callable[[str, bytes, bytes], bool]


@dataclass(frozen=True)
class ValidatorSignerBinding:
    validator_id: str
    key_resource: str

    def __post_init__(self) -> None:
        if not self.validator_id:
            raise ValidatorRuntimeError("validator_id is required")
        if not self.key_resource.startswith(("kms://", "hsm://")):
            raise ValidatorRuntimeError("validator signer must use a KMS/HSM resource")

    def as_evidence(self) -> dict[str, str]:
        return {
            "validator_id": self.validator_id,
            "key_resource_digest": hashlib.sha256(
                self.key_resource.encode("utf-8")
            ).hexdigest(),
        }


@dataclass(frozen=True)
class FinalizedProposal:
    proposal: ExecutedProposal
    certificate: FinalityCertificate
    stored_block: StoredBlock

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-live-validator-finalization/v1",
            "height": self.stored_block.height,
            "block_hash": self.stored_block.block_hash,
            "state_root": self.stored_block.state_root,
            "certificate_hash": self.certificate.certificate_hash,
            "signed_power": self.certificate.signed_power,
            "total_power": self.certificate.total_power,
            "finality_status": "FINALIZED",
            "governance": "JAIOS Institutional Governance",
            "network": "Public Testnet / No Monetary Value",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


class LiveValidatorRuntime:
    """Coordinate one deterministic proposal through external signing to commit."""

    def __init__(
        self,
        *,
        pipeline: NodeExecutionPipeline,
        schedule: ValidatorSetSchedule,
        signer_bindings: Mapping[str, ValidatorSignerBinding],
        signer: ConsensusSigner,
        signature_verifier: ConsensusSignatureVerifier,
    ) -> None:
        if not callable(signer) or not callable(signature_verifier):
            raise ValidatorRuntimeError("signer and signature verifier are required")
        initial = schedule.at_height(0)
        if pipeline.config.chain_id <= 0:
            raise ValidatorRuntimeError("pipeline chain identity is invalid")
        self.pipeline = pipeline
        self.schedule = schedule
        self.signer = signer
        self.signature_verifier = signature_verifier
        self.bindings = self._validate_bindings(initial, signer_bindings)
        self._proposal: ExecutedProposal | None = None
        self._machine: FinalityStateMachine | None = None
        self._active_set: ValidatorSet | None = None
        self._round = 0

    @property
    def pending_proposal(self) -> ExecutedProposal | None:
        return self._proposal

    def replace_signer_bindings(
        self,
        bindings: Mapping[str, ValidatorSignerBinding],
    ) -> None:
        """Atomically bind the exact validator set for the next block height."""
        if self._proposal is not None:
            raise ValidatorRuntimeError(
                "signer bindings cannot change while a proposal is pending"
            )
        next_set = self.schedule.at_height(self.pipeline.store.head_height + 1)
        self.bindings = self._validate_bindings(next_set, bindings)

    def propose(self, *, round: int = 0) -> ExecutedProposal:
        if self._proposal is not None:
            raise ValidatorRuntimeError("a proposal is already awaiting finality")
        if isinstance(round, bool) or not isinstance(round, int) or round < 0:
            raise ValidatorRuntimeError("round must be a non-negative integer")
        proposal = self.pipeline.execute_candidate()
        active = self.schedule.at_height(proposal.height)
        self._validate_bindings(active, self.bindings)
        self._proposal = proposal
        self._active_set = active
        self._machine = FinalityStateMachine(
            chain_id=self.pipeline.config.chain_id,
            validators=active.validators,
            initial_finalized_height=self.pipeline.store.head_height,
        )
        self._round = round
        return proposal

    def sign_vote(self, validator_id: str) -> FinalityVote:
        proposal, active, _ = self._pending()
        if validator_id not in {item.validator_id for item in active.validators}:
            raise ValidatorRuntimeError("validator is not active for proposal height")
        try:
            binding = self.bindings[validator_id]
        except KeyError as exc:
            raise ValidatorRuntimeError("validator signer binding is missing") from exc
        unsigned = FinalityVote(
            chain_id=self.pipeline.config.chain_id,
            height=proposal.height,
            round=self._round,
            block_hash=proposal.block_hash,
            validator_id=validator_id,
            signature=b"",
        )
        signature = self.signer(binding.key_resource, unsigned.signing_payload)
        if not isinstance(signature, bytes) or len(signature) not in {64, 65}:
            raise ValidatorRuntimeError("signer returned an invalid consensus signature")
        return FinalityVote(
            chain_id=unsigned.chain_id,
            height=unsigned.height,
            round=unsigned.round,
            block_hash=unsigned.block_hash,
            validator_id=unsigned.validator_id,
            signature=signature,
        )

    def accept_vote(self, vote: FinalityVote) -> FinalizedProposal | None:
        proposal, active, machine = self._pending()
        if (
            vote.height != proposal.height
            or vote.round != self._round
            or vote.block_hash.lower() != proposal.block_hash
        ):
            raise ValidatorRuntimeError("vote does not bind the pending proposal")
        if active.set_hash != self.schedule.at_height(vote.height).set_hash:
            raise ValidatorRuntimeError("active validator set changed during proposal")

        def verify(item: FinalityVote) -> bool:
            return self.signature_verifier(
                item.validator_id,
                item.signing_payload,
                item.signature,
            )

        certificate = machine.add_vote(vote, verifier=verify)
        if certificate is None:
            return None
        stored = self.pipeline.commit_finalized(proposal, certificate)
        result = FinalizedProposal(
            proposal=proposal,
            certificate=certificate,
            stored_block=stored,
        )
        self._proposal = None
        self._machine = None
        self._active_set = None
        return result

    def evidence(self) -> dict[str, object]:
        pending = self._proposal
        active = (
            self._active_set
            if self._active_set is not None
            else self.schedule.at_height(self.pipeline.store.head_height + 1)
        )
        return {
            "schema_version": "junca-live-validator-runtime/v1",
            "chain_id": self.pipeline.config.chain_id,
            "head_height": self.pipeline.store.head_height,
            "pending_height": None if pending is None else pending.height,
            "validator_set_epoch": active.epoch,
            "validator_set_hash": active.set_hash,
            "signer_bindings": [
                self.bindings[item.validator_id].as_evidence()
                for item in active.validators
            ],
            "private_key_material_accepted": False,
            "governance": "JAIOS Institutional Governance",
            "network": "Public Testnet / No Monetary Value",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _pending(
        self,
    ) -> tuple[ExecutedProposal, ValidatorSet, FinalityStateMachine]:
        if self._proposal is None or self._active_set is None or self._machine is None:
            raise ValidatorRuntimeError("no proposal is awaiting finality")
        return self._proposal, self._active_set, self._machine

    @staticmethod
    def _validate_bindings(
        validator_set: ValidatorSet,
        bindings: Mapping[str, ValidatorSignerBinding],
    ) -> dict[str, ValidatorSignerBinding]:
        if not isinstance(bindings, Mapping):
            raise ValidatorRuntimeError("signer bindings must be a mapping")
        normalized = dict(bindings)
        expected = {item.validator_id for item in validator_set.validators}
        if set(normalized) != expected:
            raise ValidatorRuntimeError(
                "signer bindings must exactly match the active validator set"
            )
        resources: set[str] = set()
        for validator_id, binding in normalized.items():
            if (
                not isinstance(binding, ValidatorSignerBinding)
                or binding.validator_id != validator_id
            ):
                raise ValidatorRuntimeError("signer binding identity mismatch")
            if binding.key_resource in resources:
                raise ValidatorRuntimeError("validator signer resources must be distinct")
            resources.add(binding.key_resource)
        return normalized
