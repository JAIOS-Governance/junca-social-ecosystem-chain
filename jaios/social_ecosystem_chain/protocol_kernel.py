"""Deterministic account-state transition kernel for JUNCA Social Ecosystem Chain.

The kernel intentionally delegates cryptographic signature recovery and smart
contract execution to the execution-client adapter.  It owns the consensus
critical admission, fee, nonce, value-transfer, receipt, and state-root rules
that can be tested independently from infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Callable, Iterable, Mapping


ZERO_ADDRESS = "0x" + ("0" * 40)
SCHEMA_VERSION = "junca-protocol-kernel/v1"


class ProtocolTransitionError(ValueError):
    """Raised when a block or transaction violates a protocol rule."""


@dataclass(frozen=True)
class ProtocolConfig:
    chain_id: int
    block_gas_limit: int = 30_000_000
    target_gas: int = 15_000_000
    initial_base_fee: int = 1_000_000_000
    base_fee_change_denominator: int = 8
    intrinsic_gas: int = 21_000
    max_transaction_data_bytes: int = 131_072

    def __post_init__(self) -> None:
        values = (
            self.chain_id,
            self.block_gas_limit,
            self.target_gas,
            self.initial_base_fee,
            self.base_fee_change_denominator,
            self.intrinsic_gas,
            self.max_transaction_data_bytes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ProtocolTransitionError("protocol configuration values must be positive integers")
        if self.target_gas > self.block_gas_limit:
            raise ProtocolTransitionError("target_gas cannot exceed block_gas_limit")


@dataclass(frozen=True)
class AccountState:
    balance: int
    nonce: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.balance, bool)
            or not isinstance(self.balance, int)
            or self.balance < 0
            or isinstance(self.nonce, bool)
            or not isinstance(self.nonce, int)
            or self.nonce < 0
        ):
            raise ProtocolTransitionError("account balance and nonce must be non-negative integers")


@dataclass(frozen=True)
class TransactionEnvelope:
    chain_id: int
    sender: str
    recipient: str
    nonce: int
    value: int
    gas_limit: int
    max_fee_per_gas: int
    max_priority_fee_per_gas: int
    data: bytes = b""
    signature: bytes = b""

    def signing_payload(self) -> bytes:
        canonical = {
            "chain_id": self.chain_id,
            "data": self.data.hex(),
            "gas_limit": self.gas_limit,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "nonce": self.nonce,
            "recipient": self.recipient.lower(),
            "sender": self.sender.lower(),
            "value": self.value,
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def transaction_hash(self) -> str:
        return "0x" + hashlib.sha256(self.signing_payload() + self.signature).hexdigest()


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_hash: str
    transaction_index: int
    sender: str
    recipient: str
    gas_used: int
    effective_gas_price: int
    base_fee_burned: int
    validator_tip: int
    status: str = "SUCCESS"


@dataclass(frozen=True)
class BlockTransition:
    chain_id: int
    base_fee_per_gas: int
    gas_used: int
    total_base_fee_burned: int
    total_validator_tips: int
    state_root: str
    accounts: Mapping[str, AccountState]
    receipts: tuple[TransactionReceipt, ...]

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "base_fee_per_gas": self.base_fee_per_gas,
            "gas_used": self.gas_used,
            "total_base_fee_burned": self.total_base_fee_burned,
            "total_validator_tips": self.total_validator_tips,
            "state_root": self.state_root,
            "transaction_count": len(self.receipts),
            "transition_status": "VERIFIED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


SignatureVerifier = Callable[[TransactionEnvelope], bool]


def next_base_fee(
    config: ProtocolConfig,
    *,
    parent_base_fee: int,
    parent_gas_used: int,
) -> int:
    """Calculate the next block base fee using bounded EIP-1559 semantics."""
    if (
        isinstance(parent_base_fee, bool)
        or not isinstance(parent_base_fee, int)
        or parent_base_fee <= 0
    ):
        raise ProtocolTransitionError("parent_base_fee must be a positive integer")
    if (
        isinstance(parent_gas_used, bool)
        or not isinstance(parent_gas_used, int)
        or not 0 <= parent_gas_used <= config.block_gas_limit
    ):
        raise ProtocolTransitionError("parent_gas_used is outside the block gas boundary")
    if parent_gas_used == config.target_gas:
        return parent_base_fee
    gas_delta = abs(parent_gas_used - config.target_gas)
    fee_delta = (
        parent_base_fee
        * gas_delta
        // config.target_gas
        // config.base_fee_change_denominator
    )
    if parent_gas_used > config.target_gas:
        return parent_base_fee + max(fee_delta, 1)
    return max(parent_base_fee - fee_delta, 1)


def execute_block(
    config: ProtocolConfig,
    *,
    parent_base_fee: int,
    parent_gas_used: int,
    accounts: Mapping[str, AccountState],
    transactions: Iterable[TransactionEnvelope],
    signature_verifier: SignatureVerifier,
) -> BlockTransition:
    """Apply a transfer-only block atomically and return deterministic evidence."""
    if not callable(signature_verifier):
        raise ProtocolTransitionError("a cryptographic signature verifier is required")
    state = _normalize_accounts(accounts)
    base_fee = next_base_fee(
        config,
        parent_base_fee=parent_base_fee,
        parent_gas_used=parent_gas_used,
    )
    receipts: list[TransactionReceipt] = []
    seen_hashes: set[str] = set()
    block_gas_used = 0
    total_burned = 0
    total_tips = 0

    for index, transaction in enumerate(transactions):
        _validate_transaction(config, transaction, base_fee)
        tx_hash = transaction.transaction_hash
        if tx_hash in seen_hashes:
            raise ProtocolTransitionError("duplicate transaction hash")
        if not signature_verifier(transaction):
            raise ProtocolTransitionError("transaction signature verification failed")
        if block_gas_used + config.intrinsic_gas > config.block_gas_limit:
            raise ProtocolTransitionError("block gas limit exceeded")

        sender_key = transaction.sender.lower()
        recipient_key = transaction.recipient.lower()
        sender = state.get(sender_key, AccountState(balance=0))
        if transaction.nonce != sender.nonce:
            raise ProtocolTransitionError("transaction nonce does not match sender state")

        priority_fee = min(
            transaction.max_priority_fee_per_gas,
            transaction.max_fee_per_gas - base_fee,
        )
        effective_gas_price = base_fee + priority_fee
        fee = config.intrinsic_gas * effective_gas_price
        total_debit = transaction.value + fee
        if sender.balance < total_debit:
            raise ProtocolTransitionError("insufficient sender balance")

        recipient = state.get(recipient_key, AccountState(balance=0))
        state[sender_key] = replace(
            sender,
            balance=sender.balance - total_debit,
            nonce=sender.nonce + 1,
        )
        state[recipient_key] = replace(
            recipient,
            balance=recipient.balance + transaction.value,
        )

        burned = config.intrinsic_gas * base_fee
        tip = config.intrinsic_gas * priority_fee
        block_gas_used += config.intrinsic_gas
        total_burned += burned
        total_tips += tip
        seen_hashes.add(tx_hash)
        receipts.append(
            TransactionReceipt(
                transaction_hash=tx_hash,
                transaction_index=index,
                sender=sender_key,
                recipient=recipient_key,
                gas_used=config.intrinsic_gas,
                effective_gas_price=effective_gas_price,
                base_fee_burned=burned,
                validator_tip=tip,
            )
        )

    return BlockTransition(
        chain_id=config.chain_id,
        base_fee_per_gas=base_fee,
        gas_used=block_gas_used,
        total_base_fee_burned=total_burned,
        total_validator_tips=total_tips,
        state_root=compute_state_root(state),
        accounts=dict(sorted(state.items())),
        receipts=tuple(receipts),
    )


def compute_state_root(accounts: Mapping[str, AccountState]) -> str:
    canonical = [
        {
            "address": address.lower(),
            "balance": account.balance,
            "nonce": account.nonce,
        }
        for address, account in sorted(accounts.items())
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "0x" + hashlib.sha256(encoded).hexdigest()


def _normalize_accounts(accounts: Mapping[str, AccountState]) -> dict[str, AccountState]:
    normalized: dict[str, AccountState] = {}
    for address, account in accounts.items():
        key = _address(address, "account address")
        if key in normalized:
            raise ProtocolTransitionError("duplicate account after address normalization")
        if not isinstance(account, AccountState):
            raise ProtocolTransitionError("accounts must contain AccountState values")
        normalized[key] = account
    return normalized


def _validate_transaction(
    config: ProtocolConfig,
    transaction: TransactionEnvelope,
    base_fee: int,
) -> None:
    if not isinstance(transaction, TransactionEnvelope):
        raise ProtocolTransitionError("block contains a non-transaction value")
    if transaction.chain_id != config.chain_id:
        raise ProtocolTransitionError("transaction chain_id mismatch")
    _address(transaction.sender, "sender")
    _address(transaction.recipient, "recipient")
    integer_fields = {
        "nonce": transaction.nonce,
        "value": transaction.value,
        "gas_limit": transaction.gas_limit,
        "max_fee_per_gas": transaction.max_fee_per_gas,
        "max_priority_fee_per_gas": transaction.max_priority_fee_per_gas,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in integer_fields.values()
    ):
        raise ProtocolTransitionError("transaction integer fields must be non-negative")
    if transaction.gas_limit < config.intrinsic_gas:
        raise ProtocolTransitionError("transaction gas_limit is below intrinsic gas")
    if transaction.gas_limit > config.block_gas_limit:
        raise ProtocolTransitionError("transaction gas_limit exceeds block gas limit")
    if transaction.max_fee_per_gas < base_fee:
        raise ProtocolTransitionError("max_fee_per_gas is below block base fee")
    if transaction.max_priority_fee_per_gas > transaction.max_fee_per_gas:
        raise ProtocolTransitionError("priority fee exceeds max fee")
    if not isinstance(transaction.data, bytes) or len(transaction.data) > config.max_transaction_data_bytes:
        raise ProtocolTransitionError("transaction data exceeds the protocol boundary")
    if not isinstance(transaction.signature, bytes) or not transaction.signature:
        raise ProtocolTransitionError("transaction signature is required")


def _address(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ProtocolTransitionError(f"{field} must be a 20-byte hex address")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise ProtocolTransitionError(f"{field} must be a 20-byte hex address") from exc
    return value.lower()
