from __future__ import annotations

import json
import unittest

from jaios.social_ecosystem_chain.state_transition import (
    StateMachine,
    StateTransaction,
    StateTransitionError,
    StateWrite,
)


GENESIS = "0x" + ("11" * 32)
SENDER_A = "0x" + ("22" * 20)
SENDER_B = "0x" + ("33" * 20)


def accept(_transaction: StateTransaction) -> bool:
    return True


class StateTransitionTests(unittest.TestCase):
    def _machine(self) -> StateMachine:
        return StateMachine(
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
        )

    def _transaction(
        self,
        *,
        sender: str = SENDER_A,
        nonce: int = 0,
        operations: tuple[StateWrite, ...] | None = None,
        max_resource_units: int = 100_000,
        chain_id: int = 20260723,
        genesis_hash: str = GENESIS,
    ) -> StateTransaction:
        return StateTransaction(
            chain_id=chain_id,
            genesis_hash=genesis_hash,
            protocol_version="1.0.0",
            sender=sender,
            nonce=nonce,
            max_resource_units=max_resource_units,
            operations=operations
            or (StateWrite("identity", "profiles/alice", None, b'{"name":"Alice"}'),),
        )

    def test_state_root_is_deterministic_for_equivalent_snapshots(self) -> None:
        first = StateMachine(
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
            state={
                "identity:profiles/alice": b"A",
                "permissions:roles/alice": b"member",
            },
            nonces={SENDER_A: 2, SENDER_B: 1},
        )
        second = StateMachine(
            chain_id=20260723,
            genesis_hash=GENESIS,
            protocol_version="1.0.0",
            state={
                "permissions:roles/alice": b"member",
                "identity:profiles/alice": b"A",
            },
            nonces={SENDER_B: 1, SENDER_A: 2},
        )
        self.assertEqual(first.state_root, second.state_root)

    def test_transaction_applies_atomically_and_advances_nonce(self) -> None:
        machine = self._machine()
        pre_root = machine.state_root
        receipt = machine.apply_transaction(
            self._transaction(),
            signature_verifier=accept,
        )
        self.assertEqual(machine.get("identity", "profiles/alice"), b'{"name":"Alice"}')
        self.assertEqual(machine.expected_nonce(SENDER_A), 1)
        self.assertEqual(receipt.pre_state_root, pre_root)
        self.assertEqual(receipt.post_state_root, machine.state_root)
        self.assertNotEqual(receipt.pre_state_root, receipt.post_state_root)

    def test_precondition_failure_rolls_back_all_writes_and_nonce(self) -> None:
        machine = self._machine()
        machine.apply_transaction(self._transaction(), signature_verifier=accept)
        original_root = machine.state_root
        operations = (
            StateWrite(
                "identity",
                "profiles/alice",
                "0x" + ("44" * 32),
                b"changed",
            ),
            StateWrite("permissions", "roles/alice", None, b"admin"),
        )
        with self.assertRaisesRegex(StateTransitionError, "precondition failed"):
            machine.apply_transaction(
                self._transaction(nonce=1, operations=operations),
                signature_verifier=accept,
            )
        self.assertEqual(machine.state_root, original_root)
        self.assertIsNone(machine.get("permissions", "roles/alice"))
        self.assertEqual(machine.expected_nonce(SENDER_A), 1)

    def test_signature_verifier_is_required_and_fails_closed(self) -> None:
        machine = self._machine()
        with self.assertRaisesRegex(StateTransitionError, "signature_verifier"):
            machine.apply_transaction(
                self._transaction(),
                signature_verifier=None,  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(StateTransitionError, "rejected"):
            machine.apply_transaction(
                self._transaction(),
                signature_verifier=lambda _tx: False,
            )
        with self.assertRaisesRegex(StateTransitionError, "failed closed"):
            machine.apply_transaction(
                self._transaction(),
                signature_verifier=lambda _tx: (_ for _ in ()).throw(RuntimeError()),
            )
        self.assertEqual(machine.expected_nonce(SENDER_A), 0)

    def test_replay_and_cross_domain_transactions_are_rejected(self) -> None:
        machine = self._machine()
        transaction = self._transaction()
        machine.apply_transaction(transaction, signature_verifier=accept)
        with self.assertRaisesRegex(StateTransitionError, "replay|nonce"):
            machine.apply_transaction(transaction, signature_verifier=accept)
        with self.assertRaisesRegex(StateTransitionError, "chain_id mismatch"):
            self._machine().apply_transaction(
                self._transaction(chain_id=1),
                signature_verifier=accept,
            )
        with self.assertRaisesRegex(StateTransitionError, "genesis_hash mismatch"):
            self._machine().apply_transaction(
                self._transaction(genesis_hash="0x" + ("55" * 32)),
                signature_verifier=accept,
            )

    def test_resource_limit_rejection_is_atomic(self) -> None:
        machine = self._machine()
        transaction = self._transaction(max_resource_units=1)
        with self.assertRaisesRegex(StateTransitionError, "resource limit"):
            machine.apply_transaction(transaction, signature_verifier=accept)
        self.assertIsNone(machine.get("identity", "profiles/alice"))
        self.assertEqual(machine.expected_nonce(SENDER_A), 0)

    def test_block_failure_rolls_back_prior_transactions(self) -> None:
        machine = self._machine()
        root = machine.state_root
        first = self._transaction()
        second = self._transaction(
            sender=SENDER_B,
            operations=(
                StateWrite(
                    "identity",
                    "profiles/bob",
                    "0x" + ("66" * 32),
                    b"Bob",
                ),
            ),
        )
        with self.assertRaisesRegex(StateTransitionError, "precondition failed"):
            machine.apply_block(
                height=1,
                timestamp=1,
                parent_state_root=root,
                transactions=(first, second),
                signature_verifier=accept,
            )
        self.assertEqual(machine.state_root, root)
        self.assertEqual(machine.height, 0)
        self.assertEqual(machine.timestamp, 0)
        self.assertEqual(machine.expected_nonce(SENDER_A), 0)
        self.assertIsNone(machine.get("identity", "profiles/alice"))

    def test_successful_block_commits_receipts_and_height(self) -> None:
        machine = self._machine()
        root = machine.state_root
        receipt = machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=root,
            transactions=(
                self._transaction(),
                self._transaction(
                    sender=SENDER_B,
                    operations=(StateWrite("identity", "profiles/bob", None, b"Bob"),),
                ),
            ),
            signature_verifier=accept,
        )
        self.assertEqual(machine.height, 1)
        self.assertEqual(machine.timestamp, 100)
        self.assertEqual(len(receipt.transaction_hashes), 2)
        self.assertEqual(len(receipt.transaction_receipt_hashes), 2)
        self.assertEqual(receipt.state_root, machine.state_root)

    def test_snapshot_round_trip_and_tamper_rejection(self) -> None:
        machine = self._machine()
        machine.apply_block(
            height=1,
            timestamp=100,
            parent_state_root=machine.state_root,
            transactions=(self._transaction(),),
            signature_verifier=accept,
        )
        snapshot = machine.export_snapshot()
        restored = StateMachine.restore_snapshot(snapshot)
        self.assertEqual(restored.as_evidence(), machine.as_evidence())
        self.assertEqual(
            restored.get("identity", "profiles/alice"),
            b'{"name":"Alice"}',
        )
        tampered = json.loads(snapshot)
        tampered["payload"]["height"] = 2
        with self.assertRaisesRegex(StateTransitionError, "digest mismatch"):
            StateMachine.restore_snapshot(
                json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
            )

    def test_safety_evidence_does_not_activate_mainnet_assets_or_bridge(self) -> None:
        evidence = self._machine().as_evidence()
        self.assertEqual(
            evidence["activation_status"],
            "MAINNET_CANDIDATE_NOT_ACTIVATED",
        )
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
