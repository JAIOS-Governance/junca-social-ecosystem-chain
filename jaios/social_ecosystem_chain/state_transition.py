"""Deterministic state transition and snapshot contracts for Mainnet candidates.

This module is a fail-closed protocol primitive. It does not activate Mainnet,
issue assets, move assets, or enable a bridge. Cryptographic authorization is
injected through an explicitly supplied verifier so the state engine cannot
silently accept unsigned transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = "junca-state-transition/v1"
TX_DOMAIN = b"JUNCA_STATE_TRANSACTION_V1\x00"
STATE_DOMAIN = b"JUNCA_STATE_ROOT_V1\x00"
WRITE_SET_DOMAIN = b"JUNCA_STATE_WRITE_SET_V1\x00"
RECEIPT_DOMAIN = b"JUNCA_STATE_RECEIPT_V1\x00"
BLOCK_RECEIPT_DOMAIN = b"JUNCA_STATE_BLOCK_RECEIPT_V1\x00"
SNAPSHOT_DOMAIN = b"JUNCA_STATE_SNAPSHOT_V1\x00"

_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_PROTOCOL_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_STATE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

MAX_VALUE_BYTES = 1_048_576
MAX_OPERATIONS_PER_TRANSACTION = 256
MAX_TRANSACTION_RESOURCE_UNITS = 10_000_000
MAX_BLOCK_RESOURCE_UNITS = 100_000_000


class StateTransitionError(ValueError):
    """Raised when a state transition violates a canonical protocol boundary."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(domain: bytes, value: object) -> str:
    return "0x" + hashlib.sha256(domain + _canonical_json(value)).hexdigest()


def _normalize_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise StateTransitionError(f"{field} must be a 32-byte lowercase hex hash")
    return value.lower()


def _normalize_address(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value.lower()):
        raise StateTransitionError(f"{field} must be a 20-byte hex address")
    return value.lower()


def _positive_int(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StateTransitionError(f"{field} must be an integer >= {minimum}")
    return value


def _value_hash(value: bytes | None) -> str | None:
    if value is None:
        return None
    return "0x" + hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class StateWrite:
    """One conditional, deterministic mutation of module-scoped state."""

    namespace: str
    key: str
    expected_value_hash: str | None
    value: bytes | None

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not _NAMESPACE.fullmatch(self.namespace):
            raise StateTransitionError("namespace is invalid")
        if not isinstance(self.key, str) or not _STATE_KEY.fullmatch(self.key):
            raise StateTransitionError("state key is invalid")
        if self.expected_value_hash is not None:
            object.__setattr__(
                self,
                "expected_value_hash",
                _normalize_hash(self.expected_value_hash, "expected_value_hash"),
            )
        if self.value is not None:
            if not isinstance(self.value, bytes):
                raise StateTransitionError("state value must be bytes or None")
            if len(self.value) > MAX_VALUE_BYTES:
                raise StateTransitionError("state value exceeds maximum size")

    @property
    def storage_key(self) -> str:
        return f"{self.namespace}:{self.key}"

    @property
    def new_value_hash(self) -> str | None:
        return _value_hash(self.value)

    @property
    def resource_units(self) -> int:
        # Deterministic accounting: fixed operation overhead plus key/value bytes.
        return 100 + len(self.namespace.encode()) + len(self.key.encode()) + (
            len(self.value) if self.value is not None else 0
        )

    def as_commitment_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "key": self.key,
            "expected_value_hash": self.expected_value_hash,
            "new_value_hash": self.new_value_hash,
            "delete": self.value is None,
            "value_size": 0 if self.value is None else len(self.value),
        }


