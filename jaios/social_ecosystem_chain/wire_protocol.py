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
MAX_SNAPSHOT_CHUNKS = 4096
MAX_SNAPSHOT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SIGNATURE_BYTES = 512
MAX_SEQUENCE = (1 << 63) - 1
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
        if (
            not isinstance(self.node_id, str)
            or not self.node_id
            or len(self.node_id.encode("utf-8")) > 128
            or self.node_id.strip() != self.node_id
            or any(ord(character) < 0x21 for character in self.node_id)
        ):
            raise WireProtocolError("node_id is required and bounded")
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
            or isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version != PROTOCOL_VERSION
        ):
            raise WireProtocolError("unsupported handshake protocol identity")
        _canonical_hash(self.genesis_hash, "genesis_hash")
        _canonical_hash(self.session_nonce, "session_nonce")
        if (
            not isinstance(self.capabilities, tuple)
            or not self.capabilities
            or len(self.capabilities) > 32
            or any(
                not isinstance(capability, str)
                or not capability
                or len(capability) > 64
                or not capability.replace("_", "").isalnum()
                for capability in self.capabilities
            )
            or tuple(sorted(set(self.capabilities))) != self.capabilities
        ):
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
        if local.node_id == remote.node_id:
            raise WireProtocolError("peer node_id must be distinct")
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
        if self._next_send > MAX_SEQUENCE:
            raise WireProtocolError("wire sequence space is exhausted")
        _validate_payload(message_type, payload)
        unsigned = {
            "message_type": message_type.value,
            "sequence": self._next_send,
            "payload": payload,
        }
        signature = self._signer(self._session_bound(_canonical(unsigned)))
        if (
            not isinstance(signature, bytes)
            or not signature
            or len(signature) > MAX_SIGNATURE_BYTES
        ):
            raise WireProtocolError("signer returned an invalid signature")
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
            signature_text = decoded["signature"]
            if (
                not isinstance(signature_text, str)
                or not signature_text
                or signature_text != signature_text.lower()
                or len(signature_text) % 2
                or len(signature_text) > MAX_SIGNATURE_BYTES * 2
            ):
                raise ValueError
            signature = bytes.fromhex(signature_text)
            if not signature:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise WireProtocolError("wire envelope encoding is invalid") from exc
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or not 0 <= sequence <= MAX_SEQUENCE
            or sequence != self._next_receive
        ):
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
    if (
        isinstance(requested_start, bool)
        or not isinstance(requested_start, int)
        or requested_start < 1
        or not isinstance(blocks, Sequence)
        or isinstance(blocks, (str, bytes, bytearray))
        or not blocks
        or len(blocks) > MAX_BLOCK_RANGE
    ):
        raise WireProtocolError("block range size is invalid")
    expected_height = requested_start
    previous_hash: str | None = None
    for block in blocks:
        if not isinstance(block, Mapping):
            raise WireProtocolError("block range entry is invalid")
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
            _canonical_hash(block[field], field)
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
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
            or isinstance(self.height, bool)
            or not isinstance(self.height, int)
            or self.height < 0
            or not isinstance(self.chunk_hashes, tuple)
            or not self.chunk_hashes
            or len(self.chunk_hashes) > MAX_SNAPSHOT_CHUNKS
        ):
            raise WireProtocolError("snapshot manifest identity is invalid")
        _canonical_hash(self.block_hash, "block_hash")
        _canonical_hash(self.state_root, "state_root")
        _canonical_hash(self.checkpoint_digest, "checkpoint_digest")
        for value in self.chunk_hashes:
            _canonical_hash(value, "chunk_hash")

    def verify_chunks(self, chunks: Sequence[bytes]) -> str:
        if (
            not isinstance(chunks, Sequence)
            or isinstance(chunks, (str, bytes, bytearray))
            or len(chunks) != len(self.chunk_hashes)
        ):
            raise WireProtocolError("snapshot chunk count mismatch")
        total_bytes = 0
        for expected, chunk in zip(self.chunk_hashes, chunks, strict=True):
            if not isinstance(chunk, bytes):
                raise WireProtocolError("snapshot chunk encoding is invalid")
            total_bytes += len(chunk)
            if len(chunk) > MAX_FRAME_BYTES or total_bytes > MAX_SNAPSHOT_TOTAL_BYTES:
                raise WireProtocolError("snapshot chunk exceeds size boundary")
            actual = "0x" + hashlib.sha256(chunk).hexdigest()
            if actual != expected.lower():
                raise WireProtocolError("snapshot chunk digest mismatch")
        return "VERIFIED"


