from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.finality import (
    FinalityStateMachine,
    FinalityVote,
    Validator,
)
from jaios.social_ecosystem_chain.mempool import TransactionPool
from jaios.social_ecosystem_chain.node_pipeline import NodeExecutionPipeline
from jaios.social_ecosystem_chain.peer_sync import (
    PeerAdvertisement,
    PeerSyncError,
    RecoveryAction,
)
from jaios.social_ecosystem_chain.protocol_kernel import (
    AccountState,
    ProtocolConfig,
    TransactionEnvelope,
)
from jaios.social_ecosystem_chain.state_store import PersistentStateStore
from jaios.social_ecosystem_chain.validator_node import (
    AuthenticatedVote,
    ValidatorNodeError,
    ValidatorSyncRecovery,
)


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)
ALICE = "0x" + ("a" * 40)
BOB = "0x" + ("b" * 40)


class ValidatorSyncRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=42_000,
            target_gas=21_000,
            initial_base_fee=1_000,
        )
        self.store = PersistentStateStore(
            Path(self.directory.name, "state.sqlite"), chain_id=CHAIN_ID
        )
        self.addCleanup(self.store.close)
        self.store.initialize_genesis(
            block_hash=GENESIS,
            accounts={ALICE: AccountState(balance=1_000_000_000)},
            base_fee_per_gas=1_000,
        )
        self.pool = TransactionPool(self.config)
        self.pipeline = NodeExecutionPipeline(
            config=self.config,
            pool=self.pool,
            store=self.store,
            signature_verifier=lambda transaction: bool(transaction.signature),
        )
        self.resources = {
            f"validator-{index}": (
                f"arn:aws:kms:us-east-1:595710543956:key/validator-{index}"
            )
            for index in range(1, 4)
        }

    @staticmethod
    def signature(context: str, payload: bytes) -> bytes:
        return hashlib.sha256(context.encode() + payload).digest() * 2

    def consensus_verify(self, validator_id, resource, payload, signature):
        return signature == self.signature(resource, payload)

    def peer_verify(self, validator_id, payload, signature):
        return signature == self.signature("peer:" + validator_id, payload)

    def coordinator(self) -> ValidatorSyncRecovery:
        return ValidatorSyncRecovery(
            store=self.store,
            data_dir=self.directory.name,
            genesis_hash=GENESIS,
            signer_resources=self.resources,
            consensus_verifier=self.consensus_verify,
            peer_verifier=self.peer_verify,
            pipeline=self.pipeline,
        )

    def proposal(self):
        transaction = TransactionEnvelope(
            chain_id=CHAIN_ID,
            sender=ALICE,
            recipient=BOB,
            nonce=0,
            value=100,
            gas_limit=21_000,
            max_fee_per_gas=2_000,
            max_priority_fee_per_gas=100,
            signature=b"transaction",
        )
        self.pool.admit(
            transaction,
            account=self.store.accounts_at()[ALICE],
            current_base_fee=self.store.head().base_fee_per_gas,
            signature_verifier=lambda item: bool(item.signature),
        )
        return self.pipeline.execute_candidate()

    def finality(self, proposal):
        machine = FinalityStateMachine(
            chain_id=CHAIN_ID,
            validators=tuple(Validator(item, 1) for item in sorted(self.resources)),
            initial_finalized_height=proposal.height - 1,
        )
        packets = []
        certificate = None
        for validator_id in sorted(self.resources):
            unsigned = FinalityVote(
                chain_id=CHAIN_ID,
                height=proposal.height,
                round=0,
                block_hash=proposal.block_hash,
                validator_id=validator_id,
                signature=b"",
            )
            vote = FinalityVote(
                **{
                    **unsigned.__dict__,
                    "signature": self.signature(
                        self.resources[validator_id], unsigned.signing_payload
                    ),
                }
            )
            packet = AuthenticatedVote(
                **vote.__dict__,
                peer_signature=b"pending",
            )
            packet = AuthenticatedVote(
                **{
                    **packet.__dict__,
                    "peer_signature": self.signature(
                        "peer:" + validator_id, packet.peer_signing_payload
                    ),
                }
            )
            packets.append(packet)
            certificate = machine.add_vote(vote, verifier=lambda _: True)
        return certificate, packets

    def advertise(self, coordinator, proposal, peer_id="validator-2"):
        coordinator.observe(
            PeerAdvertisement(
                peer_id=peer_id,
                chain_id=CHAIN_ID,
                genesis_hash=GENESIS,
                finalized_height=proposal.height,
                finalized_hash=proposal.block_hash,
            )
        )

    def test_authenticated_finalized_catch_up_commits(self):
        proposal = self.proposal()
        certificate, packets = self.finality(proposal)
        coordinator = self.coordinator()
        self.advertise(coordinator, proposal)
        coordinator.import_authenticated_finalized(
            peer_id="validator-2",
            proposal=proposal,
            certificate=certificate,
            votes=packets,
        )
        self.assertEqual(self.store.head_height, 1)
        self.assertEqual(coordinator.recovery_action, RecoveryAction.CLEAN)
        self.assertTrue(coordinator.evidence()["authenticated_finalized_only"])

    def test_forged_peer_authentication_is_rejected_without_commit(self):
        proposal = self.proposal()
        certificate, packets = self.finality(proposal)
        packets[1] = AuthenticatedVote(
            **{**packets[1].__dict__, "peer_signature": b"forged"}
        )
        coordinator = self.coordinator()
        self.advertise(coordinator, proposal)
        with self.assertRaisesRegex(ValidatorNodeError, "authentication"):
            coordinator.import_authenticated_finalized(
                peer_id="validator-2",
                proposal=proposal,
                certificate=certificate,
                votes=packets,
            )
        self.assertEqual(self.store.head_height, 0)

    def test_fork_advertisement_fails_closed(self):
        proposal = self.proposal()
        coordinator = self.coordinator()
        self.advertise(coordinator, proposal)
        with self.assertRaisesRegex(PeerSyncError, "conflicting finalized hash"):
            coordinator.observe(
                PeerAdvertisement(
                    peer_id="validator-2",
                    chain_id=CHAIN_ID,
                    genesis_hash=GENESIS,
                    finalized_height=proposal.height,
                    finalized_hash="0x" + ("f" * 64),
                )
            )
        self.assertEqual(self.store.head_height, 0)

    def test_restart_retries_only_identical_prepared_state(self):
        proposal = self.proposal()
        certificate, packets = self.finality(proposal)
        first = self.coordinator()
        self.advertise(first, proposal)
        first.journal.begin(peer_id="validator-2", proposal=proposal)

        restarted = self.coordinator()
        self.assertEqual(restarted.recovery_action, RecoveryAction.RETRY_REQUIRED)
        self.advertise(restarted, proposal)
        restarted.import_authenticated_finalized(
            peer_id="validator-2",
            proposal=proposal,
            certificate=certificate,
            votes=packets,
        )
        self.assertEqual(self.store.head_height, 1)
        self.assertEqual(restarted.recovery_action, RecoveryAction.CLEAN)

    def test_restart_divergence_preserves_journal_and_fails_closed(self):
        proposal = self.proposal()
        certificate, packets = self.finality(proposal)
        first = self.coordinator()
        self.advertise(first, proposal)
        first.journal.begin(peer_id="validator-2", proposal=proposal)

        restarted = self.coordinator()
        self.advertise(restarted, proposal)
        with self.assertRaisesRegex(PeerSyncError, "diverges"):
            restarted.import_authenticated_finalized(
                peer_id="validator-3",
                proposal=proposal,
                certificate=certificate,
                votes=packets,
            )
        self.assertIsNotNone(restarted.journal.read())
        self.assertEqual(self.store.head_height, 0)


if __name__ == "__main__":
    unittest.main()
