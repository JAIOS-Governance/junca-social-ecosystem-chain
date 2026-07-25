from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import peer_sync as peer_sync_module
from jaios.social_ecosystem_chain.finality import FinalityStateMachine, FinalityVote, Validator
from jaios.social_ecosystem_chain.mempool import TransactionPool
from jaios.social_ecosystem_chain.node_pipeline import NodeExecutionPipeline
from jaios.social_ecosystem_chain.peer_sync import (
    PeerAdvertisement,
    PeerRegistry,
    PeerSyncError,
    RecoveryAction,
    RecoveryJournal,
    SynchronizedBlockImporter,
)
from jaios.social_ecosystem_chain.protocol_kernel import AccountState, ProtocolConfig, TransactionEnvelope
from jaios.social_ecosystem_chain.state_store import PersistentStateStore


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)
ALICE = "0x" + ("a" * 40)
BOB = "0x" + ("b" * 40)


class InjectedCrash(RuntimeError):
    pass


class PeerSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.config = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=42_000,
            target_gas=21_000,
            initial_base_fee=1_000,
        )
        self.store = PersistentStateStore(Path(self.directory.name, "state.sqlite"), chain_id=CHAIN_ID)
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
        self.registry = PeerRegistry(chain_id=CHAIN_ID, genesis_hash=GENESIS)
        self.registry.observe(self.advertisement("peer-b", 1, "2"))
        self.registry.observe(self.advertisement("peer-a", 1, "2"))
        self.journal = RecoveryJournal(Path(self.directory.name, "import.json"), chain_id=CHAIN_ID)
        self.validators = tuple(Validator(f"validator-{index}", 1) for index in range(1, 4))

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def advertisement(self, peer_id: str, height: int, hash_digit: str) -> PeerAdvertisement:
        return PeerAdvertisement(
            peer_id=peer_id,
            chain_id=CHAIN_ID,
            genesis_hash=GENESIS,
            finalized_height=height,
            finalized_hash="0x" + (hash_digit * 64),
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
            signature_verifier=self.verify,
        )
        return self.pipeline.execute_candidate()

    def advertise_ahead(self, peer_id: str = "peer-a") -> None:
        self.registry.observe(self.advertisement(peer_id, 2, "3"))

    def certificate(self, proposal):
        machine = FinalityStateMachine(chain_id=CHAIN_ID, validators=self.validators)
        for height, block_hash in ((0, GENESIS), (proposal.height, proposal.block_hash)):
            certificate = None
            for validator in self.validators:
                certificate = machine.add_vote(
                    FinalityVote(
                        chain_id=CHAIN_ID,
                        height=height,
                        round=0,
                        block_hash=block_hash,
                        validator_id=validator.validator_id,
                        signature=validator.validator_id.encode(),
                    ),
                    verifier=self.verify,
                )
        return certificate

    def test_identity_mismatches_are_rejected(self) -> None:
        with self.assertRaisesRegex(PeerSyncError, "chain_id"):
            self.registry.observe(
                PeerAdvertisement("bad", 1, GENESIS, 1, "0x" + ("2" * 64))
            )
        with self.assertRaisesRegex(PeerSyncError, "genesis"):
            self.registry.observe(
                PeerAdvertisement("bad", CHAIN_ID, "0x" + ("9" * 64), 1, "0x" + ("2" * 64))
            )

    def test_peer_regression_is_rejected(self) -> None:
        self.registry.observe(self.advertisement("peer-a", 2, "3"))
        with self.assertRaisesRegex(PeerSyncError, "regressed"):
            self.registry.observe(self.advertisement("peer-a", 1, "2"))

    def test_peer_finalized_equivocation_is_rejected_without_replacement(self) -> None:
        original = self.registry.observe(self.advertisement("peer-a", 2, "3"))
        with self.assertRaisesRegex(PeerSyncError, "conflicting finalized hash"):
            self.registry.observe(self.advertisement("peer-a", 2, "4"))
        selected = self.registry.select_source(local_height=0)
        self.assertEqual(
            selected.advertisement.finalized_hash,
            original.advertisement.finalized_hash,
        )

    def test_peer_identity_rejects_boolean_protocol_values(self) -> None:
        with self.assertRaises(PeerSyncError):
            PeerAdvertisement("bad", True, GENESIS, 1, "0x" + ("2" * 64))
        with self.assertRaises(PeerSyncError):
            PeerAdvertisement("bad", CHAIN_ID, GENESIS, True, "0x" + ("2" * 64))
        with self.assertRaises(PeerSyncError):
            PeerAdvertisement(
                "bad",
                CHAIN_ID,
                GENESIS,
                1,
                "0x" + ("2" * 64),
                protocol_version=True,
            )

    def test_selection_is_deterministic(self) -> None:
        self.assertEqual(self.registry.select_source(local_height=0).advertisement.peer_id, "peer-a")
        self.registry.observe(self.advertisement("peer-b", 2, "3"))
        self.assertEqual(self.registry.select_source(local_height=0).advertisement.peer_id, "peer-b")

    def test_three_faults_quarantine_peer(self) -> None:
        for _ in range(3):
            record = self.registry.record_fault("peer-a")
        self.assertFalse(record.eligible)
        self.assertEqual(self.registry.select_source(local_height=0).advertisement.peer_id, "peer-b")

    def test_finalized_import_commits_and_clears_journal(self) -> None:
        proposal = self.proposal()
        self.advertise_ahead()
        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
        )
        stored = importer.import_finalized(
            peer_id="peer-a",
            proposal=proposal,
            certificate=self.certificate(proposal),
        )
        self.assertEqual(stored.height, 1)
        self.assertEqual(self.store.accounts_at()[BOB].balance, 100)
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.CLEAN)

    def test_non_selected_source_is_rejected(self) -> None:
        proposal = self.proposal()
        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
        )
        with self.assertRaisesRegex(PeerSyncError, "selected"):
            importer.import_finalized(
                peer_id="peer-b",
                proposal=proposal,
                certificate=self.certificate(proposal),
            )

    def test_import_must_match_advertised_finalized_hash(self) -> None:
        proposal = self.proposal()
        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
        )
        with self.assertRaisesRegex(PeerSyncError, "finalized advertisement"):
            importer.import_finalized(
                peer_id="peer-a",
                proposal=proposal,
                certificate=self.certificate(proposal),
            )
        self.assertEqual(self.registry._require("peer-a").fault_score, 1)
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.CLEAN)

    def test_crash_after_prepare_requires_retry(self) -> None:
        proposal = self.proposal()
        self.advertise_ahead()

        def crash(stage: str) -> None:
            if stage == "after_journal_prepare":
                raise InjectedCrash(stage)

        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
            fault_injector=crash,
        )
        with self.assertRaises(InjectedCrash):
            importer.import_finalized(
                peer_id="peer-a",
                proposal=proposal,
                certificate=self.certificate(proposal),
            )
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.RETRY_REQUIRED)

    def test_crash_after_state_commit_is_reconciled(self) -> None:
        proposal = self.proposal()
        self.advertise_ahead()

        def crash(stage: str) -> None:
            if stage == "after_state_commit":
                raise InjectedCrash(stage)

        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
            fault_injector=crash,
        )
        with self.assertRaises(InjectedCrash):
            importer.import_finalized(
                peer_id="peer-a",
                proposal=proposal,
                certificate=self.certificate(proposal),
            )
        self.assertEqual(self.store.head_height, 1)
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.COMMIT_CONFIRMED)
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.CLEAN)

    def test_journal_tamper_is_fail_closed(self) -> None:
        proposal = self.proposal()
        self.journal.begin(peer_id="peer-a", proposal=proposal)
        record = self.journal.path.read_text(encoding="utf-8").replace("PREPARED", "CORRUPTED")
        self.journal.path.write_text(record, encoding="utf-8")
        with self.assertRaisesRegex(PeerSyncError, "integrity"):
            self.journal.read()

    def test_invalid_finality_clears_prepared_journal_for_safe_fallback(self) -> None:
        proposal = self.proposal()
        self.advertise_ahead()
        certificate = replace(
            self.certificate(proposal),
            signed_power=1,
            total_power=3,
        )
        importer = SynchronizedBlockImporter(
            registry=self.registry,
            pipeline=self.pipeline,
            journal=self.journal,
        )
        with self.assertRaisesRegex(ValueError, "quorum"):
            importer.import_finalized(
                peer_id="peer-a",
                proposal=proposal,
                certificate=certificate,
            )
        self.assertEqual(self.store.head_height, 0)
        self.assertEqual(self.journal.recover(self.store), RecoveryAction.CLEAN)
        self.assertEqual(self.registry._require("peer-a").fault_score, 1)

    def test_journal_rejects_recomputed_invalid_values(self) -> None:
        proposal = self.proposal()
        self.journal.begin(peer_id="peer-a", proposal=proposal)
        record = json.loads(self.journal.path.read_text(encoding="utf-8"))
        record["status"] = "UNKNOWN"
        body = dict(record)
        body.pop("record_digest")
        record["record_digest"] = peer_sync_module._digest(body)
        self.journal.path.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PeerSyncError, "values"):
            self.journal.read()

    def test_peer_evidence_preserves_public_boundaries(self) -> None:
        evidence = self.registry.evidence()
        self.assertEqual(evidence["eligible_peer_count"], 2)
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