def _validate_payload(message_type: MessageType, payload: Mapping[str, object]) -> None:
    if not isinstance(message_type, MessageType) or not isinstance(payload, Mapping):
        raise WireProtocolError("message type and payload are required")
    if message_type is MessageType.HELLO:
        required = {
            "node_id",
            "chain_id",
            "genesis_hash",
            "session_nonce",
            "protocol_version",
            "capabilities",
        }
        if set(payload) != required or not isinstance(payload["capabilities"], list):
            raise WireProtocolError("HELLO payload fields are invalid")
        Handshake(
            node_id=payload["node_id"],
            chain_id=payload["chain_id"],
            genesis_hash=payload["genesis_hash"],
            session_nonce=payload["session_nonce"],
            protocol_version=payload["protocol_version"],
            capabilities=tuple(payload["capabilities"]),
        )
    elif message_type is MessageType.STATUS:
        required = {
            "chain_id",
            "genesis_hash",
            "height",
            "block_hash",
            "parent_hash",
            "state_root",
            "signed_power",
            "total_power",
        }
        if set(payload) != required:
            raise WireProtocolError("STATUS payload fields are invalid")
        for field in ("chain_id", "height", "signed_power", "total_power"):
            value = payload[field]
            minimum = 1 if field in {"chain_id", "total_power"} else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise WireProtocolError("STATUS numeric field is invalid")
        if payload["signed_power"] > payload["total_power"]:
            raise WireProtocolError("STATUS voting power is invalid")
        for field in ("genesis_hash", "block_hash", "parent_hash", "state_root"):
            _canonical_hash(payload[field], f"STATUS {field}")
    elif message_type is MessageType.GET_BLOCK_RANGE:
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
    elif message_type is MessageType.BLOCK_RANGE:
        if set(payload) != {"blocks", "finality_proofs"}:
            raise WireProtocolError("BLOCK_RANGE payload fields are invalid")
        blocks, proofs = payload["blocks"], payload["finality_proofs"]
        if (
            not isinstance(blocks, list)
            or not isinstance(proofs, list)
            or not blocks
            or len(blocks) != len(proofs)
            or len(blocks) > MAX_BLOCK_RANGE
        ):
            raise WireProtocolError("BLOCK_RANGE payload size is invalid")
        first = blocks[0]
        if not isinstance(first, Mapping):
            raise WireProtocolError("BLOCK_RANGE entry is invalid")
        validate_block_range(blocks, requested_start=first.get("height"))
        if any(not isinstance(proof, dict) for proof in proofs):
            raise WireProtocolError("BLOCK_RANGE finality proof is invalid")
    elif message_type is MessageType.GET_SNAPSHOT:
        if set(payload) != {"height"}:
            raise WireProtocolError("GET_SNAPSHOT payload fields are invalid")
        height = payload["height"]
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise WireProtocolError("GET_SNAPSHOT height is invalid")
    elif message_type is MessageType.SNAPSHOT_MANIFEST:
        required = {
            "chain_id",
            "height",
            "block_hash",
            "state_root",
            "checkpoint_digest",
            "chunk_hashes",
        }
        if set(payload) != required or not isinstance(payload["chunk_hashes"], list):
            raise WireProtocolError("SNAPSHOT_MANIFEST payload fields are invalid")
        SnapshotManifest(
            chain_id=payload["chain_id"],
            height=payload["height"],
            block_hash=payload["block_hash"],
            state_root=payload["state_root"],
            checkpoint_digest=payload["checkpoint_digest"],
            chunk_hashes=tuple(payload["chunk_hashes"]),
        )
    elif message_type in {MessageType.PING, MessageType.PONG}:
        if set(payload) != {"nonce"}:
            raise WireProtocolError("ping payload fields are invalid")
        _canonical_hash(payload["nonce"], "ping nonce")
    if len(_canonical(payload)) > MAX_FRAME_BYTES - 1024:
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


def _canonical_hash(value: object, field: str) -> None:
    _hash(value, field)
    if value != value.lower():
        raise WireProtocolError(f"{field} must use canonical lowercase hex")
