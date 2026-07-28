"""Versioned canonical block commitments for JUNCA Mainnet candidates.

This module defines consensus-critical commitment primitives without activating
Mainnet or changing the current Public Testnet runtime.  Runtime integration is
intentionally a separate reviewed change after deterministic vectors and
compatibility rules are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Sequence


SCHEMA_VERSION = "junca-protocol-commitments/v1"
BLOCK_HASH_DOMAIN = b"JUNCA_CANONICAL_BLOCK_HEADER_V1\x00"
MERKLE_DOMAIN = b"JUNCA_ORDERED_HASH_COMMITMENT_V1\x00"
ZERO_HASH = "0x" + ("0" * 64)
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class ProtocolCommitmentError(ValueError):
    """Raised when a Mainnet candidate commitment is not canonical."""


def ordered_hash_commitment(values: Sequence[str], *, domain: str) -> str:
    """Commit to an ordered sequence of 32-byte hashes using a binary tree.

    Ordering is consensus-critical.  Odd levels duplicate the final node so the
    result is deterministic across implementations.  The domain is committed at
    every level to prevent cross-purpose root substitution.
    """

    if not isinstance(domain, str) or not _IDENTIFIER.fullmatch(domain):
        raise ProtocolCommitmentError("commitment domain is invalid")
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ProtocolCommitmentError("commitment values must be a sequence")

    domain_bytes = domain.encode("ascii")
    if not values:
        return _digest(MERKLE_DOMAIN + domain_bytes + b"\x00EMPTY")

    level: list[bytes] = []
    for index, value in enumerate(values):
        normalized = _hash(value, f"values[{index}]")
        level.append(
            hashlib.sha256(
                MERKLE_DOMAIN
                + domain_bytes
                + b"\x00LEAF\x00"
                + bytes.fromhex(normalized[2:])
            ).digest()
        )

    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(
                MERKLE_DOMAIN
                + domain_bytes
                + b"\x00NODE\x00"
                + level[index]
                + level[index + 1]
            ).digest()
            for index in range(0, len(level), 2)
        ]
    return "0x" + level[0].hex()


@dataclass(frozen=True)
class CanonicalBlockBodyCommitment:
    transaction_hashes: tuple[str, ...]
    receipt_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_hashes, tuple):
            raise ProtocolCommitmentError("transaction_hashes must be a tuple")
        if not isinstance(self.receipt_hashes, tuple):
            raise ProtocolCommitmentError("receipt_hashes must be a tuple")
        if len(self.transaction_hashes) != len(self.receipt_hashes):
            raise ProtocolCommitmentError(
                "transaction and receipt commitment counts must match"
            )
        for index, value in enumerate(self.transaction_hashes):
            _hash(value, f"transaction_hashes[{index}]")
        for index, value in enumerate(self.receipt_hashes):
            _hash(value, f"receipt_hashes[{index}]")

    @property
    def transactions_root(self) -> str:
        return ordered_hash_commitment(
            self.transaction_hashes,
            domain="transactions",
        )

    @property
    def receipts_root(self) -> str:
        return ordered_hash_commitment(
            self.receipt_hashes,
            domain="receipts",
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "transaction_count": len(self.transaction_hashes),
            "transactions_root": self.transactions_root,
            "receipts_root": self.receipts_root,
        }


@dataclass(frozen=True)
class CanonicalBlockHeader:
    protocol_version: str
    network_profile: str
    chain_id: int
    height: int
    round: int
    timestamp: int
    parent_hash: str
    state_root: str
    transactions_root: str
    receipts_root: str
    validator_set_hash: str
    proposer_id: str
    gas_limit: int
    gas_used: int
    base_fee_per_gas: int

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.protocol_version):
            raise ProtocolCommitmentError("protocol_version is invalid")
        if not _IDENTIFIER.fullmatch(self.network_profile):
            raise ProtocolCommitmentError("network_profile is invalid")
        if not _IDENTIFIER.fullmatch(self.proposer_id):
            raise ProtocolCommitmentError("proposer_id is invalid")

        positive = {
            "chain_id": self.chain_id,
            "timestamp": self.timestamp,
            "gas_limit": self.gas_limit,
            "base_fee_per_gas": self.base_fee_per_gas,
        }
        for field, value in positive.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProtocolCommitmentError(f"{field} must be a positive integer")

        nonnegative = {
            "height": self.height,
            "round": self.round,
            "gas_used": self.gas_used,
        }
        for field, value in nonnegative.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProtocolCommitmentError(
                    f"{field} must be a non-negative integer"
                )
        if self.gas_used > self.gas_limit:
            raise ProtocolCommitmentError("gas_used exceeds gas_limit")

        for field in (
            "parent_hash",
            "state_root",
            "transactions_root",
            "receipts_root",
            "validator_set_hash",
        ):
            _hash(getattr(self, field), field)

    @property
    def signing_payload(self) -> bytes:
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def block_hash(self) -> str:
        return _digest(BLOCK_HASH_DOMAIN + self.signing_payload)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": self.protocol_version,
            "network_profile": self.network_profile,
            "chain_id": self.chain_id,
            "height": self.height,
            "round": self.round,
            "timestamp": self.timestamp,
            "parent_hash": self.parent_hash.lower(),
            "state_root": self.state_root.lower(),
            "transactions_root": self.transactions_root.lower(),
            "receipts_root": self.receipts_root.lower(),
            "validator_set_hash": self.validator_set_hash.lower(),
            "proposer_id": self.proposer_id,
            "gas_limit": self.gas_limit,
            "gas_used": self.gas_used,
            "base_fee_per_gas": self.base_fee_per_gas,
        }

    def as_evidence(self) -> dict[str, Any]:
        return {
            **self.as_dict(),
            "block_hash": self.block_hash,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProtocolCommitmentError(f"{field} must be a 32-byte hash")
    normalized = value.lower()
    if not _HASH.fullmatch(normalized):
        raise ProtocolCommitmentError(f"{field} must be a 32-byte hash")
    return normalized


def _digest(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()
