"""Deterministic sparse Merkle tree primitives for Mainnet Candidate state.

The tree authenticates already-authorized state values. It does not execute
transactions, activate Mainnet, issue assets, move assets, or enable a bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "junca-authenticated-state-tree/v1"
DEPTH = 256
KEY_DOMAIN = b"JUNCA_STATE_KEY_V1\x00"
LEAF_DOMAIN = b"JUNCA_STATE_LEAF_V1\x00"
NODE_DOMAIN = b"JUNCA_STATE_NODE_V1\x00"
EMPTY_LEAF_DOMAIN = b"JUNCA_STATE_EMPTY_LEAF_V1\x00"
_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_STATE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
MAX_VALUE_BYTES = 1_048_576


class AuthenticatedStateTreeError(ValueError):
    """Raised when a state-tree input or proof is not canonical."""


def _sha(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _hex(value: bytes) -> str:
    return "0x" + value.hex()


def _unhex(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise AuthenticatedStateTreeError(f"{field} must be a 32-byte hash")
    return bytes.fromhex(value[2:])


def canonical_storage_key(namespace: str, key: str) -> str:
    if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
        raise AuthenticatedStateTreeError("namespace is invalid")
    if not isinstance(key, str) or not _STATE_KEY.fullmatch(key):
        raise AuthenticatedStateTreeError("state key is invalid")
    return f"{namespace}:{key}"


def state_key_hash(namespace: str, key: str) -> str:
    storage_key = canonical_storage_key(namespace, key)
    return _hex(_sha(KEY_DOMAIN + storage_key.encode("utf-8")))


def state_value_hash(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise AuthenticatedStateTreeError("state value must be bytes")
    if len(value) > MAX_VALUE_BYTES:
        raise AuthenticatedStateTreeError("state value exceeds maximum size")
    return _hex(_sha(value))


def _leaf_hash(key_hash: bytes, value_hash: bytes) -> bytes:
    return _sha(LEAF_DOMAIN + key_hash + value_hash)


def _node_hash(left: bytes, right: bytes) -> bytes:
    return _sha(NODE_DOMAIN + left + right)


def _empty_hashes() -> tuple[bytes, ...]:
    hashes = [_sha(EMPTY_LEAF_DOMAIN)]
    for _ in range(DEPTH):
        hashes.append(_node_hash(hashes[-1], hashes[-1]))
    return tuple(hashes)


EMPTY_HASHES = _empty_hashes()


@dataclass(frozen=True)
class StateProof:
    key_hash: str
    value_hash: str | None
    siblings: tuple[str, ...]

    def __post_init__(self) -> None:
        _unhex(self.key_hash, "key_hash")
        if self.value_hash is not None:
            _unhex(self.value_hash, "value_hash")
        if not isinstance(self.siblings, tuple) or len(self.siblings) != DEPTH:
            raise AuthenticatedStateTreeError("proof must contain 256 siblings")
        for sibling in self.siblings:
            _unhex(sibling, "sibling")

    @property
    def exists(self) -> bool:
        return self.value_hash is not None

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "key_hash": self.key_hash,
            "value_hash": self.value_hash,
            "exists": self.exists,
            "siblings": list(self.siblings),
        }


class SparseMerkleStateTree:
    """In-memory canonical sparse Merkle tree with verifiable proofs."""

    def __init__(self, entries: Mapping[str, bytes] | None = None) -> None:
        self._values: dict[bytes, bytes] = {}
        if entries:
            for storage_key, value in entries.items():
                if not isinstance(storage_key, str) or ":" not in storage_key:
                    raise AuthenticatedStateTreeError("storage key is invalid")
                namespace, key = storage_key.split(":", 1)
                self.set(namespace, key, value)

    def set(self, namespace: str, key: str, value: bytes) -> None:
        key_hash = _unhex(state_key_hash(namespace, key), "key_hash")
        value_hash = _unhex(state_value_hash(value), "value_hash")
        self._values[key_hash] = value_hash

    def delete(self, namespace: str, key: str) -> bool:
        key_hash = _unhex(state_key_hash(namespace, key), "key_hash")
        return self._values.pop(key_hash, None) is not None

    def contains(self, namespace: str, key: str) -> bool:
        key_hash = _unhex(state_key_hash(namespace, key), "key_hash")
        return key_hash in self._values

    @property
    def root_hash(self) -> str:
        levels = self._build_levels()
        return _hex(levels[DEPTH].get(0, EMPTY_HASHES[DEPTH]))

    @property
    def entry_count(self) -> int:
        return len(self._values)

    def prove(self, namespace: str, key: str) -> StateProof:
        key_hash = _unhex(state_key_hash(namespace, key), "key_hash")
        path = int.from_bytes(key_hash, "big")
        levels = self._build_levels()
        siblings: list[str] = []
        index = path
        for level in range(DEPTH):
            sibling = index ^ 1
            siblings.append(_hex(levels[level].get(sibling, EMPTY_HASHES[level])))
            index >>= 1
        value_hash = self._values.get(key_hash)
        return StateProof(
            key_hash=_hex(key_hash),
            value_hash=None if value_hash is None else _hex(value_hash),
            siblings=tuple(siblings),
        )

    def apply_batch(
        self,
        writes: Iterable[tuple[str, str, bytes | None]],
    ) -> str:
        staged = dict(self._values)
        seen: set[bytes] = set()
        for item in writes:
            if not isinstance(item, tuple) or len(item) != 3:
                raise AuthenticatedStateTreeError("write must be a namespace/key/value tuple")
            namespace, key, value = item
            key_hash = _unhex(state_key_hash(namespace, key), "key_hash")
            if key_hash in seen:
                raise AuthenticatedStateTreeError("batch contains duplicate state key")
            seen.add(key_hash)
            if value is None:
                staged.pop(key_hash, None)
            else:
                staged[key_hash] = _unhex(state_value_hash(value), "value_hash")
        self._values = staged
        return self.root_hash

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "depth": DEPTH,
            "entry_count": self.entry_count,
            "root_hash": self.root_hash,
            "activation_status": "MAINNET_CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _build_levels(self) -> tuple[dict[int, bytes], ...]:
        leaves = {
            int.from_bytes(key_hash, "big"): _leaf_hash(key_hash, value_hash)
            for key_hash, value_hash in self._values.items()
        }
        levels: list[dict[int, bytes]] = [leaves]
        current = leaves
        for level in range(DEPTH):
            parents: dict[int, bytes] = {}
            for parent in {index >> 1 for index in current}:
                left = current.get(parent << 1, EMPTY_HASHES[level])
                right = current.get((parent << 1) | 1, EMPTY_HASHES[level])
                node = _node_hash(left, right)
                if node != EMPTY_HASHES[level + 1]:
                    parents[parent] = node
            levels.append(parents)
            current = parents
        return tuple(levels)


def verify_state_proof(root_hash: str, proof: StateProof) -> bool:
    root = _unhex(root_hash, "root_hash")
    if not isinstance(proof, StateProof):
        raise AuthenticatedStateTreeError("StateProof is required")
    key_hash = _unhex(proof.key_hash, "key_hash")
    if proof.value_hash is None:
        node = EMPTY_HASHES[0]
    else:
        node = _leaf_hash(key_hash, _unhex(proof.value_hash, "value_hash"))
    path = int.from_bytes(key_hash, "big")
    for level, sibling_hex in enumerate(proof.siblings):
        sibling = _unhex(sibling_hex, "sibling")
        if (path >> level) & 1:
            node = _node_hash(sibling, node)
        else:
            node = _node_hash(node, sibling)
    return node == root
