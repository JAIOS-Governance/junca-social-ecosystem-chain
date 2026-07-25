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

    def test_checkpoint_rejects_noncanonical_identity_and_account_schema(self) -> None:
        checkpoint = self.store.export_checkpoint()

        uppercase_hash = dict(checkpoint)
        uppercase_hash["block_hash"] = "0x" + ("AB" * 32)
        uppercase_hash["checkpoint_digest"] = self._checkpoint_digest(uppercase_hash)
        with self.assertRaisesRegex(StateStoreError, "block_hash is not canonical"):
            self.store.verify_checkpoint(uppercase_hash)

        extra_account_field = dict(checkpoint)
        extra_account_field["accounts"] = {
            ALICE: {
                "balance": 1_000_000_000,
                "nonce": 0,
                "memo": "not-consensus-state",
            }
        }
        extra_account_field["checkpoint_digest"] = self._checkpoint_digest(
            extra_account_field
        )
        with self.assertRaisesRegex(StateStoreError, "accounts are invalid"):
            self.store.verify_checkpoint(extra_account_field)

        not_finalized = dict(checkpoint)
        not_finalized["finalized"] = False
        not_finalized["checkpoint_digest"] = self._checkpoint_digest(not_finalized)
        with self.assertRaisesRegex(StateStoreError, "not finalized"):
            self.store.verify_checkpoint(not_finalized)

    def test_genesis_checkpoint_rejects_certificate_and_wrong_parent(self) -> None:
        checkpoint = self.store.export_checkpoint()

        certificate = dict(checkpoint)
        certificate["certificate_hash"] = "0x" + ("2" * 64)
        certificate["checkpoint_digest"] = self._checkpoint_digest(certificate)
        with self.assertRaisesRegex(StateStoreError, "cannot contain a certificate"):
            self.store.verify_checkpoint(certificate)

        parent = dict(checkpoint)
        parent["parent_hash"] = "0x" + ("3" * 64)
        parent["checkpoint_digest"] = self._checkpoint_digest(parent)
        with self.assertRaisesRegex(StateStoreError, "genesis checkpoint parent_hash"):
            self.store.verify_checkpoint(parent)

    def test_read_and_export_fail_closed_on_corrupt_snapshot(self) -> None:
        self.store.connection.execute(
            "UPDATE blocks SET accounts_json=? WHERE height=0",
            (
                '{"0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa":'
                '{"balance":1000000000,"memo":"ignored","nonce":0}}',
            ),
        )
        with self.assertRaisesRegex(StateStoreError, "snapshot fields"):
            self.store.accounts_at()
        with self.assertRaisesRegex(StateStoreError, "snapshot fields"):
            self.store.export_checkpoint()

    def test_finalized_checkpoint_restores_and_extends_on_restart(self) -> None:
        self.admit(self.transaction())
        first = self.pipeline.execute_candidate()
        self.pipeline.commit_finalized(first, self.certificate(first))
        checkpoint = self.store.export_checkpoint()

        restored = PersistentStateStore(
            Path(self.directory.name, "restored.sqlite"),
            chain_id=CHAIN_ID,
        )
        try:
            head = restored.restore_checkpoint(
                checkpoint,
                trusted_checkpoint_digest=checkpoint["checkpoint_digest"],
                trusted_block_hash=checkpoint["block_hash"],
            )
            self.assertEqual(head.height, 1)
            self.assertEqual(restored.accounts_at(), self.store.accounts_at())
            integrity = restored.integrity_check()
            self.assertEqual(integrity["base_height"], 1)
            self.assertEqual(integrity["head_height"], 1)

            pipeline = NodeExecutionPipeline(
                config=self.config,
                pool=TransactionPool(self.config),
                store=restored,
                signature_verifier=self.verify,
            )
            proposal = pipeline.execute_candidate()
            self.assertEqual(proposal.height, 2)
            machine = FinalityStateMachine(
                chain_id=CHAIN_ID,
                validators=self.validators,
                initial_finalized_height=1,
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
            committed = pipeline.commit_finalized(proposal, certificate)
            self.assertEqual(committed.height, 2)
            self.assertEqual(restored.integrity_check()["head_height"], 2)
        finally:
            restored.close()

    def test_checkpoint_restore_fails_closed(self) -> None:
        checkpoint = self.store.export_checkpoint()
        with self.assertRaisesRegex(StateStoreError, "empty"):
            self.store.restore_checkpoint(
                checkpoint,
                trusted_checkpoint_digest=checkpoint["checkpoint_digest"],
                trusted_block_hash=checkpoint["block_hash"],
            )

        wrong_chain = PersistentStateStore(
            Path(self.directory.name, "wrong-chain.sqlite"),
            chain_id=1,
        )
        try:
            with self.assertRaisesRegex(StateStoreError, "chain_id mismatch"):
                wrong_chain.restore_checkpoint(
                    checkpoint,
                    trusted_checkpoint_digest=checkpoint["checkpoint_digest"],
                    trusted_block_hash=checkpoint["block_hash"],
                )
            self.assertEqual(wrong_chain.head_height, -1)
        finally:
            wrong_chain.close()

        tampered = dict(checkpoint)
        tampered["accounts"] = {}
        empty = PersistentStateStore(
            Path(self.directory.name, "tampered.sqlite"),
            chain_id=CHAIN_ID,
        )
        try:
            with self.assertRaisesRegex(StateStoreError, "digest mismatch"):
                empty.restore_checkpoint(
                    tampered,
                    trusted_checkpoint_digest=checkpoint["checkpoint_digest"],
                    trusted_block_hash=checkpoint["block_hash"],
                )
            self.assertEqual(empty.head_height, -1)
        finally:
            empty.close()

    def test_checkpoint_restore_requires_matching_trusted_anchors(self) -> None:
        checkpoint = self.store.export_checkpoint()
        wrong_digest = "0x" + ("f" * 64)
        wrong_hash = "0x" + ("e" * 64)

        digest_store = PersistentStateStore(
            Path(self.directory.name, "wrong-digest.sqlite"),
            chain_id=CHAIN_ID,
        )
        try:
            with self.assertRaisesRegex(StateStoreError, "trusted digest"):
                digest_store.restore_checkpoint(
                    checkpoint,
                    trusted_checkpoint_digest=wrong_digest,
                    trusted_block_hash=checkpoint["block_hash"],
                )
            self.assertEqual(digest_store.head_height, -1)
        finally:
            digest_store.close()

        hash_store = PersistentStateStore(
            Path(self.directory.name, "wrong-hash.sqlite"),
            chain_id=CHAIN_ID,
        )
        try:
            with self.assertRaisesRegex(StateStoreError, "trusted block hash"):
                hash_store.restore_checkpoint(
                    checkpoint,
                    trusted_checkpoint_digest=checkpoint["checkpoint_digest"],
                    trusted_block_hash=wrong_hash,
                )
            self.assertEqual(hash_store.head_height, -1)
        finally:
            hash_store.close()

    def test_integrity_check_rejects_metadata_and_noncanonical_payloads(self) -> None:
        self.store.connection.execute(
            "UPDATE metadata SET value='1' WHERE key='base_height'"
        )
        with self.assertRaisesRegex(StateStoreError, "base_height metadata"):
            self.store.integrity_check()
        self.store.connection.execute(
            "UPDATE metadata SET value='0' WHERE key='base_height'"
        )
        self.store.connection.execute(
            "UPDATE blocks SET accounts_json=? WHERE height=0",
            ('{"0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa":{"nonce":0,"balance":1000000000}}',),
        )
        with self.assertRaisesRegex(StateStoreError, "not canonical"):
            self.store.integrity_check()

    def test_database_chain_id_rebinding_is_rejected(self) -> None:
        path = Path(self.directory.name, "bound.sqlite")
        first = PersistentStateStore(path, chain_id=CHAIN_ID)
        first.close()
        with self.assertRaisesRegex(StateStoreError, "different chain_id"):
            PersistentStateStore(path, chain_id=1)

    @staticmethod
    def _checkpoint_digest(checkpoint: dict[str, object]) -> str:
        from jaios.social_ecosystem_chain.state_store import _checkpoint_digest

        body = {
            key: value
            for key, value in checkpoint.items()
            if key != "checkpoint_digest"
        }
        return _checkpoint_digest(body)


if __name__ == "__main__":
    unittest.main()
