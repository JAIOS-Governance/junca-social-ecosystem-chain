"""Replay-protected transaction-domain controls for Mainnet candidates.

The guard validates chain/genesis/network/protocol domain separation, sender
nonce progression, expiry and cryptographic verification through an injected
verifier.  It does not expose transaction RPC or activate Mainnet.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable


SCHEMA_VERSION = "junca-mainnet-transaction-security/v1"
SIGNING_DOMAIN = b"JUNCA_MAINNET_TRANSACTION_V1\x00"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class TransactionSecurityError(ValueError):
    """Raised when a transaction violates replay or signature policy."""


@dataclass(frozen=True)
class TransactionDomain:
    chain_id: int
    genesis_hash: str
    protocol_version: str
    network_profile: str

    def __post_init__(self) -> None:
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise TransactionSecurityError("chain_id must be a positive integer")
        _hash(self.genesis_hash, "genesis_hash")
        for field in ("protocol_version", "network_profile"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise TransactionSecurityError(f"{field} is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash.lower(),
            "protocol_version": self.protocol_version,
            "network_profile": self.network_profile,
        }


@dataclass(frozen=True)
class ReplayProtectedTransaction:
    domain: TransactionDomain
    sender: str
    nonce: int
    valid_until_height: int
    payload_hash: str
    signature: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.domain, TransactionDomain):
            raise TransactionSecurityError("transaction domain is required")
        if not isinstance(self.sender, str) or not _ADDRESS.fullmatch(self.sender.lower()):
            raise TransactionSecurityError("sender must be a 20-byte address")
        for field in ("nonce", "valid_until_height"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TransactionSecurityError(f"{field} must be non-negative")
        _hash(self.payload_hash, "payload_hash")
        if not isinstance(self.signature, bytes) or not 1 <= len(self.signature) <= 4096:
            raise TransactionSecurityError("signature must be 1 to 4096 bytes")

    @property
    def signing_payload(self) -> bytes:
        body = {
            "schema_version": SCHEMA_VERSION,
            "domain": self.domain.as_dict(),
            "sender": self.sender.lower(),
            "nonce": self.nonce,
            "valid_until_height": self.valid_until_height,
            "payload_hash": self.payload_hash.lower(),
        }
        return SIGNING_DOMAIN + json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    @property
    def transaction_hash(self) -> str:
        return "0x" + hashlib.sha256(self.signing_payload + self.signature).hexdigest()


SignatureVerifier = Callable[[ReplayProtectedTransaction], bool]


class TransactionReplayGuard:
    """In-memory reference guard for deterministic replay-security semantics."""

    def __init__(self, domain: TransactionDomain) -> None:
        if not isinstance(domain, TransactionDomain):
            raise TransactionSecurityError("guard domain is required")
        self.domain = domain
        self._next_nonce: dict[str, int] = {}
        self._accepted_hashes: set[str] = set()

    def next_nonce(self, sender: str) -> int:
        normalized = _address(sender)
        return self._next_nonce.get(normalized, 0)

    def authorize(
        self,
        transaction: ReplayProtectedTransaction,
        *,
        current_height: int,
        verifier: SignatureVerifier,
    ) -> str:
        if not isinstance(transaction, ReplayProtectedTransaction):
            raise TransactionSecurityError("transaction type is invalid")
        if transaction.domain != self.domain:
            raise TransactionSecurityError("transaction domain mismatch")
        if (
            isinstance(current_height, bool)
            or not isinstance(current_height, int)
            or current_height < 0
        ):
            raise TransactionSecurityError("current_height must be non-negative")
        if transaction.valid_until_height < current_height:
            raise TransactionSecurityError("transaction validity window has expired")
        if not callable(verifier):
            raise TransactionSecurityError("cryptographic verifier is required")

        sender = transaction.sender.lower()
        expected_nonce = self._next_nonce.get(sender, 0)
        if transaction.nonce != expected_nonce:
            raise TransactionSecurityError("transaction nonce is not the next sender nonce")
        tx_hash = transaction.transaction_hash
        if tx_hash in self._accepted_hashes:
            raise TransactionSecurityError("transaction replay detected")
        try:
            verified = verifier(transaction)
        except Exception as exc:
            raise TransactionSecurityError("transaction signature verification failed") from exc
        if verified is not True:
            raise TransactionSecurityError("transaction signature verification failed")

        self._accepted_hashes.add(tx_hash)
        self._next_nonce[sender] = expected_nonce + 1
        return tx_hash

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "domain": self.domain.as_dict(),
            "tracked_senders": len(self._next_nonce),
            "accepted_transaction_count": len(self._accepted_hashes),
            "replay_protection": True,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def _address(value: object) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value.lower()):
        raise TransactionSecurityError("sender must be a 20-byte address")
    return value.lower()


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise TransactionSecurityError(f"{field} must be a 32-byte hash")
    return value.lower()
