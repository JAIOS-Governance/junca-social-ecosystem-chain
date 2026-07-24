from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.finality import (
    FinalityCertificate,
    FinalityStateMachine,
    FinalityVote,
    Validator,
)
from jaios.social_ecosystem_chain.mempool import TransactionPool
from jaios.social_ecosystem_chain.node_pipeline import NodeExecutionPipeline, NodePipelineError
from jaios.social_ecosystem_chain.protocol_kernel import (
    AccountState,
    ProtocolConfig,
    TransactionEnvelope,
)
from jaios.social_ecosystem_chain.state_store import PersistentStateStore, StateStoreError


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)
ALICE = "0x" + ("a" * 40)
BOB = "0x" + ("b" * 40)


class PersistentStatePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.config = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=42_000,
            target_gas=21_000,
            initial_base_fee=1_000,
        )
        self.store = PersistentStateStore(
            Path(self.directory.name, "state.sqlite"),
            chain_id=CHAIN_ID,
        )
        self.store.initialize_genesis(
            block_hash=GENESIS,
            accounts={ALICE: AccountState(balance=1_000_000_000)},
            base_fee_per_gas=1_000,
        )
        self.pool = TransactionPool(self.config)
        self.verify = lambda item: bool(item.signature)
        self.pipeline = NodeExecutionPipeline(
            config=self.config,
            pool=self.pool,
            store=self.store,
            signature_verifier=self.verify,
        )
        self.validators = tuple(Validator(f"validator-{index}", 1) for index in range(1, 4))

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def transaction(self, nonce: int = 0) -> TransactionEnvelope:
        return TransactionEnvelope(
            chain_id=CHAIN_ID,
            sender=ALICE,
            recipient=BOB,
            nonce=nonce,
            value=100,
            gas_limit=21_000,
            max_fee_per_gas=2_000,
            max_priority_fee_per_gas=100,
            signature=f"tx-{nonce}".encode(),
        )

    def admit(self, transaction: TransactionEnvelope) -> None:
        self.pool.admit(
            transaction,
            account=self.store.accounts_at()[ALICE],
            current_base_fee=self.store.head().base_fee_per_gas,
            signature_verifier=self.verify,
        )

    def certificate(self, proposal) -> FinalityCertificate:
        machine = FinalityStateMachine(chain_id=CHAIN_ID, validators=self.validators)
        for validator in self.validators:
            machine.add_vote(
                FinalityVote(
                    chain_id=CHAIN_ID,
                    height=0,
                    round=0,
                    block_hash=GENESIS,
                    validator_id=validator.validator_id,
                    signature=validator.validator_id.encode(),
                ),
                verifier=self.verify,
            )
        certificate = None
        for validator in self.validators:
            certificate = machine.add_vote(
                FinalityVote(
                    chain_id=CHAIN_ID,
                    height=proposal.height,
                    round=0,
                    block_hash=proposal.block_hash,
                    validator_id=validator.validator_id,
                    signature=validator.validator_id.encode(),
                ),
                verifier=self.verify,
            )
        assert certificate is not None
        return certificate

    def test_genesis_is_idempotent_and_chain_bound(self) -> None:
        again = self.store.initialize_genesis(
            block_hash=GENESIS,
            accounts={ALICE: AccountState(balance=1_000_000_000)},
            base_fee_per_gas=1_000,
        )
        self.assertEqual(again.height, 0)
        with self.assertRaisesRegex(StateStoreError, "different identity"):
            self.store.initialize_genesis(
                block_hash="0x" + ("2" * 64),
                accounts={ALICE: AccountState(balance=1)},
                base_fee_per_gas=1_000,
            )

    def test_execute_finalize_commit_and_integrity(self) -> None:
        transaction = self.transaction()
        self.admit(transaction)
        proposal = self.pipeline.execute_candidate()
        self.assertEqual(proposal.height, 1)
        stored = self.pipeline.commit_finalized(proposal, self.certificate(proposal))
        self.assertTrue(stored.finalized)
        self.assertEqual(self.store.accounts_at()[BOB].balance, 100)
        self.assertEqual(len(self.pool), 0)
        evidence = self.store.integrity_check()
        self.assertEqual(evidence["integrity_status"], "VERIFIED")
        self.assertEqual(evidence["head_height"], 1)

    def test_proposal_is_deterministic_without_state_mutation(self) -> None:
        self.admit(self.transaction())
        first = self.pipeline.execute_candidate()
        second = self.pipeline.execute_candidate()
        self.assertEqual(first.block_hash, second.block_hash)
        self.assertEqual(self.store.head_height, 0)
        self.assertEqual(len(self.pool), 1)

    def test_wrong_certificate_block_is_rejected(self) -> None:
        self.admit(self.transaction())
        proposal = self.pipeline.execute_candidate()
        certificate = self.certificate(proposal)
        wrong = replace(certificate, block_hash="0x" + ("f" * 64))
        with self.assertRaisesRegex(NodePipelineError, "does not bind"):
            self.pipeline.commit_finalized(proposal, wrong)

    def test_below_quorum_certificate_is_rejected(self) -> None:
        self.admit(self.transaction())
        proposal = self.pipeline.execute_candidate()
        certificate = replace(
            self.certificate(proposal),
            signed_power=1,
            total_power=3,
        )
        with self.assertRaisesRegex(StateStoreError, "quorum"):
            self.store.commit_finalized_block(
                height=proposal.height,
                block_hash=proposal.block_hash,
                parent_hash=proposal.parent_hash,
                transition=proposal.transition,
                certificate=certificate,
            )

    def test_tampered_transition_state_root_is_rejected(self) -> None:
        self.admit(self.transaction())
        proposal = self.pipeline.execute_candidate()
        tampered = replace(proposal.transition, state_root="0x" + ("0" * 64))
        with self.assertRaisesRegex(StateStoreError, "state_root"):
            self.store.commit_finalized_block(
                height=proposal.height,
                block_hash=proposal.block_hash,
                parent_hash=proposal.parent_hash,
                transition=tampered,
                certificate=self.certificate(proposal),
            )

    def test_stale_proposal_cannot_commit_after_head_advances(self) -> None:
        self.admit(self.transaction())
        stale = self.pipeline.execute_candidate()
        self.pipeline.commit_finalized(stale, self.certificate(stale))
        with self.assertRaisesRegex(NodePipelineError, "current head"):
            self.pipeline.commit_finalized(stale, self.certificate(stale))

    def test_finalized_rollback_is_prohibited(self) -> None:
        with self.assertRaisesRegex(StateStoreError, "rollback"):
            self.store.rollback_to(-1)
        self.store.rollback_to(0)

    def test_checkpoint_round_trip_and_tamper_detection(self) -> None:
        checkpoint = self.store.export_checkpoint()
        evidence = self.store.verify_checkpoint(checkpoint)
        self.assertEqual(evidence["verification_status"], "VERIFIED")
        self.assertEqual(evidence["height"], 0)
        tampered = dict(checkpoint)
        tampered["state_root"] = "0x" + ("0" * 64)
        with self.assertRaisesRegex(StateStoreError, "digest mismatch"):
            self.store.verify_checkpoint(tampered)

    def test_database_chain_id_rebinding_is_rejected(self) -> None:
        path = Path(self.directory.name, "bound.sqlite")
        first = PersistentStateStore(path, chain_id=CHAIN_ID)
        first.close()
        with self.assertRaisesRegex(StateStoreError, "different chain_id"):
            PersistentStateStore(path, chain_id=1)


if __name__ == "__main__":
    unittest.main()
