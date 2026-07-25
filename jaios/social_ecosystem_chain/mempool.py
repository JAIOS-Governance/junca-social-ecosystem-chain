"""Deterministic mempool and block-candidate construction.

Admission is fail-closed.  Transactions are indexed by sender and nonce,
replacement is bounded, and block construction preserves sender nonce order
while ranking executable heads by validator reward.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping

from .protocol_kernel import (
    AccountState,
    ProtocolConfig,
    ProtocolTransitionError,
    SignatureVerifier,
    TransactionEnvelope,
)


class MempoolError(ValueError):
    """Raised when transaction admission or block selection is unsafe."""


@dataclass(frozen=True)
class MempoolPolicy:
    max_transactions: int = 50_000
    max_per_sender: int = 256
    max_nonce_gap: int = 64
    replacement_bump_percent: int = 10

    def __post_init__(self) -> None:
        values = (
            self.max_transactions,
            self.max_per_sender,
            self.max_nonce_gap,
            self.replacement_bump_percent,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise MempoolError("mempool policy values must be positive integers")
        if self.replacement_bump_percent > 100:
            raise MempoolError("replacement bump percent cannot exceed 100")


@dataclass(frozen=True)
class AdmissionResult:
    transaction_hash: str
    status: str
    pool_size: int


@dataclass(frozen=True)
class BlockCandidate:
    transactions: tuple[TransactionEnvelope, ...]
    gas_limit: int
    gas_used: int
    candidate_digest: str

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-block-candidate/v1",
            "transaction_count": len(self.transactions),
            "transaction_hashes": [tx.transaction_hash for tx in self.transactions],
            "gas_limit": self.gas_limit,
            "gas_used": self.gas_used,
            "candidate_digest": self.candidate_digest,
            "selection_status": "DETERMINISTIC",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


class TransactionPool:
    def __init__(self, config: ProtocolConfig, policy: MempoolPolicy | None = None) -> None:
        self._config = config
        self._policy = policy or MempoolPolicy()
        self._transactions: dict[tuple[str, int], TransactionEnvelope] = {}
        self._hashes: set[str] = set()

    def __len__(self) -> int:
        return len(self._transactions)

    def admit(
        self,
        transaction: TransactionEnvelope,
        *,
        account: AccountState,
        current_base_fee: int,
        signature_verifier: SignatureVerifier,
    ) -> AdmissionResult:
        _validate_admission_boundary(
            self._config,
            self._policy,
            transaction,
            account=account,
            current_base_fee=current_base_fee,
            signature_verifier=signature_verifier,
        )
        sender = transaction.sender.lower()
        key = (sender, transaction.nonce)
        current = self._transactions.get(key)
        if transaction.transaction_hash in self._hashes:
            raise MempoolError("duplicate transaction hash")
        if current is None:
            if len(self._transactions) >= self._policy.max_transactions:
                raise MempoolError("mempool capacity exceeded")
            sender_count = sum(1 for address, _ in self._transactions if address == sender)
            if sender_count >= self._policy.max_per_sender:
                raise MempoolError("per-sender mempool capacity exceeded")
            status = "ADMITTED"
        else:
            _validate_replacement(self._policy, current, transaction)
            self._hashes.remove(current.transaction_hash)
            status = "REPLACED"
        self._transactions[key] = transaction
        self._hashes.add(transaction.transaction_hash)
        return AdmissionResult(transaction.transaction_hash, status, len(self))

    def remove_included(self, transactions: Iterable[TransactionEnvelope]) -> None:
        for transaction in transactions:
            key = (transaction.sender.lower(), transaction.nonce)
            current = self._transactions.get(key)
            if current is not None and current.transaction_hash == transaction.transaction_hash:
                del self._transactions[key]
                self._hashes.remove(current.transaction_hash)

    def prune(self, accounts: Mapping[str, AccountState], *, current_base_fee: int) -> tuple[str, ...]:
        removed: list[str] = []
        for key, transaction in list(self._transactions.items()):
            account = accounts.get(key[0], AccountState(balance=0))
            if (
                transaction.nonce < account.nonce
                or transaction.max_fee_per_gas < current_base_fee
                or transaction.nonce - account.nonce > self._policy.max_nonce_gap
            ):
                del self._transactions[key]
                self._hashes.remove(transaction.transaction_hash)
                removed.append(transaction.transaction_hash)
        return tuple(sorted(removed))

    def build_candidate(
        self,
        accounts: Mapping[str, AccountState],
        *,
        current_base_fee: int,
        gas_limit: int | None = None,
    ) -> BlockCandidate:
        limit = self._config.block_gas_limit if gas_limit is None else gas_limit
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= self._config.block_gas_limit:
            raise MempoolError("candidate gas limit is outside protocol bounds")
        normalized_accounts = {key.lower(): value for key, value in accounts.items()}
        next_nonce = {key: account.nonce for key, account in normalized_accounts.items()}
        selected: list[TransactionEnvelope] = []
        gas_used = 0

        while gas_used + self._config.intrinsic_gas <= limit:
            executable: list[TransactionEnvelope] = []
            senders = {sender for sender, _ in self._transactions}
            for sender in senders:
                nonce = next_nonce.get(sender, normalized_accounts.get(sender, AccountState(0)).nonce)
                transaction = self._transactions.get((sender, nonce))
                if transaction is not None and transaction.max_fee_per_gas >= current_base_fee:
                    executable.append(transaction)
            if not executable:
                break
            transaction = min(
                executable,
                key=lambda tx: (
                    -_validator_reward_per_gas(tx, current_base_fee),
                    tx.transaction_hash,
                ),
            )
            selected.append(transaction)
            sender = transaction.sender.lower()
            next_nonce[sender] = transaction.nonce + 1
            gas_used += self._config.intrinsic_gas

        digest_input = {
            "chain_id": self._config.chain_id,
            "gas_limit": limit,
            "gas_used": gas_used,
            "transactions": [tx.transaction_hash for tx in selected],
        }
        digest = "0x" + hashlib.sha256(
            json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return BlockCandidate(tuple(selected), limit, gas_used, digest)

    def export_snapshot(self) -> dict[str, object]:
        """Export a deterministic, chain-bound restart snapshot."""
        transactions = [
            _transaction_record(transaction)
            for _, transaction in sorted(self._transactions.items())
        ]
        body: dict[str, object] = {
            "schema_version": "junca-mempool-snapshot/v1",
            "chain_id": self._config.chain_id,
            "policy": {
                "max_transactions": self._policy.max_transactions,
                "max_per_sender": self._policy.max_per_sender,
                "max_nonce_gap": self._policy.max_nonce_gap,
                "replacement_bump_percent": self._policy.replacement_bump_percent,
            },
            "transactions": transactions,
        }
        body["snapshot_digest"] = _snapshot_digest(body)
        return body

    def restore_snapshot(
        self,
        snapshot: Mapping[str, object],
        *,
        accounts: Mapping[str, AccountState],
        current_base_fee: int,
        signature_verifier: SignatureVerifier,
    ) -> tuple[str, ...]:
        """Atomically restore pending transactions through normal admission gates."""
        if self._transactions:
            raise MempoolError("snapshot restore requires an empty mempool")
        if not isinstance(snapshot, Mapping):
            raise MempoolError("mempool snapshot must be a mapping")
        required = {
            "schema_version",
            "chain_id",
            "policy",
            "transactions",
            "snapshot_digest",
        }
        if set(snapshot) != required:
            raise MempoolError("mempool snapshot fields are invalid")
        if snapshot["schema_version"] != "junca-mempool-snapshot/v1":
            raise MempoolError("mempool snapshot schema is unsupported")
        if snapshot["chain_id"] != self._config.chain_id:
            raise MempoolError("mempool snapshot chain_id mismatch")
        body = {key: value for key, value in snapshot.items() if key != "snapshot_digest"}
        if snapshot["snapshot_digest"] != _snapshot_digest(body):
            raise MempoolError("mempool snapshot digest mismatch")
        expected_policy = {
            "max_transactions": self._policy.max_transactions,
            "max_per_sender": self._policy.max_per_sender,
            "max_nonce_gap": self._policy.max_nonce_gap,
            "replacement_bump_percent": self._policy.replacement_bump_percent,
        }
        if snapshot["policy"] != expected_policy:
            raise MempoolError("mempool snapshot policy mismatch")
        records = snapshot["transactions"]
        if not isinstance(records, list):
            raise MempoolError("mempool snapshot transactions must be a list")
        normalized_accounts = {address.lower(): account for address, account in accounts.items()}
        restored = TransactionPool(self._config, self._policy)
        hashes: list[str] = []
        for record in records:
            transaction = _transaction_from_record(record)
            account = normalized_accounts.get(transaction.sender.lower(), AccountState(balance=0))
            restored.admit(
                transaction,
                account=account,
                current_base_fee=current_base_fee,
                signature_verifier=signature_verifier,
            )
            hashes.append(transaction.transaction_hash)
        self._transactions = restored._transactions
        self._hashes = restored._hashes
        return tuple(hashes)


def _validate_admission_boundary(
    config: ProtocolConfig,
    policy: MempoolPolicy,
    transaction: TransactionEnvelope,
    *,
    account: AccountState,
    current_base_fee: int,
    signature_verifier: SignatureVerifier,
) -> None:
    if not isinstance(transaction, TransactionEnvelope):
        raise MempoolError("mempool accepts only TransactionEnvelope values")
    if transaction.chain_id != config.chain_id:
        raise MempoolError("transaction chain_id mismatch")
    if not callable(signature_verifier) or not signature_verifier(transaction):
        raise MempoolError("transaction signature verification failed")
    if transaction.nonce < account.nonce:
        raise MempoolError("transaction nonce is already consumed")
    if transaction.nonce - account.nonce > policy.max_nonce_gap:
        raise MempoolError("transaction nonce gap exceeds policy")
    if transaction.gas_limit < config.intrinsic_gas or transaction.gas_limit > config.block_gas_limit:
        raise MempoolError("transaction gas limit is outside protocol bounds")
    if transaction.max_fee_per_gas < current_base_fee:
        raise MempoolError("transaction fee cap is below current base fee")
    if transaction.max_priority_fee_per_gas > transaction.max_fee_per_gas:
        raise MempoolError("transaction priority fee exceeds fee cap")
    worst_case_debit = transaction.value + transaction.gas_limit * transaction.max_fee_per_gas
    if account.balance < worst_case_debit:
        raise MempoolError("sender cannot cover worst-case transaction debit")
    if not transaction.signature:
        raise MempoolError("transaction signature is required")


def _validate_replacement(
    policy: MempoolPolicy,
    current: TransactionEnvelope,
    replacement: TransactionEnvelope,
) -> None:
    denominator = 100
    numerator = denominator + policy.replacement_bump_percent
    required_fee = (current.max_fee_per_gas * numerator + denominator - 1) // denominator
    required_tip = (
        current.max_priority_fee_per_gas * numerator + denominator - 1
    ) // denominator
    if replacement.max_fee_per_gas < required_fee or replacement.max_priority_fee_per_gas < required_tip:
        raise MempoolError("replacement transaction fee bump is insufficient")


def _validator_reward_per_gas(transaction: TransactionEnvelope, base_fee: int) -> int:
    if transaction.max_fee_per_gas < base_fee:
        raise ProtocolTransitionError("transaction fee cap is below base fee")
    return min(
        transaction.max_priority_fee_per_gas,
        transaction.max_fee_per_gas - base_fee,
    )


def _transaction_record(transaction: TransactionEnvelope) -> dict[str, object]:
    return {
        "chain_id": transaction.chain_id,
        "sender": transaction.sender.lower(),
        "recipient": transaction.recipient.lower(),
        "nonce": transaction.nonce,
        "value": transaction.value,
        "gas_limit": transaction.gas_limit,
        "max_fee_per_gas": transaction.max_fee_per_gas,
        "max_priority_fee_per_gas": transaction.max_priority_fee_per_gas,
        "data": transaction.data.hex(),
        "signature": transaction.signature.hex(),
        "transaction_hash": transaction.transaction_hash,
    }


def _transaction_from_record(record: object) -> TransactionEnvelope:
    fields = {
        "chain_id",
        "sender",
        "recipient",
        "nonce",
        "value",
        "gas_limit",
        "max_fee_per_gas",
        "max_priority_fee_per_gas",
        "data",
        "signature",
        "transaction_hash",
    }
    if not isinstance(record, Mapping) or set(record) != fields:
        raise MempoolError("mempool snapshot transaction fields are invalid")
    try:
        data = bytes.fromhex(record["data"])
        signature = bytes.fromhex(record["signature"])
        transaction = TransactionEnvelope(
            chain_id=record["chain_id"],
            sender=record["sender"],
            recipient=record["recipient"],
            nonce=record["nonce"],
            value=record["value"],
            gas_limit=record["gas_limit"],
            max_fee_per_gas=record["max_fee_per_gas"],
            max_priority_fee_per_gas=record["max_priority_fee_per_gas"],
            data=data,
            signature=signature,
        )
    except (TypeError, ValueError) as error:
        raise MempoolError("mempool snapshot transaction encoding is invalid") from error
    if record["transaction_hash"] != transaction.transaction_hash:
        raise MempoolError("mempool snapshot transaction hash mismatch")
    return transaction


def _snapshot_digest(body: Mapping[str, object]) -> str:
    try:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MempoolError("mempool snapshot is not canonical JSON") from error
    return "0x" + hashlib.sha256(b"JUNCA_MEMPOOL_SNAPSHOT_V1\x00" + payload).hexdigest()
