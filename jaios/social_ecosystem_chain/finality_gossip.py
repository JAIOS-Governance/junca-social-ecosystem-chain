"""Authenticated vote and finalized-vote-set gossip for validator convergence.

The canonical transport sends each signed vote directly to every peer. Direct
fan-out can be asymmetric during startup or recovery: one validator may collect
strict quorum while another misses the final vote. This module provides bounded,
duplicate-suppressed re-propagation and distributes the exact authenticated vote
set after finalization so every healthy validator reconstructs the same finality
certificate independently.

The module does not create votes, alter signatures, lower quorum, copy databases,
or trust a remote certificate. Every vote is authenticated by the canonical
consensus callback, and every announced certificate hash is recomputed from the
three exact validator votes. It is initially activated only by the isolated local
network entrypoint while the protocol integration track is reviewed.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import socket
import struct
import threading
from typing import Any, Mapping

from .finality import FinalityVote
from .validator_node import (
    AuthenticatedVote,
    PrivateVpcPeerTransport,
    PublicTestnetConsensus,
    ValidatorNodeError,
    _authenticated_vote,
    _receive_exact,
    _vote_frame,
)

_MAX_SEEN_VOTES = 4096
_MAX_FINALIZATIONS = 256
_FINALIZATION_SCHEMA = "junca-finalized-authenticated-vote-set/v1"
_FINALIZATION_TYPE = "FINALIZED_AUTHENTICATED_VOTE_SET"

_ACTIVE_CONSENSUS: PublicTestnetConsensus | None = None
_ACTIVE_CONSENSUS_LOCK = threading.Lock()


class GossipAwarePublicTestnetConsensus(PublicTestnetConsensus):
    """Register the process-local canonical consensus for transport evidence."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        global _ACTIVE_CONSENSUS
        with _ACTIVE_CONSENSUS_LOCK:
            _ACTIVE_CONSENSUS = self


