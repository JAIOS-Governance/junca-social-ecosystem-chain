from __future__ import annotations

import unittest
from unittest.mock import patch

from jaios.social_ecosystem_chain.finality_gossip import (
    ReliableAuthenticatedVoteGossip,
)
from jaios.social_ecosystem_chain.validator_node import (
    AuthenticatedVote,
    ValidatorNodeError,
)


ENDPOINTS = {
    "validator-01": ("127.0.0.11", 30303),
    "validator-02": ("127.0.0.12", 30303),
    "validator-03": ("127.0.0.13", 30303),
}


def packet(validator_id: str = "validator-02") -> AuthenticatedVote:
    return AuthenticatedVote(
        chain_id=20260723,
        height=1,
        round=0,
        block_hash="0x" + ("11" * 32),
        validator_id=validator_id,
        signature=b"s" * 64,
        peer_signature=b"p" * 64,
        block_timestamp=10,
    )


class FakeConnection:
    def __init__(self, endpoint: tuple[str, int], sent: list[tuple[tuple[str, int], bytes]]):
        self.endpoint = endpoint
        self.sent = sent

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def sendall(self, value: bytes) -> None:
        self.sent.append((self.endpoint, value))


class ReliableAuthenticatedVoteGossipTests(unittest.TestCase):
    def make_transport(self, received: list[AuthenticatedVote]):
        return ReliableAuthenticatedVoteGossip(
            validator_id="validator-01",
            endpoints=ENDPOINTS,
            receive_vote=received.append,
        )

    def test_local_retry_submits_once_but_retries_every_peer(self) -> None:
        received: list[AuthenticatedVote] = []
        sent: list[tuple[tuple[str, int], bytes]] = []
        transport = self.make_transport(received)

        def connect(endpoint: tuple[str, int], timeout: int) -> FakeConnection:
            self.assertEqual(timeout, 3)
            return FakeConnection(endpoint, sent)

        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=connect,
        ):
            transport.broadcast(packet())
            transport.broadcast(packet())

        self.assertEqual(len(received), 1)
        self.assertEqual(len(sent), 4)
        self.assertEqual(
            {endpoint for endpoint, _ in sent},
            {ENDPOINTS["validator-02"], ENDPOINTS["validator-03"]},
        )

    def test_new_peer_vote_is_forwarded_once_excluding_source(self) -> None:
        received: list[AuthenticatedVote] = []
        sent: list[tuple[tuple[str, int], bytes]] = []
        transport = self.make_transport(received)

        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=lambda endpoint, timeout: FakeConnection(endpoint, sent),
        ):
            self.assertTrue(
                transport.ingest_from_peer(
                    packet(), source_validator_id="validator-02"
                )
            )
            self.assertFalse(
                transport.ingest_from_peer(
                    packet(), source_validator_id="validator-02"
                )
            )

        self.assertEqual(received, [packet()])
        self.assertEqual([endpoint for endpoint, _ in sent], [ENDPOINTS["validator-03"]])
        self.assertEqual(transport.observed_peer_count(), 1)

    def test_forwarded_vote_does_not_authenticate_the_transport_source(self) -> None:
        received: list[AuthenticatedVote] = []
        transport = self.make_transport(received)

        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=lambda endpoint, timeout: FakeConnection(endpoint, []),
        ):
            self.assertTrue(
                transport.ingest_from_peer(
                    packet("validator-02"),
                    source_validator_id="validator-03",
                )
            )

        self.assertEqual(transport.observed_peer_count(), 0)

    def test_duplicate_direct_vote_authenticates_its_matching_source(self) -> None:
        received: list[AuthenticatedVote] = []
        transport = self.make_transport(received)

        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=lambda endpoint, timeout: FakeConnection(endpoint, []),
        ):
            self.assertTrue(
                transport.ingest_from_peer(
                    packet("validator-02"),
                    source_validator_id="validator-03",
                )
            )
            self.assertFalse(
                transport.ingest_from_peer(
                    packet("validator-02"),
                    source_validator_id="validator-02",
                )
            )

        self.assertEqual(transport.observed_peer_count(), 1)

    def test_failed_authentication_is_not_forwarded(self) -> None:
        sent: list[tuple[tuple[str, int], bytes]] = []

        def reject(_: AuthenticatedVote) -> None:
            raise ValidatorNodeError("peer vote authentication failed")

        transport = ReliableAuthenticatedVoteGossip(
            validator_id="validator-01",
            endpoints=ENDPOINTS,
            receive_vote=reject,
        )
        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=lambda endpoint, timeout: FakeConnection(endpoint, sent),
        ):
            with self.assertRaisesRegex(
                ValidatorNodeError, "peer vote authentication failed"
            ):
                transport.ingest_from_peer(
                    packet(), source_validator_id="validator-02"
                )

        self.assertEqual(sent, [])
        self.assertEqual(transport.observed_peer_count(), 0)

    def test_failed_authentication_does_not_poison_a_later_retry(self) -> None:
        received: list[AuthenticatedVote] = []
        reject_once = [True]

        def receive(value: AuthenticatedVote) -> None:
            if reject_once:
                reject_once.pop()
                raise ValidatorNodeError("peer vote authentication failed")
            received.append(value)

        transport = ReliableAuthenticatedVoteGossip(
            validator_id="validator-01",
            endpoints=ENDPOINTS,
            receive_vote=receive,
        )
        with patch(
            "jaios.social_ecosystem_chain.finality_gossip.socket.create_connection",
            side_effect=lambda endpoint, timeout: FakeConnection(endpoint, []),
        ):
            with self.assertRaisesRegex(
                ValidatorNodeError,
                "peer vote authentication failed",
            ):
                transport.ingest_from_peer(
                    packet(),
                    source_validator_id="validator-02",
                )
            self.assertTrue(
                transport.ingest_from_peer(
                    packet(),
                    source_validator_id="validator-02",
                )
            )

        self.assertEqual(received, [packet()])
        self.assertEqual(transport.observed_peer_count(), 1)

    def test_evidence_preserves_protocol_boundaries(self) -> None:
        transport = self.make_transport([])
        evidence = transport.evidence()
        self.assertTrue(evidence["authentication_before_forwarding"])
        self.assertTrue(evidence["duplicate_suppression"])
        self.assertFalse(evidence["quorum_changed"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
