"""Canonical authenticated wire protocol for JUNCA peer synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import struct
from typing import Callable, Mapping, Sequence


MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_BLOCK_RANGE = 512
PROTOCOL_VERSION = 1


class WireProtocolError(ValueError):
    """Raised when a peer frame violates the wire protocol."""


class MessageType(str, Enum):
    HELLO = "HELLO"
    STATUS = "STATUS"
    GET_BLOCK_RANGE = "GET_BLOCK_RANGE"
    BLOCK_RANGE = "BLOCK_RANGE"
    GET_SNAPSHOT = "GET_SNAPSHOT"
    SNAPSHOT_MANIFEST = "SNAPSHOT_MANIFEST"
    PING = "PING"
    PONG = "PONG"


Signer = Callable[[bytes], bytes]
Verifier = Callable[[str, bytes, bytes], bool]


@dataclass(frozen=True)
class Handshake:
    node_id: str
    chain_id: int
    genesis_hash: str
    session_nonce: str
    protocol_version: int = PROTOCOL_VERSION
    capabilities: tuple[str, ...] = ("BLOCK_RANGE_V1", "SNAPSHOT_V1")

    def __post_init__(self) -> None:
        if not self.node_id or len(self.node_id) > 128:
            raise WireProtocolError("node_id is required and bounded")
        if self.chain_id <= 0 or self.protocol_version != PROTOCOL_VERSION:
            raise WireProtocolError("unsupported handshake protocol identity")
        _hash(self.genesis_hash, "genesis_hash")
        _hash(self.session_nonce, "session_nonce")
        if not self.capabilities or tuple(sorted(set(self.capabilities))) != self.capabilities:
            raise WireProtocolError("capabilities must be unique and canonically ordered")

    def payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash.lower(),
            "session_nonce": self.session_nonce.lower(),
            "protocol_version": self.protocol_version,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class WireEnvelope:
    message_type: MessageType
    sequence: int
    payload: Mapping[str, object]
    signature: str

    def signing_bytes(self) -> bytes:
        return _canonical(
            {
                "message_type": self.message_type.value,
                "sequence": self.sequence,
                "payload": self.payload,
            }
        )


class AuthenticatedPeerSession:
    """Strictly ordered session with externally supplied identity signatures."""

    def __init__(
        self,
        *,
        local: Handshake,
        remote: Handshake,
        signer: Signer,
        verifier: Verifier,
    ) -> None:
        if local.chain_id != remote.chain_id:
            raise WireProtocolError("handshake chain_id mismatch")
        if local.genesis_hash.lower() != remote.genesis_hash.lower():
            raise WireProtocolError("handshake genesis mismatch")
        if local.session_nonce.lower() == remote.session_nonce.lower():
            raise WireProtocolError("session nonces must be distinct")
        if not callable(signer) or not callable(verifier):
            raise WireProtocolError("signer and verifier are required")
        self.local = local
        self.remote = remote
        self._signer = signer
        self._verifier = verifier
        self._next_send = 0
        self._next_receive = 0

    def send(self, message_type: MessageType, payload: Mapping[str, object]) -> bytes:
        _validate_payload(message_type, payload)
        unsigned = {
            "message_type": message_type.value,
            "sequence": self._next_send,
            "payload": payload,
        }
        signature = self._signer(self._session_bound(_canonical(unsigned)))
        if not signature:
            raise WireProtocolError("signer returned an empty signature")
        envelope = dict(unsigned)
        envelope["signature"] = signature.hex()
        frame = encode_frame(envelope)
        self._next_send += 1
        return frame

    def receive(self, frame: bytes) -> WireEnvelope:
        decoded = decode_frame(frame)
        required = {"message_type", "sequence", "payload", "signature"}
        if set(decoded) != required:
            raise WireProtocolError("wire envelope fields are invalid")
        try:
            message_type = MessageType(decoded["message_type"])
            sequence = decoded["sequence"]
            payload = decoded["payload"]
            signature = bytes.fromhex(decoded["signature"])
        except (ValueError, TypeError) as exc:
            raise WireProtocolError("wire envelope encoding is invalid") from exc
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence != self._next_receive:
            raise WireProtocolError("wire sequence is replayed or out of order")
        if not isinstance(payload, dict):
            raise WireProtocolError("wire payload must be an object")
        _validate_payload(message_type, payload)
        unsigned = {
            "message_type": message_type.value,
            "sequence": sequence,
            "payload": payload,
        }
        if not self._verifier(
            self.remote.node_id,
            self._session_bound(_canonical(unsigned)),
            signature,
        ):
            raise WireProtocolError("peer signature verification failed")
        self._next_receive += 1
        return WireEnvelope(message_type, sequence, payload, decoded["signature"])

    def _session_bound(self, message: bytes) -> bytes:
        nonces = sorted((self.local.session_nonce.lower(), self.remote.session_nonce.lower()))
        context = {
            "chain_id": self.local.chain_id,
            "genesis_hash": self.local.genesis_hash.lower(),
            "nonces": nonces,
            "protocol": "JUNCA_PEER_WIRE_V1",
        }
        return _canonical(context) + b"\x00" + message


def encode_frame(envelope: Mapping[str, object]) -> bytes:
    body = _canonical(envelope)
    if not body or len(body) > MAX_FRAME_BYTES:
        raise WireProtocolError("wire frame exceeds size boundary")
    return struct.pack(">I", len(body)) + body


def decode_frame(frame: bytes) -> dict[str, object]:
    if not isinstance(frame, bytes) or len(frame) < 5:
        raise WireProtocolError("wire frame is truncated")
    declared = struct.unpack(">I", frame[:4])[0]
    body = frame[4:]
    if declared != len(body) or declared > MAX_FRAME_BYTES:
        raise WireProtocolError("wire frame length is invalid")
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WireProtocolError("wire frame JSON is invalid") from exc
    if not isinstance(decoded, dict) or _canonical(decoded) != body:
        raise WireProtocolError("wire frame is not canonical")
    return decoded


def validate_block_range(blocks: Sequence[Mapping[str, object]], *, requested_start: int) -> None:
    if not blocks or len(blocks) > MAX_BLOCK_RANGE:
        raise WireProtocolError("block range size is invalid")
    expected_height = requested_start
    previous_hash: str | None = None
    for block in blocks:
        required = {
            "height",
            "block_hash",
            "parent_hash",
            "state_root",
            "certificate_hash",
        }
        if set(block) != required or block["height"] != expected_height:
            raise WireProtocolError("block range is non-contiguous")
        for field in ("block_hash", "parent_hash", "state_root", "certificate_hash"):
            _hash(block[field], field)
        if previous_hash is not None and block["parent_hash"].lower() != previous_hash:
            raise WireProtocolError("block range parent linkage is invalid")
        previous_hash = block["block_hash"].lower()
        expected_height += 1


@dataclass(frozen=True)
class SnapshotManifest:
    chain_id: int
    height: int
    block_hash: str
    state_root: str
    checkpoint_digest: str
    chunk_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.chain_id <= 0 or self.height < 0 or not self.chunk_hashes:
            raise WireProtocolError("snapshot manifest identity is invalid")
        _hash(self.block_hash, "block_hash")
        _hash(self.state_root, "state_root")
        _hash(self.checkpoint_digest, "checkpoint_digest")
        for value in self.chunk_hashes:
            _hash(value, "chunk_hash")

    def verify_chunks(self, chunks: Sequence[bytes]) -> str:
        if len(chunks) != len(self.chunk_hashes):
            raise WireProtocolError("snapshot chunk count mismatch")
        for expected, chunk in zip(self.chunk_hashes, chunks, strict=True):
            if len(chunk) > MAX_FRAME_BYTES:
                raise WireProtocolError("snapshot chunk exceeds size boundary")
            actual = "0x" + hashlib.sha256(chunk).hexdigest()
            if actual != expected.lower():
                raise WireProtocolError("snapshot chunk digest mismatch")
        return "VERIFIED"


def _validate_payload(message_type: MessageType, payload: Mapping[str, object]) -> None:
    if not isinstance(message_type, MessageType) or not isinstance(payload, Mapping):
        raise WireProtocolError("message type and payload are required")
    if message_type is MessageType.GET_BLOCK_RANGE:
        if set(payload) != {"start_height", "limit"}:
            raise WireProtocolError("block range request fields are invalid")
        start, limit = payload["start_height"], payload["limit"]
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 1
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_BLOCK_RANGE
        ):
            raise WireProtocolError("block range request is outside bounds")
    elif message_type in {MessageType.PING, MessageType.PONG}:
        if set(payload) != {"nonce"}:
            raise WireProtocolError("ping payload fields are invalid")
        _hash(payload["nonce"], "ping nonce")
    elif message_type is MessageType.HELLO:
        Handshake(
            node_id=payload.get("node_id"),
            chain_id=payload.get("chain_id"),
            genesis_hash=payload.get("genesis_hash"),
            session_nonce=payload.get("session_nonce"),
            protocol_version=payload.get("protocol_version"),
            capabilities=tuple(payload.get("capabilities", ())),
        )
    elif len(_canonical(payload)) > MAX_FRAME_BYTES - 1024:
        raise WireProtocolError("message payload exceeds size boundary")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WireProtocolError("value is not canonically serializable") from exc


def _hash(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise WireProtocolError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise WireProtocolError(f"{field} must be a 32-byte hex value") from exc
