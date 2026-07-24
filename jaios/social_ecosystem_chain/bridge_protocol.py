"""Deterministic, fail-closed testnet bridge message state machine."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from .interoperability import REQUIRED_GOVERNANCE, REQUIRED_NOTICE


class BridgeProtocolError(ValueError):
    """Raised when a bridge message or transition violates protocol controls."""


class BridgeState(str, Enum):
    OBSERVED = "OBSERVED"
    FINALITY_PENDING = "FINALITY_PENDING"
    ATTESTED = "ATTESTED"
    EXECUTION_READY = "EXECUTION_READY"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class BridgeMessage:
    route_digest: str
    direction: str
    source_network: str
    destination_network: str
    nonce: int
    source_transaction: str
    source_block: int
    asset_type: str
    source_asset: str
    destination_asset: str
    sender: str
    recipient: str
    value: int
    token_id: int | None = None
    governance: str = REQUIRED_GOVERNANCE
    notice: str = REQUIRED_NOTICE
    schema_version: int = 1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "destination_asset": self.destination_asset,
            "destination_network": self.destination_network,
            "direction": self.direction,
            "governance": self.governance,
            "nonce": self.nonce,
            "notice": self.notice,
            "recipient": self.recipient,
            "route_digest": self.route_digest,
            "schema_version": self.schema_version,
            "sender": self.sender,
            "source_asset": self.source_asset,
            "source_block": self.source_block,
            "source_network": self.source_network,
            "source_transaction": self.source_transaction,
            "token_id": self.token_id,
            "value": self.value,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(b"JUNCA_BRIDGE_MESSAGE_V1\x00" + encoded).hexdigest()


@dataclass(frozen=True)
class RelayerAttestation:
    relayer_id: str
    message_digest: str
    key_id: str
    signature: str
    cryptographic_verification: bool


@dataclass
class BridgeRecord:
    message: BridgeMessage
    state: BridgeState = BridgeState.OBSERVED
    confirmations: int = 0
    attestations: dict[str, RelayerAttestation] = field(default_factory=dict)
    execution_transaction: str | None = None
    rejection_reason: str | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "message": self.message.canonical_payload(),
            "message_digest": self.message.digest,
            "state": self.state.value,
            "confirmations": self.confirmations,
            "attested_relayers": sorted(self.attestations),
            "execution_transaction": self.execution_transaction,
            "rejection_reason": self.rejection_reason,
        }


class BridgeProtocol:
    """In-memory reference engine used to prove bridge control semantics."""

    def __init__(
        self,
        *,
        route_digest: str,
        allowed_networks: Iterable[str],
        relayer_ids: Iterable[str],
        threshold: int,
        required_confirmations: int,
        per_transaction_limit: int,
        daily_limit: int,
        paused: bool = True,
    ) -> None:
        self.route_digest = route_digest
        self.allowed_networks = frozenset(allowed_networks)
        self.relayer_ids = frozenset(relayer_ids)
        self.threshold = threshold
        self.required_confirmations = required_confirmations
        self.per_transaction_limit = per_transaction_limit
        self.daily_limit = daily_limit
        self.paused = paused
        self.records: dict[str, BridgeRecord] = {}
        self.used_source_transactions: set[str] = set()
        self.used_nonces: set[tuple[str, int]] = set()
        self.executed_value = 0
        self._validate_policy()

    def _validate_policy(self) -> None:
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", self.route_digest)), "invalid route digest")
        _require(len(self.allowed_networks) == 2, "exactly two route networks are required")
        _require("junca-public-testnet" in self.allowed_networks, "JUNCA testnet is required")
        _require(self.allowed_networks & {"bsc-testnet", "tron-shasta"}, "supported destination is required")
        _require(len(self.relayer_ids) >= 3, "at least three relayers are required")
        _require(2 <= self.threshold <= len(self.relayer_ids), "invalid relayer threshold")
        _require(self.required_confirmations > 0, "confirmations must be positive")
        _require(0 < self.per_transaction_limit <= self.daily_limit, "invalid limits")

    def observe(self, message: BridgeMessage) -> BridgeRecord:
        self._validate_message(message)
        digest = message.digest
        _require(digest not in self.records, "message replay detected")
        _require(message.source_transaction not in self.used_source_transactions, "source transaction replay detected")
        nonce_key = (message.source_network, message.nonce)
        _require(nonce_key not in self.used_nonces, "source nonce replay detected")
        record = BridgeRecord(message=message)
        self.records[digest] = record
        self.used_source_transactions.add(message.source_transaction)
        self.used_nonces.add(nonce_key)
        return record

    def apply_confirmations(self, message_digest: str, confirmations: int) -> BridgeRecord:
        record = self._record(message_digest)
        _require(record.state in {BridgeState.OBSERVED, BridgeState.FINALITY_PENDING}, "invalid confirmation transition")
        _require(confirmations >= record.confirmations, "confirmations cannot decrease")
        record.confirmations = confirmations
        record.state = (
            BridgeState.ATTESTED
            if confirmations >= self.required_confirmations and len(record.attestations) >= self.threshold
            else BridgeState.FINALITY_PENDING
        )
        return record

    def attest(self, attestation: RelayerAttestation) -> BridgeRecord:
        record = self._record(attestation.message_digest)
        _require(record.state not in {BridgeState.EXECUTED, BridgeState.REJECTED}, "terminal bridge record")
        _require(attestation.relayer_id in self.relayer_ids, "unknown relayer")
        _require(attestation.relayer_id not in record.attestations, "duplicate relayer attestation")
        _require(attestation.message_digest == record.message.digest, "attestation digest mismatch")
        _require(attestation.cryptographic_verification is True, "signature was not cryptographically verified")
        _require(bool(attestation.key_id), "relayer key id is required")
        _require(bool(re.fullmatch(r"(0x)?[0-9a-fA-F]{128,}", attestation.signature)), "invalid signature encoding")
        record.attestations[attestation.relayer_id] = attestation
        if len(record.attestations) >= self.threshold and record.confirmations >= self.required_confirmations:
            record.state = BridgeState.ATTESTED
        return record

    def prepare_execution(self, message_digest: str) -> BridgeRecord:
        record = self._record(message_digest)
        _require(record.state == BridgeState.ATTESTED, "record is not attested and final")
        _require(self.paused is False, "route is paused")
        _require(record.message.value <= self.per_transaction_limit, "per-transaction limit exceeded")
        _require(self.executed_value + record.message.value <= self.daily_limit, "daily limit exceeded")
        record.state = BridgeState.EXECUTION_READY
        return record

    def mark_executed(self, message_digest: str, execution_transaction: str) -> BridgeRecord:
        record = self._record(message_digest)
        _require(record.state == BridgeState.EXECUTION_READY, "record is not execution-ready")
        _require(bool(re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", execution_transaction)), "invalid execution transaction")
        record.execution_transaction = execution_transaction
        record.state = BridgeState.EXECUTED
        self.executed_value += record.message.value
        return record

    def reject(self, message_digest: str, reason: str) -> BridgeRecord:
        record = self._record(message_digest)
        _require(record.state != BridgeState.EXECUTED, "executed record cannot be rejected")
        _require(bool(reason.strip()), "rejection reason is required")
        record.state = BridgeState.REJECTED
        record.rejection_reason = reason.strip()
        return record

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def _record(self, digest: str) -> BridgeRecord:
        _require(digest in self.records, "unknown bridge message")
        return self.records[digest]

    def _validate_message(self, message: BridgeMessage) -> None:
        _require(message.schema_version == 1, "unsupported message schema")
        _require(message.route_digest == self.route_digest, "route digest mismatch")
        _require(message.governance == REQUIRED_GOVERNANCE, "invalid governance display")
        _require(message.notice == REQUIRED_NOTICE, "testnet notice is required")
        _require(message.source_network in self.allowed_networks, "source network is not on route")
        _require(message.destination_network in self.allowed_networks, "destination network is not on route")
        _require(message.source_network != message.destination_network, "source and destination must differ")
        expected_direction = f"{message.source_network}->{message.destination_network}"
        _require(message.direction == expected_direction, "direction does not match networks")
        _require(message.nonce >= 0 and message.source_block >= 0, "nonce and block must be non-negative")
        _require(bool(re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", message.source_transaction)), "invalid source transaction")
        _require(message.asset_type in {"fungible", "nft"}, "invalid asset type")
        _require(message.value > 0, "value must be positive")
        if message.asset_type == "nft":
            _require(message.token_id is not None and message.token_id >= 0, "NFT token_id is required")
        else:
            _require(message.token_id is None, "fungible message cannot include token_id")
        for field_name, value in (
            ("source_asset", message.source_asset),
            ("destination_asset", message.destination_asset),
            ("sender", message.sender),
            ("recipient", message.recipient),
        ):
            _require(bool(value.strip()), f"{field_name} is required")


def bridge_message_from_mapping(value: Mapping[str, Any]) -> BridgeMessage:
    allowed = {field.name for field in BridgeMessage.__dataclass_fields__.values()}
    unknown = set(value) - allowed
    _require(not unknown, f"unknown bridge message fields: {sorted(unknown)}")
    try:
        return BridgeMessage(**dict(value))
    except TypeError as exc:
        raise BridgeProtocolError(str(exc)) from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BridgeProtocolError(message)
