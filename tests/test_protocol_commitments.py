from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.protocol_commitments import (
    CanonicalBlockBodyCommitment,
    CanonicalBlockHeader,
    ProtocolCommitmentError,
    ordered_hash_commitment,
)


HASH_A = "0x" + ("11" * 32)
HASH_B = "0x" + ("22" * 32)
HASH_C = "0x" + ("33" * 32)
HASH_D = "0x" + ("44" * 32)
HASH_E = "0x" + ("55" * 32)


class OrderedHashCommitmentTests(unittest.TestCase):
    def test_commitment_is_deterministic_and_order_sensitive(self) -> None:
        first = ordered_hash_commitment((HASH_A, HASH_B), domain="transactions")
        second = ordered_hash_commitment((HASH_A, HASH_B), domain="transactions")
        reversed_root = ordered_hash_commitment(
            (HASH_B, HASH_A),
            domain="transactions",
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, reversed_root)

    def test_domain_separation_prevents_root_substitution(self) -> None:
        transactions = ordered_hash_commitment((HASH_A,), domain="transactions")
        receipts = ordered_hash_commitment((HASH_A,), domain="receipts")

        self.assertNotEqual(transactions, receipts)

    def test_empty_and_odd_commitments_are_stable(self) -> None:
        empty = ordered_hash_commitment((), domain="transactions")
        odd = ordered_hash_commitment(
            (HASH_A, HASH_B, HASH_C),
            domain="transactions",
        )

        self.assertRegex(empty, r"^0x[0-9a-f]{64}$")
        self.assertRegex(odd, r"^0x[0-9a-f]{64}$")
        self.assertEqual(
            odd,
            ordered_hash_commitment(
                (HASH_A, HASH_B, HASH_C),
                domain="transactions",
            ),
        )

    def test_invalid_hash_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProtocolCommitmentError, "32-byte hash"):
            ordered_hash_commitment(("0x01",), domain="transactions")


class CanonicalBlockCommitmentTests(unittest.TestCase):
    def _header(self, **overrides) -> CanonicalBlockHeader:
        body = CanonicalBlockBodyCommitment(
            transaction_hashes=(HASH_A, HASH_B),
            receipt_hashes=(HASH_C, HASH_D),
        )
        values = {
            "protocol_version": "junca-mainnet-candidate/v1",
            "network_profile": "mainnet-candidate",
            "chain_id": 20260723,
            "height": 1,
            "round": 0,
            "timestamp": 1_800_000_030,
            "parent_hash": HASH_E,
            "state_root": HASH_D,
            "transactions_root": body.transactions_root,
            "receipts_root": body.receipts_root,
            "validator_set_hash": HASH_C,
            "proposer_id": "validator-01",
            "gas_limit": 30_000_000,
            "gas_used": 42_000,
            "base_fee_per_gas": 1_000_000_000,
        }
        values.update(overrides)
        return CanonicalBlockHeader(**values)

    def test_body_requires_one_receipt_per_transaction(self) -> None:
        with self.assertRaisesRegex(ProtocolCommitmentError, "counts must match"):
            CanonicalBlockBodyCommitment(
                transaction_hashes=(HASH_A,),
                receipt_hashes=(),
            )

    def test_block_hash_commits_to_consensus_fields(self) -> None:
        base = self._header()

        self.assertNotEqual(base.block_hash, self._header(round=1).block_hash)
        self.assertNotEqual(
            base.block_hash,
            self._header(proposer_id="validator-02").block_hash,
        )
        self.assertNotEqual(
            base.block_hash,
            self._header(transactions_root=HASH_A).block_hash,
        )
        self.assertNotEqual(
            base.block_hash,
            self._header(protocol_version="junca-mainnet-candidate/v2").block_hash,
        )

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = self._header().as_evidence()

        self.assertEqual(evidence["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])

    def test_invalid_resource_boundary_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProtocolCommitmentError, "gas_used exceeds"):
            self._header(gas_limit=21_000, gas_used=42_000)


if __name__ == "__main__":
    unittest.main()
