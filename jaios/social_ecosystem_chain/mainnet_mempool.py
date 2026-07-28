"""Bounded, replay-aware Mainnet Candidate transaction pool.

The pool models admission, sender quotas, nonce gaps and deterministic
replacement ordering. It does not expose public transaction RPC or activate
Mainnet.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "junca-mainnet-mempool/v1"
TX_DOMAIN = b"JUNCA_MAINNET_MEMPOOL_TRANSACTION_V1\x00"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


class MainnetMempoolError(ValueError):
    """Raised when transaction admission violates mempool policy."""


@dataclass(frozen=True)
class MempoolAdmissionPolicy:
    maximum_transactions: int = 50_000
    maximum_per_sender: int = 128
    maximum_nonce_gap: int = 64
    maximum_transaction_bytes: int = 131_072
    minimum_replacement_bump_percent: int = 10

    def __post_init__(self) -> None:
        for field in (
            "maximum_transactions",
            "maximum_per_sender",
            "maximum_nonce_gap",
            "maximum_transaction_bytes",
            "minimum_replacement_bump_percent",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MainnetMempoolError(f"{field} must be positive")
        if self.maximum_per_sender > self.maximum_transactions:
            raise MainnetMempoolError("sender limit exceeds total pool limit")
        if self.minimum_replacement_bump_percent > 100:
            raise MainnetMempoolError("replacement bump exceeds policy")


@dataclass(frozen=True)
class MempoolTransaction:
    chain_id: int
    genesis_hash: str
    sender: str
    nonce: int
    gas_limit: int
    max_fee_per_gas: int
    max_priority_fee_per_gas: int
    payload_hash: str
    encoded_size: int
    signature: bytes

    def __post_init__(self) -> None:
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise MainnetMempoolError("chain_id must be positive")
        _hash(self.genesis_hash, "genesis_hash")
        _address(self.sender, "sender")
        for field in (
            "nonce",
            "gas_limit",
            "max_fee_per_gas",
            "max_priority_fee_per_gas",
            "encoded_size",
        ):
            value = getattr(self, field)
            minimum = 0 if field == "nonce" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise MainnetMempoolError(f"{field} is invalid")
        if self.max_priority_fee_per_gas > self.max_fee_per_gas:
            raise MainnetMempoolError("priority fee exceeds max fee")
        _hash(self.payload_hash, "payload_hash")
        if not isinstance(self.signature, bytes) or not self.signature:
            raise MainnetMempoolError("signature is required")

    @property
    def signing_payload(self) -> bytes:
        body = {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash.lower(),
            "sender": self.sender.lower(),
            "nonce": self.nonce,
            "gas_limit": self.gas_limit,
            "max_fee_per_gas": self.max_fee_per_gas,
            "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            "payload_hash": self.payload_hash.lower(),
        }
        return TX_DOMAIN + json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode()

    @property
    def transaction_hash(self) -> str:
        return "0x" + hashlib.sha256(
            self.signing_payload + self.signature
        ).hexdigest()


SignatureVerifier = Callable[[MempoolTransaction], bool]


class MainnetTransactionPool:
    def __init__(
        self,
        *,
        chain_id: int,
        genesis_hash: str,
        policy: MempoolAdmissionPolicy | None = None,
    ) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise MainnetMempoolError("chain_id must be positive")
        self.chain_id = chain_id
        self.genesis_hash = _hash(genesis_hash, "genesis_hash")
        self.policy = MempoolAdmissionPolicy() if policy is None else policy
        self._by_sender_nonce: dict[tuple[str, int], MempoolTransaction] = {}
        self._by_hash: dict[str, MempoolTransaction] = {}

    def add(
        self,
        transaction: MempoolTransaction,
        *,
        committed_nonce: int,
        verifier: SignatureVerifier,
    ) -> str:
        if not isinstance(transaction, MempoolTransaction):
            raise MainnetMempoolError("transaction type is invalid")
        if (
            transaction.chain_id != self.chain_id
            or transaction.genesis_hash.lower() != self.genesis_hash
        ):
            raise MainnetMempoolError("transaction domain mismatch")
        if (
            isinstance(committed_nonce, bool)
            or not isinstance(committed_nonce, int)
            or committed_nonce < 0
        ):
            raise MainnetMempoolError("committed_nonce must be non-negative")
        if transaction.encoded_size > self.policy.maximum_transaction_bytes:
            raise MainnetMempoolError("transaction exceeds size policy")
        if not committed_nonce <= transaction.nonce <= committed_nonce + self.policy.maximum_nonce_gap:
            raise MainnetMempoolError("transaction nonce is outside admission window")
        if not callable(verifier):
            raise MainnetMempoolError("signature verifier is required")
        try:
            verified = verifier(transaction)
        except Exception as exc:
            raise MainnetMempoolError("transaction signature verification failed") from exc
        if verified is not True:
            raise MainnetMempoolError("transaction signature verification failed")

        sender = transaction.sender.lower()
        identity = (sender, transaction.nonce)
        tx_hash = transaction.transaction_hash
        if tx_hash in self._by_hash:
            raise MainnetMempoolError("duplicate transaction hash")
        existing = self._by_sender_nonce.get(identity)
        if existing is None:
            if len(self._by_hash) >= self.policy.maximum_transactions:
                raise MainnetMempoolError("mempool capacity exceeded")
            sender_count = sum(1 for key in self._by_sender_nonce if key[0] == sender)
            if sender_count >= self.policy.maximum_per_sender:
                raise MainnetMempoolError("sender mempool quota exceeded")
        else:
            minimum_fee = (
                existing.max_fee_per_gas
                * (100 + self.policy.minimum_replacement_bump_percent)
                + 99
            ) // 100
            minimum_priority = (
                existing.max_priority_fee_per_gas
                * (100 + self.policy.minimum_replacement_bump_percent)
                + 99
            ) // 100
            if (
                transaction.max_fee_per_gas < minimum_fee
                or transaction.max_priority_fee_per_gas < minimum_priority
            ):
                raise MainnetMempoolError("replacement fee bump is insufficient")
            del self._by_hash[existing.transaction_hash]

        self._by_sender_nonce[identity] = transaction
        self._by_hash[tx_hash] = transaction
        return tx_hash

    def build_candidate(
        self,
        *,
        committed_nonces: dict[str, int],
        gas_limit: int,
        maximum_transactions: int,
    ) -> tuple[MempoolTransaction, ...]:
        if isinstance(gas_limit, bool) or not isinstance(gas_limit, int) or gas_limit <= 0:
            raise MainnetMempoolError("gas_limit must be positive")
        if (
            isinstance(maximum_transactions, bool)
            or not isinstance(maximum_transactions, int)
            or maximum_transactions <= 0
        ):
            raise MainnetMempoolError("maximum_transactions must be positive")
        expected = {address.lower(): nonce for address, nonce in committed_nonces.items()}
        selected: list[MempoolTransaction] = []
        gas_used = 0
        ordered = sorted(
            self._by_hash.values(),
            key=lambda item: (
                -item.max_priority_fee_per_gas,
                -item.max_fee_per_gas,
                item.transaction_hash,
            ),
        )
        remaining = ordered
        while remaining and len(selected) < maximum_transactions:
            progressed = False
            next_remaining: list[MempoolTransaction] = []
            for transaction in remaining:
                sender = transaction.sender.lower()
                sender_nonce = expected.get(sender, 0)
                if transaction.nonce != sender_nonce:
                    next_remaining.append(transaction)
                    continue
                if gas_used + transaction.gas_limit > gas_limit:
                    continue
                selected.append(transaction)
                gas_used += transaction.gas_limit
                expected[sender] = sender_nonce + 1
                progressed = True
                if len(selected) >= maximum_transactions:
                    break
            if not progressed:
                break
            remaining = next_remaining
        return tuple(selected)

    def remove_included(self, transactions: Iterable[MempoolTransaction]) -> None:
        for transaction in transactions:
            tx_hash = transaction.transaction_hash
            self._by_hash.pop(tx_hash, None)
            self._by_sender_nonce.pop(
                (transaction.sender.lower(), transaction.nonce), None
            )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "transaction_count": len(self._by_hash),
            "sender_count": len({key[0] for key in self._by_sender_nonce}),
            "bounded": True,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise MainnetMempoolError(f"{field} must be a 32-byte hash")
    return value.lower()


def _address(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value.lower()):
        raise MainnetMempoolError(f"{field} must be a 20-byte address")
    return value.lower()
