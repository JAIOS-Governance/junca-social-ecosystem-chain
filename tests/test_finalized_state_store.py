from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jaios.social_ecosystem_chain.finalized_state_store import (
    FinalizedStateStore,
    FinalizedStateStoreError,
)
from jaios.social_ecosystem_chain.state_transition import (
    StateMachine,
    StateTransaction,
    StateWrite,
)


GENESIS = "0x" + ("11" * 32)
SENDER = "0x" + ("22" * 20)


def accept(_transaction: StateTransaction) -> bool:
    return True


class FinalizedStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "state.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _machine(self) -> StateMachine:
        return StateMachine(
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
        )

    def _store(self) -> FinalizedStateStore:
        return FinalizedStateStore(
            self.path,
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
        )

    def _tx(self, nonce: int, key: str, value: bytes) -> StateTransaction:
        return StateTransaction(
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
            sender=SENDER,
            nonce=nonce,
            max_resource_units=100_000,
            operations=(StateWrite("identity", key, None, value),),
        )

    def test_persist_and_restore_contiguous_finalized_state(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        store.persist_finalized(machine, receipt)

        restored = store.load_latest()
        self.assertEqual(restored.height, 1)
        self.assertEqual(restored.timestamp, 100)
        self.assertEqual(restored.state_root, machine.state_root)
        self.assertEqual(restored.get("identity", "profiles/alice"), b"Alice")
        self.assertEqual(restored.expected_nonce(SENDER), 1)

        evidence = store.head_evidence()
        self.assertEqual(evidence["snapshot_count"], 2)
        self.assertEqual(evidence["height"], 1)
        self.assertEqual(evidence["journal_mode"], "wal")
        self.assertEqual(evidence["integrity_check"], "ok")

    def test_exact_duplicate_is_idempotent_and_conflict_is_rejected(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)
        store.initialize_genesis(machine)

        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        store.persist_finalized(machine, receipt)
        store.persist_finalized(machine, receipt)

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE finalized_snapshots SET state_root = ? WHERE height = 1",
                ("0x" + ("44" * 32),),
            )
            connection.commit()

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "conflicting finalized snapshot",
        ):
            store.persist_finalized(machine, receipt)

    def test_gap_and_parent_mismatch_are_rejected(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        forged_gap = type(receipt)(
            height=2,
            timestamp=receipt.timestamp,
            parent_state_root=receipt.parent_state_root,
            state_root=receipt.state_root,
            transaction_hashes=receipt.transaction_hashes,
            transaction_receipt_hashes=receipt.transaction_receipt_hashes,
            resource_units_used=receipt.resource_units_used,
        )
        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "receipt height does not match",
        ):
            store.persist_finalized(machine, forged_gap)

        store.persist_finalized(machine, receipt)
        second = machine.apply_block(
            height=2,
            timestamp=200,
            parent_state_root=machine.state_root,
            transactions=(self._tx(1, "profiles/bob", b"Bob"),),
            signature_verifier=accept,
        )
        forged_parent = type(second)(
            height=second.height,
            timestamp=second.timestamp,
            parent_state_root="0x" + ("55" * 32),
            state_root=second.state_root,
            transaction_hashes=second.transaction_hashes,
            transaction_receipt_hashes=second.transaction_receipt_hashes,
            resource_units_used=second.resource_units_used,
        )
        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "parent state root",
        ):
            store.persist_finalized(machine, forged_parent)

    def test_store_binding_mismatch_fails_closed(self) -> None:
        self._store()

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "metadata binding mismatch",
        ):
            FinalizedStateStore(
                self.path,
                chain_id=20260724,
                genesis_hash=GENESIS,
                protocol_version="1.0.0",
            )

    def test_snapshot_tampering_is_detected_on_restore(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT snapshot FROM finalized_snapshots WHERE height = 0"
            ).fetchone()
            envelope = json.loads(row[0])
            envelope["payload"]["height"] = 9
            tampered = json.dumps(
                envelope,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            connection.execute(
                "UPDATE finalized_snapshots SET snapshot = ? WHERE height = 0",
                (tampered,),
            )
            connection.commit()

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "byte hash mismatch",
        ):
            store.load_latest()

    def test_failed_persist_does_not_advance_persisted_head(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        forged = type(receipt)(
            height=receipt.height,
            timestamp=receipt.timestamp,
            parent_state_root="0x" + ("66" * 32),
            state_root=receipt.state_root,
            transaction_hashes=receipt.transaction_hashes,
            transaction_receipt_hashes=receipt.transaction_receipt_hashes,
            resource_units_used=receipt.resource_units_used,
        )

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "parent state root",
        ):
            store.persist_finalized(machine, forged)

        self.assertEqual(store.head_evidence()["height"], 0)

    def test_missing_intermediate_height_is_rejected(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        second = machine.apply_block(
            height=2,
            timestamp=200,
            parent_state_root=machine.state_root,
            transactions=(self._tx(1, "profiles/bob", b"Bob"),),
            signature_verifier=accept,
        )

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "height must be contiguous",
        ):
            store.persist_finalized(machine, second)

    def test_snapshot_digest_row_tampering_is_detected(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE finalized_snapshots SET snapshot_digest = ? WHERE height = 0",
                ("0x" + ("77" * 32),),
            )
            connection.commit()

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "snapshot digest binding mismatch",
        ):
            store.load_latest()

    def test_block_receipt_tampering_is_detected(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)
        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._tx(0, "profiles/alice", b"Alice"),),
            signature_verifier=accept,
        )
        store.persist_finalized(machine, receipt)

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE finalized_snapshots SET block_receipt_hash = ? WHERE height = 1",
                ("0x" + ("88" * 32),),
            )
            connection.commit()

        with self.assertRaisesRegex(
            FinalizedStateStoreError,
            "block receipt hash mismatch",
        ):
            store.load_latest()

    def test_safety_boundary_is_preserved(self) -> None:
        store = self._store()
        machine = self._machine()
        store.initialize_genesis(machine)
        evidence = store.head_evidence()

        self.assertEqual(
            evidence["activation_status"],
            "MAINNET_CANDIDATE_NOT_ACTIVATED",
        )
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
