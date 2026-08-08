from __future__ import annotations

from dataclasses import replace
import unittest

from jaios.social_ecosystem_chain.protocol_kernel import (
    AccountState,
    ProtocolConfig,
    ProtocolTransitionError,
    TransactionEnvelope,
    compute_state_root,
    execute_block,
    next_base_fee,
    validate_block_transition,
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

    def test_transition_integrity_rejects_tampered_receipt_accounting(self) -> None:
        result = self.execute(transaction())
        receipt = result.receipts[0]
        tampered = {
            "receipt index": replace(
                result,
                receipts=(replace(receipt, transaction_index=1),),
            ),
            "receipt gas": replace(result, gas_used=result.gas_used + 1),
            "base fee burn": replace(
                result,
                receipts=(replace(receipt, base_fee_burned=receipt.base_fee_burned + 1),),
            ),
            "validator tip": replace(
                result,
                receipts=(replace(receipt, validator_tip=receipt.validator_tip + 1),),
            ),
            "aggregate burn": replace(
                result,
                total_base_fee_burned=result.total_base_fee_burned + 1,
            ),
        }
        for label, transition in tampered.items():
            with self.subTest(label=label):
                with self.assertRaises(ProtocolTransitionError):
                    validate_block_transition(transition)

    def test_transition_integrity_rejects_duplicate_and_noncanonical_receipts(self) -> None:
        result = self.execute(transaction())
        receipt = result.receipts[0]
        duplicate = replace(
            result,
            gas_used=result.gas_used * 2,
            total_base_fee_burned=result.total_base_fee_burned * 2,
            total_validator_tips=result.total_validator_tips * 2,
            receipts=(receipt, replace(receipt, transaction_index=1)),
        )
        with self.assertRaisesRegex(ProtocolTransitionError, "duplicate receipt"):
            validate_block_transition(duplicate)
        uppercase = replace(
            result,
            receipts=(replace(receipt, sender=receipt.sender.upper().replace("0X", "0x")),),
        )
        with self.assertRaisesRegex(ProtocolTransitionError, "canonical"):
            validate_block_transition(uppercase)

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


if __name__ == "__main__":
    unittest.main()
