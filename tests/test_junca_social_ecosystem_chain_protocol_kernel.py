from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.protocol_kernel import (
    AccountState,
    ProtocolConfig,
    ProtocolTransitionError,
    TransactionEnvelope,
    compute_state_root,
    execute_block,
    next_base_fee,
    transaction_encoded_size,
    transaction_intrinsic_gas,
)


ALICE = "0x" + ("a" * 40)
BOB = "0x" + ("b" * 40)
CHAIN_ID = 20260723


def transaction(**overrides: object) -> TransactionEnvelope:
    values: dict[str, object] = {
        "chain_id": CHAIN_ID,
        "sender": ALICE,
        "recipient": BOB,
        "nonce": 0,
        "value": 1_000,
        "gas_limit": 21_000,
        "max_fee_per_gas": 2_000,
        "max_priority_fee_per_gas": 100,
        "signature": b"verified-by-execution-client",
    }
    values.update(overrides)
    return TransactionEnvelope(**values)  # type: ignore[arg-type]


class ProtocolKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=42_000,
            target_gas=21_000,
            initial_base_fee=1_000,
        )
        self.accounts = {ALICE: AccountState(balance=100_000_000)}

    def execute(self, *transactions: TransactionEnvelope):
        return execute_block(
            self.config,
            parent_base_fee=1_000,
            parent_gas_used=21_000,
            accounts=self.accounts,
            transactions=transactions,
            signature_verifier=lambda tx: tx.signature == b"verified-by-execution-client",
        )

    def test_transfer_fee_burn_tip_nonce_and_receipt_are_deterministic(self) -> None:
        result = self.execute(transaction())
        self.assertEqual(result.base_fee_per_gas, 1_000)
        self.assertEqual(result.accounts[ALICE].nonce, 1)
        self.assertEqual(result.accounts[BOB].balance, 1_000)
        self.assertEqual(result.total_base_fee_burned, 21_000_000)
        self.assertEqual(result.total_validator_tips, 2_100_000)
        self.assertEqual(result.gas_used, 21_000)
        self.assertEqual(result.receipts[0].effective_gas_price, 1_100)
        self.assertEqual(result.as_evidence()["mainnet_changed"], False)

    def test_chain_replay_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolTransitionError, "chain_id mismatch"):
            self.execute(transaction(chain_id=1))

    def test_nonce_gap_and_replay_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolTransitionError, "nonce"):
            self.execute(transaction(nonce=1))
        duplicate = transaction()
        with self.assertRaisesRegex(ProtocolTransitionError, "duplicate transaction"):
            self.execute(duplicate, duplicate)

    def test_invalid_signature_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolTransitionError, "signature verification"):
            self.execute(transaction(signature=b"invalid"))

    def test_underpriced_and_overpriority_transactions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolTransitionError, "below block base fee"):
            self.execute(transaction(max_fee_per_gas=999))
        with self.assertRaisesRegex(ProtocolTransitionError, "priority fee exceeds"):
            self.execute(transaction(max_fee_per_gas=1_000, max_priority_fee_per_gas=1_001))

    def test_insufficient_balance_is_rejected_without_mutating_input(self) -> None:
        original = dict(self.accounts)
        with self.assertRaisesRegex(ProtocolTransitionError, "insufficient"):
            self.execute(transaction(value=100_000_000))
        self.assertEqual(self.accounts, original)

    def test_block_gas_limit_is_fail_closed(self) -> None:
        second = transaction(nonce=1, signature=b"verified-by-execution-client-2")
        third = transaction(nonce=2, signature=b"verified-by-execution-client-3")
        verifier = lambda tx: tx.signature.startswith(b"verified-by-execution-client")
        with self.assertRaisesRegex(ProtocolTransitionError, "block gas limit"):
            execute_block(
                self.config,
                parent_base_fee=1_000,
                parent_gas_used=21_000,
                accounts=self.accounts,
                transactions=(transaction(), second, third),
                signature_verifier=verifier,
            )

    def test_base_fee_and_state_root_are_order_stable(self) -> None:
        self.assertGreater(
            next_base_fee(self.config, parent_base_fee=1_000, parent_gas_used=42_000),
            1_000,
        )
        self.assertLess(
            next_base_fee(self.config, parent_base_fee=1_000, parent_gas_used=0),
            1_000,
        )
        first = compute_state_root({ALICE: AccountState(1), BOB: AccountState(2)})
        second = compute_state_root({BOB: AccountState(2), ALICE: AccountState(1)})
        self.assertEqual(first, second)

    def test_calldata_intrinsic_gas_is_charged_and_reported(self) -> None:
        payload = b"\x00\x01\x00\xff"
        required = 21_000 + 2 * 4 + 2 * 16
        item = transaction(data=payload, gas_limit=required)

        self.assertEqual(transaction_intrinsic_gas(self.config, item), required)
        result = self.execute(item)
        self.assertEqual(result.gas_used, required)
        self.assertEqual(result.receipts[0].gas_used, required)
        self.assertEqual(result.total_base_fee_burned, required * 1_000)
        self.assertEqual(result.total_validator_tips, required * 100)

    def test_calldata_cannot_bypass_intrinsic_or_block_gas_limits(self) -> None:
        payload = b"nonzero-calldata"
        required = 21_000 + len(payload) * 16
        with self.assertRaisesRegex(ProtocolTransitionError, "below intrinsic"):
            self.execute(transaction(data=payload, gas_limit=required - 1))

        first = transaction(data=payload, gas_limit=required)
        second = transaction(
            nonce=1,
            data=payload,
            gas_limit=required,
            signature=b"verified-by-execution-client-2",
        )
        with self.assertRaisesRegex(ProtocolTransitionError, "block gas limit"):
            execute_block(
                self.config,
                parent_base_fee=1_000,
                parent_gas_used=21_000,
                accounts=self.accounts,
                transactions=(first, second),
                signature_verifier=lambda tx: tx.signature.startswith(
                    b"verified-by-execution-client"
                ),
            )

    def test_canonical_transaction_and_block_byte_caps_fail_closed(self) -> None:
        first = transaction(signature=b"a" * 1_024)
        second = transaction(nonce=1, signature=b"b" * 1_024)
        first_size = transaction_encoded_size(self.config, first)
        second_size = transaction_encoded_size(self.config, second)
        bounded = ProtocolConfig(
            chain_id=CHAIN_ID,
            block_gas_limit=42_000,
            target_gas=21_000,
            initial_base_fee=1_000,
            max_signature_bytes=1_024,
            max_transaction_encoded_bytes=max(first_size, second_size),
            max_block_encoded_bytes=first_size + second_size - 1,
        )
        with self.assertRaisesRegex(ProtocolTransitionError, "block encoded byte"):
            execute_block(
                bounded,
                parent_base_fee=1_000,
                parent_gas_used=21_000,
                accounts=self.accounts,
                transactions=(first, second),
                signature_verifier=lambda tx: bool(tx.signature),
            )

    def test_oversized_signature_is_rejected_before_execution(self) -> None:
        oversized = transaction(signature=b"x" * (self.config.max_signature_bytes + 1))
        with self.assertRaisesRegex(ProtocolTransitionError, "signature exceeds"):
            self.execute(oversized)


if __name__ == "__main__":
    unittest.main()