@dataclass(frozen=True)
class StateTransaction:
    chain_id: int
    genesis_hash: str
    protocol_version: str
    sender: str
    nonce: int
    max_resource_units: int
    operations: tuple[StateWrite, ...]

    def __post_init__(self) -> None:
        _positive_int(self.chain_id, "chain_id")
        object.__setattr__(self, "genesis_hash", _normalize_hash(self.genesis_hash, "genesis_hash"))
        if (
            not isinstance(self.protocol_version, str)
            or not _PROTOCOL_VERSION.fullmatch(self.protocol_version)
        ):
            raise StateTransitionError("protocol_version must use semantic versioning")
        object.__setattr__(self, "sender", _normalize_address(self.sender, "sender"))
        _positive_int(self.nonce, "nonce", minimum=0)
        _positive_int(self.max_resource_units, "max_resource_units")
        if self.max_resource_units > MAX_TRANSACTION_RESOURCE_UNITS:
            raise StateTransitionError("max_resource_units exceeds protocol maximum")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise StateTransitionError("operations must be a non-empty tuple")
        if len(self.operations) > MAX_OPERATIONS_PER_TRANSACTION:
            raise StateTransitionError("too many state operations")
        if any(not isinstance(operation, StateWrite) for operation in self.operations):
            raise StateTransitionError("operation type is invalid")
        storage_keys = [operation.storage_key for operation in self.operations]
        if len(set(storage_keys)) != len(storage_keys):
            raise StateTransitionError("transaction contains duplicate state keys")

    @property
    def transaction_hash(self) -> str:
        return _digest(
            TX_DOMAIN,
            {
                "schema_version": SCHEMA_VERSION,
                "chain_id": self.chain_id,
                "genesis_hash": self.genesis_hash,
                "protocol_version": self.protocol_version,
                "sender": self.sender,
                "nonce": self.nonce,
                "max_resource_units": self.max_resource_units,
                "operations": [
                    operation.as_commitment_dict() for operation in self.operations
                ],
            },
        )

    @property
    def write_set_hash(self) -> str:
        return _digest(
            WRITE_SET_DOMAIN,
            [operation.as_commitment_dict() for operation in self.operations],
        )


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_hash: str
    sender: str
    nonce: int
    resource_units_used: int
    pre_state_root: str
    post_state_root: str
    write_set_hash: str
    status: str = "APPLIED"

    @property
    def receipt_hash(self) -> str:
        return _digest(RECEIPT_DOMAIN, self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "sender": self.sender,
            "nonce": self.nonce,
            "resource_units_used": self.resource_units_used,
            "pre_state_root": self.pre_state_root,
            "post_state_root": self.post_state_root,
            "write_set_hash": self.write_set_hash,
            "status": self.status,
        }


@dataclass(frozen=True)
class BlockReceipt:
    height: int
    timestamp: int
    parent_state_root: str
    state_root: str
    transaction_hashes: tuple[str, ...]
    transaction_receipt_hashes: tuple[str, ...]
    resource_units_used: int

    @property
    def receipt_hash(self) -> str:
        return _digest(BLOCK_RECEIPT_DOMAIN, self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "height": self.height,
            "timestamp": self.timestamp,
            "parent_state_root": self.parent_state_root,
            "state_root": self.state_root,
            "transaction_hashes": list(self.transaction_hashes),
            "transaction_receipt_hashes": list(self.transaction_receipt_hashes),
            "resource_units_used": self.resource_units_used,
        }


SignatureVerifier = Callable[[StateTransaction], bool]


