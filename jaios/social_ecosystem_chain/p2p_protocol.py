"""Versioned P2P message and peer-policy primitives for Mainnet candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = "junca-mainnet-p2p/v1"
MESSAGE_DOMAIN = b"JUNCA_MAINNET_P2P_MESSAGE_V1\x00"
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ALLOWED_TYPES = frozenset(
    {
        "handshake",
        "peer-status",
        "transaction",
        "proposal",
        "vote",
        "finality-proof",
        "block-range",
        "snapshot-manifest",
    }
)


class P2PProtocolError(ValueError):
    """Raised when a peer or message violates Mainnet network policy."""


@dataclass(frozen=True)
class PeerIdentity:
    peer_id: str
    protocol_version: str
    network_profile: str
    chain_id: int
    genesis_hash: str
    node_role: str

    def __post_init__(self) -> None:
        for field in ("peer_id", "network_profile", "node_role"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise P2PProtocolError(f"{field} is invalid")
        if not _VERSION.fullmatch(self.protocol_version):
            raise P2PProtocolError("protocol_version must use semantic versioning")
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise P2PProtocolError("chain_id must be positive")
        _hash(self.genesis_hash, "genesis_hash")
        if self.node_role not in {"validator", "full", "read", "archive", "indexer"}:
            raise P2PProtocolError("node_role is not supported")


@dataclass(frozen=True)
class P2PMessage:
    message_type: str
    sender_peer_id: str
    sequence: int
    height: int
    payload_hash: str
    payload_size: int

    def __post_init__(self) -> None:
        if self.message_type not in _ALLOWED_TYPES:
            raise P2PProtocolError("message_type is not allowlisted")
        if not _IDENTIFIER.fullmatch(self.sender_peer_id):
            raise P2PProtocolError("sender_peer_id is invalid")
        for field in ("sequence", "height", "payload_size"):
            value = getattr(self, field)
            minimum = 1 if field == "payload_size" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise P2PProtocolError(f"{field} is invalid")
        _hash(self.payload_hash, "payload_hash")

    @property
    def message_hash(self) -> str:
        body = {
            "schema_version": SCHEMA_VERSION,
            "message_type": self.message_type,
            "sender_peer_id": self.sender_peer_id,
            "sequence": self.sequence,
            "height": self.height,
            "payload_hash": self.payload_hash.lower(),
            "payload_size": self.payload_size,
        }
        return "0x" + hashlib.sha256(
            MESSAGE_DOMAIN
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class PeerPolicy:
    maximum_message_bytes: int = 4_194_304
    maximum_height_ahead: int = 1_024
    maximum_sequence_gap: int = 10_000
    minimum_distinct_failure_domains: int = 3

    def __post_init__(self) -> None:
        for field in (
            "maximum_message_bytes",
            "maximum_height_ahead",
            "maximum_sequence_gap",
            "minimum_distinct_failure_domains",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise P2PProtocolError(f"{field} must be positive")


class PeerSessionGuard:
    """Reference guard for handshake identity, sequence and resource limits."""

    def __init__(
        self,
        *,
        local: PeerIdentity,
        remote: PeerIdentity,
        policy: PeerPolicy | None = None,
    ) -> None:
        if not isinstance(local, PeerIdentity) or not isinstance(remote, PeerIdentity):
            raise P2PProtocolError("local and remote peer identities are required")
        if (
            local.chain_id != remote.chain_id
            or local.genesis_hash.lower() != remote.genesis_hash.lower()
            or local.network_profile != remote.network_profile
            or local.protocol_version.split(".", 1)[0]
            != remote.protocol_version.split(".", 1)[0]
        ):
            raise P2PProtocolError("peer handshake identity mismatch")
        if local.peer_id == remote.peer_id:
            raise P2PProtocolError("peer session cannot connect an identity to itself")
        self.local = local
        self.remote = remote
        self.policy = PeerPolicy() if policy is None else policy
        self._last_sequence = -1
        self._accepted_hashes: set[str] = set()

    def accept(self, message: P2PMessage, *, local_finalized_height: int) -> str:
        if not isinstance(message, P2PMessage):
            raise P2PProtocolError("message type is invalid")
        if message.sender_peer_id != self.remote.peer_id:
            raise P2PProtocolError("message sender does not match peer session")
        if (
            isinstance(local_finalized_height, bool)
            or not isinstance(local_finalized_height, int)
            or local_finalized_height < 0
        ):
            raise P2PProtocolError("local_finalized_height is invalid")
        if message.payload_size > self.policy.maximum_message_bytes:
            raise P2PProtocolError("message exceeds size policy")
        if message.height > local_finalized_height + self.policy.maximum_height_ahead:
            raise P2PProtocolError("message height is unreasonably ahead")
        if message.sequence <= self._last_sequence:
            raise P2PProtocolError("message sequence replay detected")
        if self._last_sequence >= 0 and message.sequence - self._last_sequence > self.policy.maximum_sequence_gap:
            raise P2PProtocolError("message sequence gap exceeds policy")
        message_hash = message.message_hash
        if message_hash in self._accepted_hashes:
            raise P2PProtocolError("duplicate message hash detected")
        self._last_sequence = message.sequence
        self._accepted_hashes.add(message_hash)
        return message_hash

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "local_peer_id": self.local.peer_id,
            "remote_peer_id": self.remote.peer_id,
            "last_sequence": self._last_sequence,
            "accepted_message_count": len(self._accepted_hashes),
            "identity_bound": True,
            "replay_protected": True,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise P2PProtocolError(f"{field} must be a 32-byte hash")
    return value.lower()
