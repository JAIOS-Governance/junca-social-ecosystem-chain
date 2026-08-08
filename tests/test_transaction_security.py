from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.transaction_security import (
    ReplayProtectedTransaction,
    TransactionDomain,
    TransactionReplayGuard,
    TransactionSecurityError,
)


GENESIS = "0x" + ("11" * 32)
PAYLOAD = "0x" + ("22" * 32)
SENDER = "0x" + ("33" * 20)


class TransactionSecurityTests(unittest.TestCase):
    def _domain(self, **overrides) -> TransactionDomain:
        values = {
            "chain_id": 20260723,
            "genesis_hash": GENESIS,
            "protocol_version": "junca-mainnet-candidate/v1",
            "network_profile": "mainnet-candidate",
        }
        values.update(overrides)
        return TransactionDomain(**values)

    def _transaction(self, **overrides) -> ReplayProtectedTransaction:
        values = {
            "domain": self._domain(),
            "sender": SENDER,
            "nonce": 0,
            "valid_until_height": 1_000,
            "payload_hash": PAYLOAD,
            "signature": b"signature",
        }
        values.update(overrides)
        return ReplayProtectedTransaction(**values)

    def test_signing_payload_is_domain_separated(self) -> None:
        base = self._transaction()
        different_chain = self._transaction(domain=self._domain(chain_id=20260724))
        different_genesis = self._transaction(
            domain=self._domain(genesis_hash="0x" + ("44" * 32))
        )

        self.assertNotEqual(base.transaction_hash, different_chain.transaction_hash)
        self.assertNotEqual(base.transaction_hash, different_genesis.transaction_hash)

    def test_guard_enforces_nonce_progression(self) -> None:
        guard = TransactionReplayGuard(self._domain())
        first = self._transaction()

        accepted = guard.authorize(first, current_height=10, verifier=lambda _: True)
        self.assertEqual(guard.next_nonce(SENDER), 1)
        self.assertEqual(accepted, first.transaction_hash)

        with self.assertRaisesRegex(TransactionSecurityError, "next sender nonce"):
            guard.authorize(first, current_height=10, verifier=lambda _: True)

        second = self._transaction(nonce=1, signature=b"signature-2")
        guard.authorize(second, current_height=11, verifier=lambda _: True)
        self.assertEqual(guard.next_nonce(SENDER), 2)

    def test_expired_transaction_is_rejected(self) -> None:
        guard = TransactionReplayGuard(self._domain())

        with self.assertRaisesRegex(TransactionSecurityError, "expired"):
            guard.authorize(
                self._transaction(valid_until_height=9),
                current_height=10,
                verifier=lambda _: True,
            )

    def test_signature_failure_does_not_advance_nonce(self) -> None:
        guard = TransactionReplayGuard(self._domain())

        with self.assertRaisesRegex(TransactionSecurityError, "verification failed"):
            guard.authorize(
                self._transaction(),
                current_height=10,
                verifier=lambda _: False,
            )
        self.assertEqual(guard.next_nonce(SENDER), 0)

    def test_cross_network_replay_is_rejected(self) -> None:
        guard = TransactionReplayGuard(self._domain())
        transaction = self._transaction(
            domain=self._domain(network_profile="public-testnet")
        )

        with self.assertRaisesRegex(TransactionSecurityError, "domain mismatch"):
            guard.authorize(
                transaction,
                current_height=10,
                verifier=lambda _: True,
            )

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = TransactionReplayGuard(self._domain()).as_evidence()

        self.assertTrue(evidence["replay_protection"])
        self.assertEqual(evidence["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