class ReliableAuthenticatedVoteGossip(PrivateVpcPeerTransport):
    """Direct transport with authenticated vote and finalized-set gossip."""

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
        with _ACTIVE_CONSENSUS_LOCK:
            self._consensus = _ACTIVE_CONSENSUS
        self._seen_votes: OrderedDict[str, None] = OrderedDict()
        self._vote_packets: OrderedDict[
            tuple[int, int, str], dict[str, AuthenticatedVote]
        ] = OrderedDict()
        self._finalizations: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._seen_lock = threading.Lock()

    def broadcast(self, packet: AuthenticatedVote) -> None:
        """Process locally once and attempt direct delivery to every peer."""

        self._send_latest_finalization(excluded={self.validator_id})
        if self._mark_seen(packet):
            self._process_authenticated_vote(packet, announce_finalization=True)
        failures = self._send_frame_to_peers(
            _vote_frame(packet), excluded={self.validator_id}
        )
        if failures:
            raise ValidatorNodeError("peer vote delivery failed")

    def ingest_from_peer(
        self,
        packet: AuthenticatedVote,
        *,
        source_validator_id: str,
    ) -> bool:
        """Authenticate one new vote, gossip it onward and publish finality."""

        self._validate_source(source_validator_id)
        self._send_latest_finalization(
            excluded=set(self.endpoints) - {source_validator_id}
        )
        if not self._mark_seen(packet):
            return False

        self._process_authenticated_vote(packet, announce_finalization=True)
        self._send_frame_to_peers(
            _vote_frame(packet),
            excluded={self.validator_id, source_validator_id},
        )
        return True

    def ingest_finalization(
        self,
        value: Mapping[str, object],
        *,
        source_validator_id: str,
    ) -> bool:
        """Reconstruct a remote finalization from its exact authenticated votes."""

        self._validate_source(source_validator_id)
        normalized, packets = self._validate_finalization(
            value, source_validator_id=source_validator_id
        )
        certificate_hash = str(normalized["certificate_hash"])
        with self._seen_lock:
            if certificate_hash in self._finalizations:
                self._finalizations.move_to_end(certificate_hash)
                return False

        for packet in packets:
            self._cache_packet(packet)
            if self._mark_seen(packet):
                self._process_authenticated_vote(
                    packet,
                    announce_finalization=False,
                )

        consensus = self._require_consensus()
        certificate = consensus._last_certificate
        head = consensus.runtime.pipeline.store.head()
        if (
            certificate is None
            or certificate.certificate_hash != certificate_hash
            or certificate.height != normalized["height"]
            or certificate.block_hash != normalized["block_hash"]
            or head.height != normalized["height"]
            or head.block_hash != normalized["block_hash"]
            or head.parent_hash != normalized["parent_hash"]
            or head.state_root != normalized["state_root"]
        ):
            raise ValidatorNodeError(
                "finalized vote set did not reproduce the announced finalized state"
            )

        self._remember_finalization(certificate_hash, dict(normalized))
        self._send_frame_to_peers(
            _json_frame(dict(normalized)),
            excluded={self.validator_id, source_validator_id},
        )
        return True

    def evidence(self) -> dict[str, object]:
        with self._seen_lock:
            seen_count = len(self._seen_votes)
            finalization_count = len(self._finalizations)
        return {
            "schema_version": "junca-authenticated-finality-gossip/v1",
            "validator_id": self.validator_id,
            "seen_vote_count": seen_count,
            "maximum_seen_votes": _MAX_SEEN_VOTES,
            "retained_finalization_count": finalization_count,
            "maximum_finalizations": _MAX_FINALIZATIONS,
            "authentication_before_forwarding": True,
            "certificate_reconstructed_from_votes": True,
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
                    if value.get("message_type") == _FINALIZATION_TYPE:
                        self.ingest_finalization(
                            value,
                            source_validator_id=source_validator_id,
                        )
                    else:
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

    def _process_authenticated_vote(
        self,
        packet: AuthenticatedVote,
        *,
        announce_finalization: bool,
    ) -> None:
        consensus = self._consensus
        before_hash = (
            None
            if consensus is None or consensus._last_certificate is None
            else consensus._last_certificate.certificate_hash
        )
        self._cache_packet(packet)

        # The callback verifies both peer authentication and consensus signature.
        self.receive_vote(packet)

        if not announce_finalization or consensus is None:
            return
        certificate = consensus._last_certificate
        if certificate is None or certificate.certificate_hash == before_hash:
            return
        finalization = self._build_finalization(certificate)
        self._remember_finalization(certificate.certificate_hash, finalization)
        self._send_frame_to_peers(
            _json_frame(finalization), excluded={self.validator_id}
        )

    def _build_finalization(self, certificate: object) -> dict[str, object]:
        consensus = self._require_consensus()
        cert = consensus._last_certificate
        if cert is None or cert is not certificate:
            raise ValidatorNodeError("finality certificate is unavailable")
        key = (cert.height, cert.round, cert.block_hash)
        packets = self._vote_packets.get(key, {})
        if tuple(sorted(packets)) != cert.validator_ids:
            raise ValidatorNodeError(
                "finalized certificate is missing its exact authenticated vote set"
            )
        ordered = [packets[validator_id] for validator_id in cert.validator_ids]
        timestamps = {packet.block_timestamp for packet in ordered}
        if len(timestamps) != 1:
            raise ValidatorNodeError("finalized votes disagree on block timestamp")
        head = consensus.runtime.pipeline.store.head()
        if head.height != cert.height or head.block_hash != cert.block_hash:
            raise ValidatorNodeError("finalized certificate does not match durable head")
        return {
            "schema_version": _FINALIZATION_SCHEMA,
            "message_type": _FINALIZATION_TYPE,
            "source_validator_id": self.validator_id,
            "chain_id": cert.chain_id,
            "height": cert.height,
            "round": cert.round,
            "block_hash": cert.block_hash,
            "parent_hash": head.parent_hash,
            "state_root": head.state_root,
            "block_timestamp": next(iter(timestamps)),
            "certificate_hash": cert.certificate_hash,
            "validator_ids": list(cert.validator_ids),
            "vote_hashes": list(cert.vote_hashes),
            "votes": [_vote_payload(packet) for packet in ordered],
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _validate_finalization(
        self,
        value: Mapping[str, object],
        *,
        source_validator_id: str,
    ) -> tuple[dict[str, object], tuple[AuthenticatedVote, ...]]:
        required = {
            "schema_version",
            "message_type",
            "source_validator_id",
            "chain_id",
            "height",
            "round",
            "block_hash",
            "parent_hash",
            "state_root",
            "block_timestamp",
            "certificate_hash",
            "validator_ids",
            "vote_hashes",
            "votes",
            "mainnet_changed",
            "assets_moved",
            "bridge_activated",
        }
        if set(value) != required:
            raise ValidatorNodeError("finalized vote set fields are invalid")
        if (
            value["schema_version"] != _FINALIZATION_SCHEMA
            or value["message_type"] != _FINALIZATION_TYPE
            or value["source_validator_id"] != source_validator_id
            or value["mainnet_changed"] is not False
            or value["assets_moved"] is not False
            or value["bridge_activated"] is not False
        ):
            raise ValidatorNodeError("finalized vote set boundary is invalid")
        for field in ("chain_id", "height", "round"):
            item = value[field]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ValidatorNodeError("finalized vote set numeric identity is invalid")
        if value["chain_id"] <= 0 or value["height"] <= 0:
            raise ValidatorNodeError("finalized vote set height is invalid")
        timestamp = value["block_timestamp"]
        if timestamp is not None and (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp <= 0
        ):
            raise ValidatorNodeError("finalized vote set timestamp is invalid")
        for field in ("block_hash", "parent_hash", "state_root", "certificate_hash"):
            _hash(value[field], field)

        raw_votes = value["votes"]
        validator_ids = value["validator_ids"]
        vote_hashes = value["vote_hashes"]
        if (
            not isinstance(raw_votes, list)
            or len(raw_votes) != 3
            or not isinstance(validator_ids, list)
            or not isinstance(vote_hashes, list)
        ):
            raise ValidatorNodeError("finalized vote set requires exactly three votes")
        packets = tuple(
            sorted(
                (_authenticated_vote(item) for item in raw_votes),
                key=lambda packet: packet.validator_id,
            )
        )
        expected_ids = tuple(sorted(self.endpoints))
        if (
            tuple(packet.validator_id for packet in packets) != expected_ids
            or tuple(validator_ids) != expected_ids
        ):
            raise ValidatorNodeError("finalized vote set validator identity mismatch")
        for packet in packets:
            if (
                packet.chain_id != value["chain_id"]
                or packet.height != value["height"]
                or packet.round != value["round"]
                or packet.block_hash != value["block_hash"]
                or packet.block_timestamp != timestamp
            ):
                raise ValidatorNodeError("finalized vote diverges from announcement")

        computed_vote_hashes = tuple(
            FinalityVote(
                chain_id=packet.chain_id,
                height=packet.height,
                round=packet.round,
                block_hash=packet.block_hash,
                validator_id=packet.validator_id,
                signature=packet.signature,
            ).vote_hash
            for packet in packets
        )
        if tuple(vote_hashes) != computed_vote_hashes:
            raise ValidatorNodeError("finalized vote hashes are invalid")
        expected_certificate_hash = _certificate_hash(
            chain_id=int(value["chain_id"]),
            height=int(value["height"]),
            round=int(value["round"]),
            block_hash=str(value["block_hash"]),
            validator_ids=expected_ids,
            vote_hashes=computed_vote_hashes,
        )
        if value["certificate_hash"] != expected_certificate_hash:
            raise ValidatorNodeError("finalized certificate hash is invalid")
        return dict(value), packets

    def _send_latest_finalization(self, *, excluded: set[str]) -> None:
        with self._seen_lock:
            latest = (
                None
                if not self._finalizations
                else next(reversed(self._finalizations.values()))
            )
        if latest is not None:
            self._send_frame_to_peers(_json_frame(latest), excluded=excluded)

    def _send_frame_to_peers(
        self,
        frame: bytes,
        *,
        excluded: set[str],
    ) -> tuple[str, ...]:
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

    def _cache_packet(self, packet: AuthenticatedVote) -> None:
        key = (packet.height, packet.round, packet.block_hash)
        with self._seen_lock:
            packets = self._vote_packets.setdefault(key, {})
            packets[packet.validator_id] = packet
            self._vote_packets.move_to_end(key)
            while len(self._vote_packets) > _MAX_FINALIZATIONS:
                self._vote_packets.popitem(last=False)

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

    def _remember_finalization(
        self,
        certificate_hash: str,
        finalization: dict[str, object],
    ) -> None:
        with self._seen_lock:
            self._finalizations[certificate_hash] = finalization
            self._finalizations.move_to_end(certificate_hash)
            while len(self._finalizations) > _MAX_FINALIZATIONS:
                self._finalizations.popitem(last=False)

    def _require_consensus(self) -> PublicTestnetConsensus:
        if self._consensus is None:
            raise ValidatorNodeError("gossip consensus binding is unavailable")
        return self._consensus

    def _validate_source(self, source_validator_id: str) -> None:
        if source_validator_id == self.validator_id:
            raise ValidatorNodeError("peer vote source cannot be the local validator")
        if source_validator_id not in self.endpoints:
            raise ValidatorNodeError("peer vote source is not allowlisted")


def _vote_payload(packet: AuthenticatedVote) -> dict[str, object]:
    result: dict[str, object] = {
        "chain_id": packet.chain_id,
        "height": packet.height,
        "round": packet.round,
        "block_hash": packet.block_hash,
        "validator_id": packet.validator_id,
        "signature": packet.signature.hex(),
        "peer_signature": packet.peer_signature.hex(),
    }
    if packet.block_timestamp is not None:
        result["block_timestamp"] = packet.block_timestamp
    return result


def _json_frame(value: Mapping[str, object]) -> bytes:
    body = (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(body) > 16_384:
        raise ValidatorNodeError("peer finalization frame exceeds size boundary")
    return struct.pack(">I", len(body)) + body


def _certificate_hash(
    *,
    chain_id: int,
    height: int,
    round: int,
    block_hash: str,
    validator_ids: tuple[str, ...],
    vote_hashes: tuple[str, ...],
) -> str:
    body = {
        "block_hash": block_hash.lower(),
        "chain_id": chain_id,
        "height": height,
        "round": round,
        "signed_power": len(validator_ids),
        "total_power": len(validator_ids),
        "validator_ids": list(validator_ids),
        "vote_hashes": list(vote_hashes),
    }
    return "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ValidatorNodeError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise ValidatorNodeError(f"{field} must be a 32-byte hex value") from exc
    return value
