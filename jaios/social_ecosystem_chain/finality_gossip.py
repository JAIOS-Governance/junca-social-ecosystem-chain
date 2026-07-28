"""Reliable authenticated vote gossip for isolated validator convergence.

The canonical validator transport sends each signed vote directly to every peer.
This module adds bounded, duplicate-suppressed re-propagation so an authenticated
vote that reaches any healthy validator can still reach the remaining validators
when the original direct delivery was asymmetric.

The transport does not create votes, alter signatures, lower quorum, or accept an
unverified packet. The canonical consensus callback authenticates every packet
before the packet is forwarded. This module is initially activated only by the
isolated development entrypoint while the protocol integration track is reviewed.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import socket
import struct
import threading
from typing import Mapping

from .validator_node import (
    AuthenticatedVote,
    PrivateVpcPeerTransport,
    ValidatorNodeError,
    _authenticated_vote,
    _receive_exact,
    _vote_frame,
)

_MAX_SEEN_VOTES = 4096


class ReliableAuthenticatedVoteGossip(PrivateVpcPeerTransport):
    """Direct vote transport with bounded authenticated re-propagation."""

    def __init__(
        self,
        *,
        validator_id: str,
        endpoints: Mapping[str, tuple[str, int]],
        receive_vote: object,
    ) -> None:
        super().__init__(
            validator_id=validator_id,
            endpoints=endpoints,
            receive_vote=receive_vote,
        )
        self._seen_votes: OrderedDict[str, None] = OrderedDict()
        self._seen_lock = threading.Lock()

    def broadcast(self, packet: AuthenticatedVote) -> None:
        """Process locally once and attempt direct delivery to every peer.

        A retry of the same locally signed packet does not re-submit the vote to
        local consensus, but it does retry every peer delivery. Any failed peer
        keeps the canonical finality loop in fail-closed retry mode.
        """

        first_seen = self._mark_seen(packet)
        if first_seen:
            self.receive_vote(packet)
        failures = self._send_to_peers(packet, excluded={self.validator_id})
        if failures:
            raise ValidatorNodeError("peer vote delivery failed")

    def ingest_from_peer(
        self,
        packet: AuthenticatedVote,
        *,
        source_validator_id: str,
    ) -> bool:
        """Authenticate through consensus, then gossip one new packet onward."""

        if source_validator_id == self.validator_id:
            raise ValidatorNodeError("peer vote source cannot be the local validator")
        if source_validator_id not in self.endpoints:
            raise ValidatorNodeError("peer vote source is not allowlisted")
        if not self._mark_seen(packet):
            return False

        # The callback performs peer-signature and consensus-signature validation.
        # Forwarding occurs only after that fail-closed authentication succeeds.
        self.receive_vote(packet)
        self._send_to_peers(
            packet,
            excluded={self.validator_id, source_validator_id},
        )
        return True

    def evidence(self) -> dict[str, object]:
        with self._seen_lock:
            seen_count = len(self._seen_votes)
        return {
            "schema_version": "junca-authenticated-vote-gossip/v1",
            "validator_id": self.validator_id,
            "seen_vote_count": seen_count,
            "maximum_seen_votes": _MAX_SEEN_VOTES,
            "authentication_before_forwarding": True,
            "duplicate_suppression": True,
            "quorum_changed": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _serve(self) -> None:
        assert self._server is not None
        source_by_host = {
            host: identity
            for identity, (host, _) in self.endpoints.items()
            if identity != self.validator_id
        }
        while not self._stop.is_set():
            try:
                connection, address = self._server.accept()
            except (socket.timeout, OSError):
                continue
            with connection:
                source_validator_id = source_by_host.get(address[0])
                if source_validator_id is None:
                    continue
                connection.settimeout(3)
                try:
                    header = _receive_exact(connection, 4)
                    length = struct.unpack(">I", header)[0]
                    if not 1 <= length <= 16_384:
                        continue
                    body = _receive_exact(connection, length)
                    value = json.loads(body)
                    if not isinstance(value, dict):
                        continue
                    self.ingest_from_peer(
                        _authenticated_vote(value),
                        source_validator_id=source_validator_id,
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                    ValidatorNodeError,
                    ValueError,
                ):
                    continue

    def _send_to_peers(
        self,
        packet: AuthenticatedVote,
        *,
        excluded: set[str],
    ) -> tuple[str, ...]:
        frame = _vote_frame(packet)
        failures: list[str] = []
        for identity, endpoint in sorted(self.endpoints.items()):
            if identity in excluded:
                continue
            try:
                with socket.create_connection(endpoint, timeout=3) as connection:
                    connection.sendall(frame)
            except OSError:
                failures.append(identity)
        return tuple(failures)

    def _mark_seen(self, packet: AuthenticatedVote) -> bool:
        digest = hashlib.sha256(_vote_frame(packet)[4:]).hexdigest()
        with self._seen_lock:
            if digest in self._seen_votes:
                self._seen_votes.move_to_end(digest)
                return False
            self._seen_votes[digest] = None
            while len(self._seen_votes) > _MAX_SEEN_VOTES:
                self._seen_votes.popitem(last=False)
        return True
