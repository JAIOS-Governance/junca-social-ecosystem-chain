from __future__ import annotations

import hashlib
import hmac
import json
import struct
import unittest

from jaios.social_ecosystem_chain.wire_protocol import (
    AuthenticatedPeerSession,
    Handshake,
    MAX_BLOCK_RANGE,
    MessageType,
    SnapshotManifest,
    WireProtocolError,
    decode_frame,
    encode_frame,
    validate_block_range,
)


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)
KEY_A = b"a" * 32
KEY_B = b"b" * 32


def signer(key):
    return lambda payload: hmac.new(key, payload, hashlib.sha256).digest()


def verifier(node_id, payload, signature):
    key = {"node-a": KEY_A, "node-b": KEY_B}[node_id]
    return hmac.compare_digest(signature, hmac.new(key, payload, hashlib.sha256).digest())


class WireProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = Handshake(
            "node-a", CHAIN_ID, GENESIS, "0x" + ("a" * 64)
        )
        self.b = Handshake(
            "node-b", CHAIN_ID, GENESIS, "0x" + ("b" * 64)
        )
        self.session_a = AuthenticatedPeerSession(
            local=self.a, remote=self.b, signer=signer(KEY_A), verifier=verifier
        )
        self.session_b = AuthenticatedPeerSession(
            local=self.b, remote=self.a, signer=signer(KEY_B), verifier=verifier
        )

    def test_authenticated_round_trip_and_sequence(self) -> None:
        frame = self.session_a.send(
            MessageType.GET_BLOCK_RANGE, {"start_height": 1, "limit": 32}
        )
        envelope = self.session_b.receive(frame)
        self.assertEqual(envelope.sequence, 0)
        self.assertEqual(envelope.payload["limit"], 32)

    def test_replay_and_out_of_order_are_rejected(self) -> None:
        first = self.session_a.send(MessageType.PING, {"nonce": "0x" + ("2" * 64)})
        self.session_b.receive(first)
        with self.assertRaisesRegex(WireProtocolError, "replayed or out of order"):
            self.session_b.receive(first)

    def test_signature_tamper_is_rejected(self) -> None:
        frame = bytearray(
            self.session_a.send(MessageType.PING, {"nonce": "0x" + ("2" * 64)})
        )
        frame[-2] = ord("0") if frame[-2] != ord("0") else ord("1")
        with self.assertRaises(WireProtocolError):
            self.session_b.receive(bytes(frame))

    def test_chain_and_genesis_mismatch_are_rejected(self) -> None:
        wrong_chain = Handshake("node-b", 1, GENESIS, "0x" + ("b" * 64))
        with self.assertRaisesRegex(WireProtocolError, "chain_id"):
            AuthenticatedPeerSession(
                local=self.a, remote=wrong_chain, signer=signer(KEY_A), verifier=verifier
            )
        wrong_genesis = Handshake(
            "node-b", CHAIN_ID, "0x" + ("9" * 64), "0x" + ("b" * 64)
        )
        with self.assertRaisesRegex(WireProtocolError, "genesis"):
            AuthenticatedPeerSession(
                local=self.a, remote=wrong_genesis, signer=signer(KEY_A), verifier=verifier
            )

    def test_equal_session_nonce_is_rejected(self) -> None:
        duplicate = Handshake("node-b", CHAIN_ID, GENESIS, self.a.session_nonce)
        with self.assertRaisesRegex(WireProtocolError, "distinct"):
            AuthenticatedPeerSession(
                local=self.a, remote=duplicate, signer=signer(KEY_A), verifier=verifier
            )

    def test_self_connection_and_non_integer_identity_are_rejected(self) -> None:
        same_identity = Handshake(
            self.a.node_id,
            CHAIN_ID,
            GENESIS,
            "0x" + ("c" * 64),
        )
        with self.assertRaisesRegex(WireProtocolError, "node_id must be distinct"):
            AuthenticatedPeerSession(
                local=self.a,
                remote=same_identity,
                signer=signer(KEY_A),
                verifier=verifier,
            )
        with self.assertRaisesRegex(WireProtocolError, "protocol identity"):
            Handshake("node-c", True, GENESIS, "0x" + ("c" * 64))
        with self.assertRaisesRegex(WireProtocolError, "protocol identity"):
            Handshake(
                "node-c",
                CHAIN_ID,
                GENESIS,
                "0x" + ("c" * 64),
                protocol_version=True,
            )

    def test_handshake_rejects_control_characters_and_noncanonical_hashes(self) -> None:
        with self.assertRaisesRegex(WireProtocolError, "node_id"):
            Handshake(" node-c", CHAIN_ID, GENESIS, "0x" + ("c" * 64))
        with self.assertRaisesRegex(WireProtocolError, "lowercase"):
            Handshake("node-c", CHAIN_ID, "0x" + ("AB" * 32), "0x" + ("c" * 64))
        with self.assertRaisesRegex(WireProtocolError, "capabilities"):
            Handshake(
                "node-c",
                CHAIN_ID,
                GENESIS,
                "0x" + ("c" * 64),
                capabilities=("BLOCK RANGE",),
            )

    def test_noncanonical_and_length_mismatch_frames_are_rejected(self) -> None:
        noncanonical = b'{"z":1, "a":2}'
        with self.assertRaisesRegex(WireProtocolError, "canonical"):
            decode_frame(struct.pack(">I", len(noncanonical)) + noncanonical)
        canonical = b'{"a":2}'
        with self.assertRaisesRegex(WireProtocolError, "length"):
            decode_frame(struct.pack(">I", len(canonical) + 1) + canonical)

    def test_unknown_envelope_field_is_rejected(self) -> None:
        body = {
            "message_type": "PING",
            "sequence": 0,
            "payload": {"nonce": "0x" + ("2" * 64)},
            "signature": "00",
            "unexpected": True,
        }
        with self.assertRaisesRegex(WireProtocolError, "fields"):
            self.session_b.receive(encode_frame(body))

    def test_block_range_request_bounds(self) -> None:
        with self.assertRaisesRegex(WireProtocolError, "bounds"):
            self.session_a.send(
                MessageType.GET_BLOCK_RANGE,
                {"start_height": 1, "limit": MAX_BLOCK_RANGE + 1},
            )

    def test_block_range_linkage_validation(self) -> None:
        first_hash = "0x" + ("2" * 64)
        blocks = [
            {
                "height": 1,
                "block_hash": first_hash,
                "parent_hash": GENESIS,
                "state_root": "0x" + ("3" * 64),
                "certificate_hash": "0x" + ("4" * 64),
            },
            {
                "height": 2,
                "block_hash": "0x" + ("5" * 64),
                "parent_hash": first_hash,
                "state_root": "0x" + ("6" * 64),
                "certificate_hash": "0x" + ("7" * 64),
            },
        ]
        validate_block_range(blocks, requested_start=1)
        blocks[1]["parent_hash"] = GENESIS
        with self.assertRaisesRegex(WireProtocolError, "parent"):
            validate_block_range(blocks, requested_start=1)

    def test_block_range_height_gap_is_rejected(self) -> None:
        block = {
            "height": 2,
            "block_hash": "0x" + ("2" * 64),
            "parent_hash": GENESIS,
            "state_root": "0x" + ("3" * 64),
            "certificate_hash": "0x" + ("4" * 64),
        }
        with self.assertRaisesRegex(WireProtocolError, "non-contiguous"):
            validate_block_range([block], requested_start=1)

    def test_block_range_rejects_boolean_start_and_noncanonical_hash(self) -> None:
        block = {
            "height": 1,
            "block_hash": "0x" + ("AB" * 32),
            "parent_hash": GENESIS,
            "state_root": "0x" + ("3" * 64),
            "certificate_hash": "0x" + ("4" * 64),
        }
        with self.assertRaisesRegex(WireProtocolError, "lowercase"):
            validate_block_range([block], requested_start=1)
        block["block_hash"] = "0x" + ("2" * 64)
        with self.assertRaisesRegex(WireProtocolError, "size"):
            validate_block_range([block], requested_start=True)

    def test_snapshot_chunks_are_verified(self) -> None:
        chunks = [b"accounts-a", b"accounts-b"]
        hashes = tuple("0x" + hashlib.sha256(chunk).hexdigest() for chunk in chunks)
        manifest = SnapshotManifest(
            chain_id=CHAIN_ID,
            height=100,
            block_hash="0x" + ("2" * 64),
            state_root="0x" + ("3" * 64),
            checkpoint_digest="0x" + ("4" * 64),
            chunk_hashes=hashes,
        )
        self.assertEqual(manifest.verify_chunks(chunks), "VERIFIED")
        with self.assertRaisesRegex(WireProtocolError, "digest"):
            manifest.verify_chunks([b"tampered", chunks[1]])
        with self.assertRaisesRegex(WireProtocolError, "encoding"):
            manifest.verify_chunks(["accounts-a", chunks[1]])

    def test_handshake_capabilities_must_be_canonical(self) -> None:
        with self.assertRaisesRegex(WireProtocolError, "canonically"):
            Handshake(
                "node-a",
                CHAIN_ID,
                GENESIS,
                "0x" + ("a" * 64),
                capabilities=("SNAPSHOT_V1", "BLOCK_RANGE_V1"),
            )

    def test_wire_boundary_validates_every_message_schema(self) -> None:
        with self.assertRaisesRegex(WireProtocolError, "STATUS payload fields"):
            self.session_a.send(MessageType.STATUS, {"height": 1})
        with self.assertRaisesRegex(WireProtocolError, "GET_SNAPSHOT height"):
            self.session_a.send(MessageType.GET_SNAPSHOT, {"height": True})
        with self.assertRaisesRegex(WireProtocolError, "SNAPSHOT_MANIFEST"):
            self.session_a.send(
                MessageType.SNAPSHOT_MANIFEST,
                {
                    "chain_id": CHAIN_ID,
                    "height": 1,
                    "block_hash": "0x" + ("2" * 64),
                    "state_root": "0x" + ("3" * 64),
                    "checkpoint_digest": "0x" + ("4" * 64),
                    "chunk_hashes": "not-a-list",
                },
            )
        with self.assertRaisesRegex(WireProtocolError, "HELLO payload fields"):
            payload = self.a.payload()
            payload["unexpected"] = True
            self.session_a.send(MessageType.HELLO, payload)

    def test_signature_encoding_and_size_are_bounded(self) -> None:
        oversized = AuthenticatedPeerSession(
            local=self.a,
            remote=self.b,
            signer=lambda _: b"x" * 513,
            verifier=verifier,
        )
        with self.assertRaisesRegex(WireProtocolError, "invalid signature"):
            oversized.send(MessageType.PING, {"nonce": "0x" + ("2" * 64)})

        frame = encode_frame(
            {
                "message_type": "PING",
                "sequence": 0,
                "payload": {"nonce": "0x" + ("2" * 64)},
                "signature": "AA",
            }
        )
        with self.assertRaisesRegex(WireProtocolError, "encoding"):
            self.session_b.receive(frame)

    def test_nan_payload_is_rejected(self) -> None:
        with self.assertRaisesRegex(WireProtocolError, "serializable"):
            encode_frame({"value": float("nan")})


if __name__ == "__main__":
    unittest.main()
