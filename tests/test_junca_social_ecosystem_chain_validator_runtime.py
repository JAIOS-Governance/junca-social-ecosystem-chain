from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest

from jaios.social_ecosystem_chain.finality import FinalityVote, Validator
from jaios.social_ecosystem_chain.mempool import TransactionPool
from jaios.social_ecosystem_chain.node_pipeline import NodeExecutionPipeline
from jaios.social_ecosystem_chain.protocol_kernel import AccountState, ProtocolConfig
from jaios.social_ecosystem_chain.state_store import PersistentStateStore
from jaios.social_ecosystem_chain.sync_finality import ValidatorSet, ValidatorSetSchedule
from jaios.social_ecosystem_chain.validator_runtime import (
    LiveValidatorRuntime,
    ValidatorRuntimeError,
    ValidatorSignerBinding,
)


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)
ALICE = "0x" + ("a" * 40)


def signature(resource: str, payload: bytes) -> bytes:
    first = hashlib.sha256(resource.encode() + b"\x00" + payload).digest()
    second = hashlib.sha256(payload + b"\x00" + resource.encode()).digest()
    return first + second


class LiveValidatorRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        config = ProtocolConfig(chain_id=CHAIN_ID)
        self.store = PersistentStateStore(
            Path(self.directory.name, "state.sqlite"),
            chain_id=CHAIN_ID,
        )
        self.store.initialize_genesis(
            block_hash=GENESIS,
            accounts={ALICE: AccountState(balance=1_000_000_000)},
            base_fee_per_gas=config.initial_base_fee,
        )
        pool = TransactionPool(config)
        self.pipeline = NodeExecutionPipeline(
            config=config,
            pool=pool,
            store=self.store,
            signature_verifier=lambda item: bool(item.signature),
        )
        self.initial = ValidatorSet(
            epoch=0,
            activation_height=0,
            validators=tuple(
                Validator(f"validator-{index}", 1) for index in range(1, 4)
            ),
        )
        self.schedule = ValidatorSetSchedule(self.initial)
        self.bindings = {
            item.validator_id: ValidatorSignerBinding(
                validator_id=item.validator_id,
                key_resource=f"kms://junca-testnet/{item.validator_id}",
            )
            for item in self.initial.validators
        }
        self.runtime = self.build_runtime()

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def build_runtime(self, **overrides) -> LiveValidatorRuntime:
        signer = overrides.pop("signer", signature)
        verifier = overrides.pop(
            "signature_verifier",
            lambda validator_id, payload, value: value
            == signature(self.bindings[validator_id].key_resource, payload),
        )
        return LiveValidatorRuntime(
            pipeline=self.pipeline,
            schedule=self.schedule,
            signer_bindings=overrides.pop("signer_bindings", self.bindings),
            signer=signer,
            signature_verifier=verifier,
            **overrides,
        )

    def test_live_votes_finalize_and_atomically_commit(self) -> None:
        proposal = self.runtime.propose()
        self.assertEqual(proposal.height, 1)
        self.assertIsNone(
            self.runtime.accept_vote(self.runtime.sign_vote("validator-1"))
        )
        self.assertIsNone(
            self.runtime.accept_vote(self.runtime.sign_vote("validator-2"))
        )
        result = self.runtime.accept_vote(self.runtime.sign_vote("validator-3"))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(self.store.head_height, 1)
        self.assertEqual(
            result.stored_block.certificate_hash,
            result.certificate.certificate_hash,
        )
        self.assertEqual(result.as_evidence()["finality_status"], "FINALIZED")
        self.assertIsNone(self.runtime.pending_proposal)

    def test_runtime_never_exposes_key_resource_in_evidence(self) -> None:
        evidence = self.runtime.evidence()
        rendered = str(evidence)
        self.assertNotIn("kms://", rendered)
        self.assertFalse(evidence["private_key_material_accepted"])
        self.assertFalse(evidence["mainnet_changed"])

    def test_signer_bindings_are_exact_distinct_and_keyless(self) -> None:
        missing = dict(self.bindings)
        missing.pop("validator-3")
        with self.assertRaisesRegex(ValidatorRuntimeError, "exactly match"):
            self.build_runtime(signer_bindings=missing)
        duplicate = dict(self.bindings)
        duplicate["validator-3"] = ValidatorSignerBinding(
            "validator-3", self.bindings["validator-2"].key_resource
        )
        with self.assertRaisesRegex(ValidatorRuntimeError, "distinct"):
            self.build_runtime(signer_bindings=duplicate)
        with self.assertRaisesRegex(ValidatorRuntimeError, "KMS/HSM"):
            ValidatorSignerBinding("validator-1", "file:///private-key")

    def test_invalid_provider_signature_fails_closed(self) -> None:
        rejecting = self.build_runtime(signature_verifier=lambda *args: False)
        rejecting.propose()
        with self.assertRaisesRegex(ValueError, "signature verification"):
            rejecting.accept_vote(rejecting.sign_vote("validator-1"))
        malformed = self.build_runtime(signer=lambda resource, payload: b"short")
        malformed.propose()
        with self.assertRaisesRegex(ValidatorRuntimeError, "invalid consensus"):
            malformed.sign_vote("validator-1")

    def test_vote_must_bind_pending_proposal(self) -> None:
        proposal = self.runtime.propose(round=2)
        valid = self.runtime.sign_vote("validator-1")
        wrong = FinalityVote(
            chain_id=valid.chain_id,
            height=valid.height,
            round=valid.round + 1,
            block_hash=proposal.block_hash,
            validator_id=valid.validator_id,
            signature=valid.signature,
        )
        with self.assertRaisesRegex(ValidatorRuntimeError, "pending proposal"):
            self.runtime.accept_vote(wrong)
        with self.assertRaisesRegex(ValidatorRuntimeError, "already awaiting"):
            self.runtime.propose()

    def test_epoch_rotation_requires_new_exact_signer_set(self) -> None:
        next_set = ValidatorSet(
            epoch=1,
            activation_height=1,
            validators=tuple(
                Validator(f"next-{index}", 1) for index in range(1, 4)
            ),
        )
        self.schedule.register(next_set)
        with self.assertRaisesRegex(ValidatorRuntimeError, "exactly match"):
            self.runtime.propose()
        next_bindings = {
            item.validator_id: ValidatorSignerBinding(
                item.validator_id,
                f"hsm://junca-testnet/{item.validator_id}",
            )
            for item in next_set.validators
        }
        self.runtime.replace_signer_bindings(next_bindings)
        proposal = self.runtime.propose()
        self.assertEqual(proposal.height, 1)
        self.assertEqual(self.runtime.evidence()["validator_set_epoch"], 1)
        with self.assertRaisesRegex(ValidatorRuntimeError, "cannot change"):
            self.runtime.replace_signer_bindings(next_bindings)

    def test_non_active_validator_and_no_pending_proposal_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidatorRuntimeError, "no proposal"):
            self.runtime.sign_vote("validator-1")
        self.runtime.propose()
        with self.assertRaisesRegex(ValidatorRuntimeError, "not active"):
            self.runtime.sign_vote("unknown")


if __name__ == "__main__":
    unittest.main()
