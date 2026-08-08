from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.mainnet_mempool import (
    MainnetMempoolError,
    MainnetTransactionPool,
    MempoolAdmissionPolicy,
    MempoolTransaction,
)


GENESIS = "0x" + ("11" * 32)
PAYLOAD_A = "0x" + ("22" * 32)
PAYLOAD_B = "0x" + ("33" * 32)
ALICE = "0x" + ("aa" * 20)
BOB = "0x" + ("bb" * 20)


class MainnetMempoolTests(unittest.TestCase):
    def _pool(self, **policy_values) -> MainnetTransactionPool:
        policy = MempoolAdmissionPolicy(**policy_values)
        return MainnetTransactionPool(
            chain_id=20260723,
            genesis_hash=GENESIS,
            policy=policy,
        )

    def _transaction(self, **overrides) -> MempoolTransaction:
        values = {
            "chain_id": 20260723,
            "genesis_hash": GENESIS,
            "sender": ALICE,
            "nonce": 0,
            "gas_limit": 21_000,
            "max_fee_per_gas": 100,
            "max_priority_fee_per_gas": 10,
            "payload_hash": PAYLOAD_A,
            "encoded_size": 256,
            "signature": b"signature",
        }
        values.update(overrides)
        return MempoolTransaction(**values)

    def test_admission_binds_chain_genesis_nonce_and_signature(self) -> None:
        pool = self._pool()
        transaction = self._transaction()

        accepted = pool.add(
            transaction,
            committed_nonce=0,
            verifier=lambda _: True,
        )
        self.assertEqual(accepted, transaction.transaction_hash)

        with self.assertRaisesRegex(MainnetMempoolError, "duplicate"):
            pool.add(transaction, committed_nonce=0, verifier=lambda _: True)
        with self.assertRaisesRegex(MainnetMempoolError, "domain"):
            pool.add(
                self._transaction(chain_id=20260724, signature=b"other"),
                committed_nonce=0,
                verifier=lambda _: True,
            )
        with self.assertRaisesRegex(MainnetMempoolError, "verification failed"):
            pool.add(
                self._transaction(nonce=1, signature=b"invalid"),
                committed_nonce=0,
                verifier=lambda _: False,
            )

    def test_replacement_requires_fee_bump(self) -> None:
        pool = self._pool(minimum_replacement_bump_percent=10)
        pool.add(self._transaction(), committed_nonce=0, verifier=lambda _: True)

        with self.assertRaisesRegex(MainnetMempoolError, "bump"):
            pool.add(
                self._transaction(
                    max_fee_per_gas=109,
                    max_priority_fee_per_gas=11,
                    payload_hash=PAYLOAD_B,
                    signature=b"replacement-low",
                ),
                committed_nonce=0,
                verifier=lambda _: True,
            )
        replacement = self._transaction(
            max_fee_per_gas=110,
            max_priority_fee_per_gas=11,
            payload_hash=PAYLOAD_B,
            signature=b"replacement-ok",
        )
        pool.add(replacement, committed_nonce=0, verifier=lambda _: True)

        candidate = pool.build_candidate(
            committed_nonces={ALICE: 0},
            gas_limit=21_000,
            maximum_transactions=1,
        )
        self.assertEqual(candidate, (replacement,))

    def test_candidate_preserves_sender_nonce_order(self) -> None:
        pool = self._pool()
        nonce_one = self._transaction(
            nonce=1,
            max_priority_fee_per_gas=100,
            signature=b"nonce-one",
        )
        nonce_zero = self._transaction(
            nonce=0,
            max_priority_fee_per_gas=10,
            signature=b"nonce-zero",
        )
        bob = self._transaction(
            sender=BOB,
            nonce=0,
            max_priority_fee_per_gas=50,
            signature=b"bob",
        )
        for transaction in (nonce_one, nonce_zero, bob):
            pool.add(transaction, committed_nonce=0, verifier=lambda _: True)

        candidate = pool.build_candidate(
            committed_nonces={ALICE: 0, BOB: 0},
            gas_limit=63_000,
            maximum_transactions=3,
        )
        alice_nonces = [item.nonce for item in candidate if item.sender.lower() == ALICE]
        self.assertEqual(alice_nonces, [0, 1])

    def test_sender_quota_and_nonce_gap_fail_closed(self) -> None:
        pool = self._pool(
            maximum_transactions=2,
            maximum_per_sender=1,
            maximum_nonce_gap=1,
        )
        pool.add(self._transaction(), committed_nonce=0, verifier=lambda _: True)

        with self.assertRaisesRegex(MainnetMempoolError, "sender mempool quota"):
            pool.add(
                self._transaction(nonce=1, signature=b"second"),
                committed_nonce=0,
                verifier=lambda _: True,
            )
        with self.assertRaisesRegex(MainnetMempoolError, "nonce"):
            self._pool(maximum_nonce_gap=1).add(
                self._transaction(nonce=2),
                committed_nonce=0,
                verifier=lambda _: True,
            )

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = self._pool().as_evidence()

        self.assertTrue(evidence["bounded"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
