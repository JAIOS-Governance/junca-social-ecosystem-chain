from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from jaios.social_ecosystem_chain.mempool import MempoolError, MempoolPolicy, TransactionPool
from jaios.social_ecosystem_chain.protocol_kernel import (
    AccountState,
    ProtocolConfig,
    TransactionEnvelope,
    transaction_encoded_size,
)


CHAIN_ID = 20260723
ALICE = "0x" + ("a" * 40)
BOB = "0x" + ("b" * 40)
CAROL = "0x" + ("c" * 40)


def tx(sender: str = ALICE, nonce: int = 0, tip: int = 100, **overrides: object):
    values: dict[str, object] = {
        "chain_id": CHAIN_ID,
        "sender": sender,
        "recipient": BOB,
        "nonce": nonce,
        "value": 1,
        "gas_limit": 21_000,
        "max_fee_per_gas": 2_000,
        "max_priority_fee_per_gas": tip,
        "signature": f"{sender}:{nonce}:{tip}".encode(),
    }
    values.update(overrides)
    return TransactionEnvelope(**values)  # type: ignore[arg-type]


class TransactionPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=63_000,
            target_gas=31_500,
            initial_base_fee=1_000,
        )
        self.pool = TransactionPool(
            self.config,
            MempoolPolicy(
                max_transactions=10,
                max_per_sender=4,
                max_nonce_gap=3,
                replacement_bump_percent=10,
            ),
        )
        self.accounts = {
            ALICE: AccountState(balance=1_000_000_000),
            CAROL: AccountState(balance=1_000_000_000),
        }
        self.verify = lambda transaction: bool(transaction.signature)

    def admit(self, transaction: TransactionEnvelope):
        return self.pool.admit(
            transaction,
            account=self.accounts[transaction.sender],
            current_base_fee=1_000,
            signature_verifier=self.verify,
        )

    def test_admission_and_duplicate_hash_are_fail_closed(self) -> None:
        transaction = tx()
        result = self.admit(transaction)
        self.assertEqual(result.status, "ADMITTED")
        with self.assertRaisesRegex(MempoolError, "duplicate"):
            self.admit(transaction)

    def test_replacement_requires_fee_cap_and_tip_bump(self) -> None:
        self.admit(tx(tip=100))
        with self.assertRaisesRegex(MempoolError, "bump"):
            self.admit(tx(tip=109, max_fee_per_gas=2_200))
        result = self.admit(tx(tip=110, max_fee_per_gas=2_200))
        self.assertEqual(result.status, "REPLACED")
        self.assertEqual(len(self.pool), 1)

    def test_consumed_nonce_gap_chain_and_signature_are_rejected(self) -> None:
        self.accounts[ALICE] = AccountState(balance=1_000_000_000, nonce=1)
        with self.assertRaisesRegex(MempoolError, "already consumed"):
            self.admit(tx(nonce=0))
        with self.assertRaisesRegex(MempoolError, "gap"):
            self.admit(tx(nonce=5))
        with self.assertRaisesRegex(MempoolError, "chain_id"):
            self.admit(tx(nonce=1, chain_id=1))
        with self.assertRaisesRegex(MempoolError, "signature"):
            self.pool.admit(
                tx(nonce=1),
                account=self.accounts[ALICE],
                current_base_fee=1_000,
                signature_verifier=lambda transaction: False,
            )

    def test_worst_case_debit_is_required(self) -> None:
        poor = AccountState(balance=21_000 * 2_000)
        with self.assertRaisesRegex(MempoolError, "worst-case"):
            self.pool.admit(
                tx(value=1),
                account=poor,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

    def test_candidate_prioritizes_reward_and_preserves_sender_nonce(self) -> None:
        self.admit(tx(ALICE, nonce=0, tip=100))
        self.admit(tx(ALICE, nonce=1, tip=900))
        self.admit(tx(CAROL, nonce=0, tip=500))
        candidate = self.pool.build_candidate(self.accounts, current_base_fee=1_000)
        hashes = [transaction.transaction_hash for transaction in candidate.transactions]
        self.assertEqual(hashes[0], tx(CAROL, nonce=0, tip=500).transaction_hash)
        self.assertEqual(hashes[1], tx(ALICE, nonce=0, tip=100).transaction_hash)
        self.assertEqual(hashes[2], tx(ALICE, nonce=1, tip=900).transaction_hash)
        self.assertEqual(candidate.gas_used, 63_000)

    def test_candidate_digest_is_insertion_order_independent(self) -> None:
        transactions = [tx(ALICE, 0, 100), tx(CAROL, 0, 500)]
        for transaction in transactions:
            self.admit(transaction)
        first = self.pool.build_candidate(self.accounts, current_base_fee=1_000)
        other = TransactionPool(self.config, self.pool._policy)
        for transaction in reversed(transactions):
            other.admit(
                transaction,
                account=self.accounts[transaction.sender],
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )
        second = other.build_candidate(self.accounts, current_base_fee=1_000)
        self.assertEqual(first.candidate_digest, second.candidate_digest)

    def test_candidate_accounts_for_calldata_intrinsic_gas(self) -> None:
        payload = b"\x00\x01"
        required = 21_000 + 4 + 16
        calldata = tx(ALICE, 0, 500, data=payload, gas_limit=required)
        plain = tx(CAROL, 0, 100)
        self.admit(calldata)
        self.admit(plain)

        candidate = self.pool.build_candidate(
            self.accounts,
            current_base_fee=1_000,
            gas_limit=required,
        )
        self.assertEqual(candidate.transactions, (calldata,))
        self.assertEqual(candidate.gas_used, required)

    def test_admission_rejects_underfunded_calldata_gas(self) -> None:
        with self.assertRaisesRegex(MempoolError, "gas limit"):
            self.admit(tx(data=b"payload", gas_limit=21_000))

    def test_candidate_enforces_encoded_block_byte_cap(self) -> None:
        first = tx(ALICE, 0, 500, signature=b"a" * 1_024)
        second = tx(CAROL, 0, 100, signature=b"b" * 1_024)
        first_size = transaction_encoded_size(self.config, first)
        second_size = transaction_encoded_size(self.config, second)
        bounded_config = replace(
            self.config,
            max_signature_bytes=1_024,
            max_transaction_encoded_bytes=max(first_size, second_size),
            max_block_encoded_bytes=first_size + second_size - 1,
        )
        bounded = TransactionPool(bounded_config, self.pool._policy)
        for item in (first, second):
            bounded.admit(
                item,
                account=self.accounts[item.sender],
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

        candidate = bounded.build_candidate(self.accounts, current_base_fee=1_000)
        self.assertEqual(candidate.transactions, (first,))
        self.assertEqual(candidate.encoded_bytes, first_size)

    def test_admission_rejects_oversized_signature(self) -> None:
        with self.assertRaisesRegex(MempoolError, "signature exceeds"):
            self.admit(tx(signature=b"x" * (self.config.max_signature_bytes + 1)))

    def test_prune_and_remove_included_are_deterministic(self) -> None:
        old = tx(ALICE, nonce=0)
        future = tx(ALICE, nonce=3)
        self.admit(old)
        self.admit(future)
        removed = self.pool.prune(
            {ALICE: AccountState(balance=1_000_000_000, nonce=1)},
            current_base_fee=1_000,
        )
        self.assertEqual(removed, (old.transaction_hash,))
        self.pool.remove_included((future,))
        self.assertEqual(len(self.pool), 0)

    def test_capacity_and_candidate_gas_bounds_are_enforced(self) -> None:
        constrained = TransactionPool(
            self.config,
            MempoolPolicy(max_transactions=1, max_per_sender=1, max_nonce_gap=1),
        )
        constrained.admit(
            tx(),
            account=self.accounts[ALICE],
            current_base_fee=1_000,
            signature_verifier=self.verify,
        )
        with self.assertRaisesRegex(MempoolError, "capacity"):
            constrained.admit(
                tx(CAROL),
                account=self.accounts[CAROL],
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )
        with self.assertRaisesRegex(MempoolError, "gas limit"):
            constrained.build_candidate(self.accounts, current_base_fee=1_000, gas_limit=64_000)

    def test_snapshot_round_trip_preserves_deterministic_candidate(self) -> None:
        self.admit(tx(ALICE, nonce=0, tip=100))
        restart_data = b"restart-safe"
        restart_gas = 21_000 + len(restart_data) * 16
        self.admit(
            tx(
                CAROL,
                nonce=0,
                tip=500,
                data=restart_data,
                gas_limit=restart_gas,
            )
        )
        expected = self.pool.build_candidate(self.accounts, current_base_fee=1_000)
        snapshot = self.pool.export_snapshot()

        restored = TransactionPool(self.config, self.pool._policy)
        hashes = restored.restore_snapshot(
            snapshot,
            accounts=self.accounts,
            current_base_fee=1_000,
            signature_verifier=self.verify,
        )

        self.assertEqual(len(restored), 2)
        self.assertEqual(hashes, tuple(item["transaction_hash"] for item in snapshot["transactions"]))
        actual = restored.build_candidate(self.accounts, current_base_fee=1_000)
        self.assertEqual(actual.candidate_digest, expected.candidate_digest)
        self.assertEqual(actual.transactions, expected.transactions)

    def test_snapshot_restore_is_atomic_and_fail_closed(self) -> None:
        self.admit(tx(ALICE, nonce=0))
        snapshot = self.pool.export_snapshot()

        tampered = deepcopy(snapshot)
        tampered["transactions"][0]["value"] = 999
        restored = TransactionPool(self.config, self.pool._policy)
        with self.assertRaisesRegex(MempoolError, "digest mismatch"):
            restored.restore_snapshot(
                tampered,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )
        self.assertEqual(len(restored), 0)

        invalid_signature = deepcopy(snapshot)
        with self.assertRaisesRegex(MempoolError, "signature"):
            restored.restore_snapshot(
                invalid_signature,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=lambda transaction: False,
            )
        self.assertEqual(len(restored), 0)

    def test_snapshot_rejects_chain_policy_hash_and_nonempty_pool_mismatch(self) -> None:
        self.admit(tx(ALICE, nonce=0))
        snapshot = self.pool.export_snapshot()

        wrong_chain = deepcopy(snapshot)
        wrong_chain["chain_id"] = 1
        wrong_chain["snapshot_digest"] = snapshot["snapshot_digest"]
        empty = TransactionPool(self.config, self.pool._policy)
        with self.assertRaisesRegex(MempoolError, "chain_id mismatch"):
            empty.restore_snapshot(
                wrong_chain,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

        different_policy = TransactionPool(self.config)
        with self.assertRaisesRegex(MempoolError, "policy mismatch"):
            different_policy.restore_snapshot(
                snapshot,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

        with self.assertRaisesRegex(MempoolError, "empty mempool"):
            self.pool.restore_snapshot(
                snapshot,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

        wrong_hash = deepcopy(snapshot)
        wrong_hash["transactions"][0]["transaction_hash"] = "0x" + ("0" * 64)
        wrong_hash["snapshot_digest"] = self._digest_snapshot(wrong_hash)
        with self.assertRaisesRegex(MempoolError, "transaction hash mismatch"):
            empty.restore_snapshot(
                wrong_hash,
                accounts=self.accounts,
                current_base_fee=1_000,
                signature_verifier=self.verify,
            )

    @staticmethod
    def _digest_snapshot(snapshot: dict[str, object]) -> str:
        from jaios.social_ecosystem_chain.mempool import _snapshot_digest

        body = {key: value for key, value in snapshot.items() if key != "snapshot_digest"}
        return _snapshot_digest(body)


if __name__ == "__main__":
    unittest.main()
