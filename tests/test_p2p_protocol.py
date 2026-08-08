from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.p2p_protocol import (
    P2PMessage,
    P2PProtocolError,
    PeerIdentity,
    PeerPolicy,
    PeerSessionGuard,
)


GENESIS = "0x" + ("11" * 32)
PAYLOAD = "0x" + ("22" * 32)


class P2PProtocolTests(unittest.TestCase):
    def _peer(self, peer_id: str, **overrides) -> PeerIdentity:
        values = {
            "peer_id": peer_id,
            "protocol_version": "1.0.0",
            "network_profile": "mainnet-candidate",
            "chain_id": 20260723,
            "genesis_hash": GENESIS,
            "node_role": "validator",
        }
        values.update(overrides)
        return PeerIdentity(**values)

    def _message(self, **overrides) -> P2PMessage:
        values = {
            "message_type": "vote",
            "sender_peer_id": "validator-02",
            "sequence": 1,
            "height": 100,
            "payload_hash": PAYLOAD,
            "payload_size": 512,
        }
        values.update(overrides)
        return P2PMessage(**values)

    def test_handshake_binds_chain_genesis_network_and_major(self) -> None:
        local = self._peer("validator-01")

        with self.assertRaisesRegex(P2PProtocolError, "identity mismatch"):
            PeerSessionGuard(
                local=local,
                remote=self._peer("validator-02", chain_id=20260724),
            )
        with self.assertRaisesRegex(P2PProtocolError, "identity mismatch"):
            PeerSessionGuard(
                local=local,
                remote=self._peer("validator-02", protocol_version="2.0.0"),
            )

    def test_sequence_replay_and_duplicate_are_rejected(self) -> None:
        guard = PeerSessionGuard(
            local=self._peer("validator-01"),
            remote=self._peer("validator-02"),
        )
        message = self._message()

        self.assertEqual(
            guard.accept(message, local_finalized_height=100),
            message.message_hash,
        )
        with self.assertRaisesRegex(P2PProtocolError, "sequence replay"):
            guard.accept(message, local_finalized_height=100)

    def test_size_height_and_sequence_gap_are_bounded(self) -> None:
        guard = PeerSessionGuard(
            local=self._peer("validator-01"),
            remote=self._peer("validator-02"),
            policy=PeerPolicy(
                maximum_message_bytes=1_024,
                maximum_height_ahead=10,
                maximum_sequence_gap=5,
            ),
        )

        with self.assertRaisesRegex(P2PProtocolError, "size"):
            guard.accept(
                self._message(payload_size=1_025),
                local_finalized_height=100,
            )
        with self.assertRaisesRegex(P2PProtocolError, "ahead"):
            guard.accept(
                self._message(height=111),
                local_finalized_height=100,
            )
        guard.accept(self._message(sequence=1), local_finalized_height=100)
        with self.assertRaisesRegex(P2PProtocolError, "gap"):
            guard.accept(
                self._message(sequence=7, payload_hash="0x" + ("33" * 32)),
                local_finalized_height=100,
            )

    def test_sender_is_bound_to_session(self) -> None:
        guard = PeerSessionGuard(
            local=self._peer("validator-01"),
            remote=self._peer("validator-02"),
        )

        with self.assertRaisesRegex(P2PProtocolError, "sender"):
            guard.accept(
                self._message(sender_peer_id="validator-03"),
                local_finalized_height=100,
            )

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = PeerSessionGuard(
            local=self._peer("validator-01"),
            remote=self._peer("validator-02"),
        ).as_evidence()

        self.assertTrue(evidence["identity_bound"])
        self.assertTrue(evidence["replay_protected"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