class StateMachine:
    """Atomic, deterministic state machine for a single chain identity."""

    def __init__(
        self,
        *,
        chain_id: int,
        genesis_hash: str,
        protocol_version: str,
        state: Mapping[str, bytes] | None = None,
        nonces: Mapping[str, int] | None = None,
        height: int = 0,
        timestamp: int = 0,
    ) -> None:
        self.chain_id = _positive_int(chain_id, "chain_id")
        self.genesis_hash = _normalize_hash(genesis_hash, "genesis_hash")
        if (
            not isinstance(protocol_version, str)
            or not _PROTOCOL_VERSION.fullmatch(protocol_version)
        ):
            raise StateTransitionError("protocol_version must use semantic versioning")
        self.protocol_version = protocol_version
        self.height = _positive_int(height, "height", minimum=0)
        self.timestamp = _positive_int(timestamp, "timestamp", minimum=0)
        self._state: dict[str, bytes] = {}
        for key, value in (state or {}).items():
            if not isinstance(key, str) or ":" not in key:
                raise StateTransitionError("snapshot state key is invalid")
            namespace, item_key = key.split(":", 1)
            StateWrite(namespace, item_key, None, value)
            self._state[key] = bytes(value)
        self._nonces: dict[str, int] = {}
        for address, nonce in (nonces or {}).items():
            normalized = _normalize_address(address, "nonce address")
            self._nonces[normalized] = _positive_int(nonce, "nonce value", minimum=0)
        self._accepted_transaction_hashes: set[str] = set()

    def get(self, namespace: str, key: str) -> bytes | None:
        probe = StateWrite(namespace, key, None, None)
        value = self._state.get(probe.storage_key)
        return None if value is None else bytes(value)

    def expected_nonce(self, sender: str) -> int:
        return self._nonces.get(_normalize_address(sender, "sender"), 0)

    @property
    def state_root(self) -> str:
        return _digest(
            STATE_DOMAIN,
            {
                "schema_version": SCHEMA_VERSION,
                "chain_id": self.chain_id,
                "genesis_hash": self.genesis_hash,
                "protocol_version": self.protocol_version,
                "state": [
                    {
                        "key": key,
                        "value_hash": _value_hash(self._state[key]),
                        "value_size": len(self._state[key]),
                    }
                    for key in sorted(self._state)
                ],
                "nonces": [
                    {"sender": sender, "nonce": self._nonces[sender]}
                    for sender in sorted(self._nonces)
                ],
            },
        )

    def apply_transaction(
        self,
        transaction: StateTransaction,
        *,
        signature_verifier: SignatureVerifier,
    ) -> TransactionReceipt:
        snapshot = self._clone_mutable_state()
        try:
            return self._apply_transaction_in_place(
                transaction,
                signature_verifier=signature_verifier,
            )
        except Exception:
            self._restore_mutable_state(snapshot)
            raise

    def apply_block(
        self,
        *,
        height: int,
        timestamp: int,
        parent_state_root: str,
        transactions: Sequence[StateTransaction],
        signature_verifier: SignatureVerifier,
        max_block_resource_units: int = MAX_BLOCK_RESOURCE_UNITS,
    ) -> BlockReceipt:
        if height != self.height + 1:
            raise StateTransitionError("block height must advance exactly by one")
        if timestamp <= self.timestamp:
            raise StateTransitionError("block timestamp must increase")
        if _normalize_hash(parent_state_root, "parent_state_root") != self.state_root:
            raise StateTransitionError("parent_state_root does not match current state")
        _positive_int(max_block_resource_units, "max_block_resource_units")
        if not isinstance(transactions, Sequence):
            raise StateTransitionError("transactions must be a sequence")

        snapshot = self._clone_mutable_state()
        receipt_list: list[TransactionReceipt] = []
        total_units = 0
        original_root = self.state_root
        try:
            for transaction in transactions:
                receipt = self._apply_transaction_in_place(
                    transaction,
                    signature_verifier=signature_verifier,
                )
                total_units += receipt.resource_units_used
                if total_units > max_block_resource_units:
                    raise StateTransitionError("block resource limit exceeded")
                receipt_list.append(receipt)
            self.height = height
            self.timestamp = timestamp
        except Exception:
            self._restore_mutable_state(snapshot)
            raise

        return BlockReceipt(
            height=height,
            timestamp=timestamp,
            parent_state_root=original_root,
            state_root=self.state_root,
            transaction_hashes=tuple(
                receipt.transaction_hash for receipt in receipt_list
            ),
            transaction_receipt_hashes=tuple(
                receipt.receipt_hash for receipt in receipt_list
            ),
            resource_units_used=total_units,
        )

    def _apply_transaction_in_place(
        self,
        transaction: StateTransaction,
        *,
        signature_verifier: SignatureVerifier,
    ) -> TransactionReceipt:
        if not isinstance(transaction, StateTransaction):
            raise StateTransitionError("transaction type is invalid")
        if not callable(signature_verifier):
            raise StateTransitionError("signature_verifier is required")
        if transaction.chain_id != self.chain_id:
            raise StateTransitionError("transaction chain_id mismatch")
        if transaction.genesis_hash != self.genesis_hash:
            raise StateTransitionError("transaction genesis_hash mismatch")
        if transaction.protocol_version != self.protocol_version:
            raise StateTransitionError("transaction protocol_version mismatch")
        if transaction.transaction_hash in self._accepted_transaction_hashes:
            raise StateTransitionError("transaction replay detected")
        expected_nonce = self.expected_nonce(transaction.sender)
        if transaction.nonce != expected_nonce:
            raise StateTransitionError(
                f"transaction nonce mismatch: expected {expected_nonce}"
            )
        try:
            signature_valid = signature_verifier(transaction)
        except Exception as exc:
            raise StateTransitionError("signature verification failed closed") from exc
        if signature_valid is not True:
            raise StateTransitionError("signature verification rejected transaction")

        resource_units = sum(operation.resource_units for operation in transaction.operations)
        if resource_units > transaction.max_resource_units:
            raise StateTransitionError("transaction resource limit exceeded")

        for operation in transaction.operations:
            existing = self._state.get(operation.storage_key)
            if operation.expected_value_hash != _value_hash(existing):
                raise StateTransitionError(
                    f"state precondition failed for {operation.storage_key}"
                )

        pre_root = self.state_root
        for operation in transaction.operations:
            if operation.value is None:
                self._state.pop(operation.storage_key, None)
            else:
                self._state[operation.storage_key] = bytes(operation.value)
        self._nonces[transaction.sender] = transaction.nonce + 1
        self._accepted_transaction_hashes.add(transaction.transaction_hash)
        post_root = self.state_root
        return TransactionReceipt(
            transaction_hash=transaction.transaction_hash,
            sender=transaction.sender,
            nonce=transaction.nonce,
            resource_units_used=resource_units,
            pre_state_root=pre_root,
            post_state_root=post_root,
            write_set_hash=transaction.write_set_hash,
        )

    def export_snapshot(self) -> bytes:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "protocol_version": self.protocol_version,
            "height": self.height,
            "timestamp": self.timestamp,
            "state_root": self.state_root,
            "state": [
                {
                    "key": key,
                    "value_base64": base64.b64encode(self._state[key]).decode("ascii"),
                }
                for key in sorted(self._state)
            ],
            "nonces": [
                {"sender": sender, "nonce": self._nonces[sender]}
                for sender in sorted(self._nonces)
            ],
            "activation_status": "MAINNET_CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        envelope = {
            "payload": payload,
            "snapshot_digest": _digest(SNAPSHOT_DOMAIN, payload),
        }
        return _canonical_json(envelope)

    @classmethod
    def restore_snapshot(cls, snapshot: bytes) -> "StateMachine":
        if not isinstance(snapshot, bytes):
            raise StateTransitionError("snapshot must be bytes")
        try:
            envelope = json.loads(snapshot.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateTransitionError("snapshot is not valid canonical JSON") from exc
        if snapshot != _canonical_json(envelope):
            raise StateTransitionError("snapshot encoding is not canonical")
        if not isinstance(envelope, dict) or set(envelope) != {
            "payload",
            "snapshot_digest",
        }:
            raise StateTransitionError("snapshot envelope is invalid")
        payload = envelope["payload"]
        expected_payload_fields = {
            "schema_version",
            "chain_id",
            "genesis_hash",
            "protocol_version",
            "height",
            "timestamp",
            "state_root",
            "state",
            "nonces",
            "activation_status",
            "mainnet_changed",
            "assets_moved",
            "bridge_activated",
        }
        if not isinstance(payload, dict) or set(payload) != expected_payload_fields:
            raise StateTransitionError("snapshot payload is invalid")
        if envelope["snapshot_digest"] != _digest(SNAPSHOT_DOMAIN, payload):
            raise StateTransitionError("snapshot digest mismatch")
        if payload["schema_version"] != SCHEMA_VERSION:
            raise StateTransitionError("snapshot schema version mismatch")
        if (
            payload["activation_status"] != "MAINNET_CANDIDATE_NOT_ACTIVATED"
            or payload["mainnet_changed"] is not False
            or payload["assets_moved"] is not False
            or payload["bridge_activated"] is not False
        ):
            raise StateTransitionError("snapshot safety boundary is invalid")

        state_entries = payload["state"]
        if not isinstance(state_entries, list):
            raise StateTransitionError("snapshot state list is invalid")
        state: dict[str, bytes] = {}
        state_keys: list[str] = []
        for entry in state_entries:
            if not isinstance(entry, dict) or set(entry) != {"key", "value_base64"}:
                raise StateTransitionError("snapshot state entry is invalid")
            if not isinstance(entry["key"], str):
                raise StateTransitionError("snapshot state key is invalid")
            try:
                value = base64.b64decode(entry["value_base64"], validate=True)
            except Exception as exc:
                raise StateTransitionError("snapshot state value is invalid") from exc
            if entry["key"] in state:
                raise StateTransitionError("snapshot contains duplicate state key")
            state[entry["key"]] = value
            state_keys.append(entry["key"])
        if state_keys != sorted(state_keys):
            raise StateTransitionError("snapshot state entries are not canonical")

        nonce_entries = payload["nonces"]
        if not isinstance(nonce_entries, list):
            raise StateTransitionError("snapshot nonce list is invalid")
        nonces: dict[str, int] = {}
        nonce_senders: list[str] = []
        for entry in nonce_entries:
            if not isinstance(entry, dict) or set(entry) != {"sender", "nonce"}:
                raise StateTransitionError("snapshot nonce entry is invalid")
            normalized_sender = _normalize_address(entry["sender"], "snapshot nonce sender")
            if entry["sender"] != normalized_sender:
                raise StateTransitionError("snapshot nonce sender is not canonical")
            if normalized_sender in nonces:
                raise StateTransitionError("snapshot contains duplicate nonce address")
            nonces[normalized_sender] = entry["nonce"]
            nonce_senders.append(normalized_sender)
        if nonce_senders != sorted(nonce_senders):
            raise StateTransitionError("snapshot nonce entries are not canonical")

        machine = cls(
            chain_id=payload.get("chain_id"),
            genesis_hash=payload.get("genesis_hash"),
            protocol_version=payload.get("protocol_version"),
            state=state,
            nonces=nonces,
            height=payload.get("height"),
            timestamp=payload.get("timestamp"),
        )
        if machine.state_root != payload.get("state_root"):
            raise StateTransitionError("snapshot state_root mismatch")
        return machine

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "protocol_version": self.protocol_version,
            "height": self.height,
            "timestamp": self.timestamp,
            "state_root": self.state_root,
            "state_entries": len(self._state),
            "nonce_accounts": len(self._nonces),
            "activation_status": "MAINNET_CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _clone_mutable_state(
        self,
    ) -> tuple[dict[str, bytes], dict[str, int], set[str], int, int]:
        return (
            dict(self._state),
            dict(self._nonces),
            set(self._accepted_transaction_hashes),
            self.height,
            self.timestamp,
        )

    def _restore_mutable_state(
        self,
        snapshot: tuple[dict[str, bytes], dict[str, int], set[str], int, int],
    ) -> None:
        (
            self._state,
            self._nonces,
            self._accepted_transaction_hashes,
            self.height,
            self.timestamp,
        ) = snapshot
