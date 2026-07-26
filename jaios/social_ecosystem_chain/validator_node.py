"""Executable, keyless public-testnet validator process.

This module is deliberately limited to the JUNCA public testnet.  It binds a
canonical genesis document to a durable SQLite state store and exposes the
small, read-only JSON-RPC surface used by runtime acceptance.  Consensus key
material is never accepted; only a KMS/HSM resource identifier may be bound.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import struct
import threading
from typing import Any, Mapping, Sequence

from .consensus_signing_journal import ConsensusSigningJournal
from .finality import FinalityVote, Validator
from .mempool import TransactionPool
from .node_pipeline import ExecutedProposal, NodeExecutionPipeline
from .protocol_kernel import AccountState, ProtocolConfig
from .state_store import PersistentStateStore
from .sync_finality import ValidatorSet, ValidatorSetSchedule
from .validator_runtime import (
    FinalizedProposal,
    LiveValidatorRuntime,
    ValidatorSignerBinding,
)


NETWORK_LABEL = "Public Testnet / No Monetary Value"
GENESIS_SCHEMA = "junca-public-testnet-genesis/v1"
CLIENT_VERSION = "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
ZERO_HASH = "0x" + ("0" * 64)


class ValidatorNodeError(ValueError):
    """Raised when node configuration violates a runtime safety boundary."""


ConsensusVerifier = Any
PeerVerifier = Any


class AwsKmsSecp256k1Adapter:
    """AWS KMS ECC_SECG_P256K1 signer with fixed-width consensus signatures."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            try:
                import boto3  # type: ignore
                from botocore.config import Config  # type: ignore
            except ImportError as exc:
                raise ValidatorNodeError("boto3/botocore is required for AWS KMS") from exc
            client = boto3.client(
                "kms",
                config=Config(
                    retries={"max_attempts": 4, "mode": "standard"},
                    connect_timeout=3,
                    read_timeout=8,
                ),
            )
        self.client = client

    def sign(self, resource: str, payload: bytes) -> bytes:
        _kms_arn(resource)
        digest = hashlib.sha256(payload).digest()
        try:
            response = self.client.sign(
                KeyId=resource,
                Message=digest,
                MessageType="DIGEST",
                SigningAlgorithm="ECDSA_SHA_256",
            )
            signature = _der_to_raw(response["Signature"])
        except Exception as exc:
            raise ValidatorNodeError("AWS KMS signing failed") from exc
        if not self.verify(resource, payload, signature):
            raise ValidatorNodeError("AWS KMS returned an unverifiable signature")
        return signature

    def verify(self, resource: str, payload: bytes, signature: bytes) -> bool:
        _kms_arn(resource)
        if not isinstance(signature, bytes) or len(signature) != 64:
            return False
        try:
            response = self.client.verify(
                KeyId=resource,
                Message=hashlib.sha256(payload).digest(),
                MessageType="DIGEST",
                Signature=_raw_to_der(signature),
                SigningAlgorithm="ECDSA_SHA_256",
            )
            return response.get("SignatureValid") is True
        except Exception:
            return False


class PrivateVpcPeerTransport:
    """Bounded TCP transport restricted to an exact three-validator allowlist."""

    def __init__(
        self,
        *,
        validator_id: str,
        endpoints: Mapping[str, tuple[str, int]],
        receive_vote: Any,
    ) -> None:
        self.validator_id = _validator_id(validator_id)
        if set(endpoints) != set(sorted(endpoints)) or len(endpoints) != 3:
            raise ValidatorNodeError("peer topology requires exactly 3 validators")
        normalized: dict[str, tuple[str, int]] = {}
        for identity, endpoint in endpoints.items():
            _validator_id(identity)
            if (
                not isinstance(endpoint, tuple)
                or len(endpoint) != 2
                or not isinstance(endpoint[0], str)
                or not endpoint[0]
                or isinstance(endpoint[1], bool)
                or not isinstance(endpoint[1], int)
                or endpoint[1] != 30303
            ):
                raise ValidatorNodeError("peer endpoint must use TCP port 30303")
            normalized[identity] = endpoint
        if self.validator_id not in normalized or not callable(receive_vote):
            raise ValidatorNodeError("local validator and vote receiver are required")
        self.endpoints = normalized
        self.receive_vote = receive_vote
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._server is not None:
            raise ValidatorNodeError("peer transport is already started")
        host, port = self.endpoints[self.validator_id]
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(16)
        server.settimeout(0.5)
        self._server = server
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def broadcast(self, packet: AuthenticatedVote) -> None:
        frame = _vote_frame(packet)
        for identity, endpoint in sorted(self.endpoints.items()):
            if identity == self.validator_id:
                self.receive_vote(packet)
                continue
            try:
                with socket.create_connection(endpoint, timeout=3) as connection:
                    connection.sendall(frame)
            except OSError as exc:
                raise ValidatorNodeError("peer vote delivery failed") from exc

    def _serve(self) -> None:
        assert self._server is not None
        allowed_hosts = {host for identity, (host, _) in self.endpoints.items()
                         if identity != self.validator_id}
        while not self._stop.is_set():
            try:
                connection, address = self._server.accept()
            except (socket.timeout, OSError):
                continue
            with connection:
                if address[0] not in allowed_hosts:
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
                    self.receive_vote(_authenticated_vote(value))
                except (OSError, json.JSONDecodeError, ValidatorNodeError, ValueError):
                    continue


@dataclass(frozen=True)
class AuthenticatedVote:
    """A consensus vote plus an independent peer-transport authentication."""

    chain_id: int
    height: int
    round: int
    block_hash: str
    validator_id: str
    signature: bytes
    peer_signature: bytes

    @property
    def peer_signing_payload(self) -> bytes:
        body = {
            "block_hash": self.block_hash,
            "chain_id": self.chain_id,
            "height": self.height,
            "round": self.round,
            "signature": self.signature.hex(),
            "validator_id": self.validator_id,
        }
        return (
            b"JUNCA_AUTHENTICATED_PEER_VOTE_V1\x00"
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        )


class PublicTestnetConsensus:
    """Three-validator coordinator that commits only authenticated quorum.

    The coordinator does not sign on behalf of peers.  Each vote must carry a
    consensus signature made by the validator's assigned KMS key and a
    separately verified peer-session signature.  With three equal-power
    validators, all three votes are required by the strict >2/3 finality rule.
    """

    def __init__(
        self,
        *,
        store: PersistentStateStore,
        data_dir: str | Path,
        signer_resources: Mapping[str, str],
        consensus_verifier: ConsensusVerifier,
        peer_verifier: PeerVerifier,
    ) -> None:
        if not callable(consensus_verifier) or not callable(peer_verifier):
            raise ValidatorNodeError("consensus and peer verifiers are required")
        expected = tuple(sorted(signer_resources))
        if len(expected) != 3:
            raise ValidatorNodeError("exactly 3 validator signer bindings are required")
        bindings: dict[str, ValidatorSignerBinding] = {}
        for validator_id in expected:
            resource = signer_resources[validator_id]
            if not resource.startswith("arn:aws:kms:"):
                raise ValidatorNodeError(
                    "public testnet validators require assigned AWS KMS signers"
                )
            bindings[validator_id] = ValidatorSignerBinding(
                validator_id=validator_id,
                key_resource="kms://" + resource,
            )
        validators = tuple(Validator(item, 1) for item in expected)
        schedule = ValidatorSetSchedule(
            ValidatorSet(epoch=0, activation_height=0, validators=validators)
        )
        pipeline = NodeExecutionPipeline(
            config=ProtocolConfig(chain_id=store.chain_id),
            pool=TransactionPool(ProtocolConfig(chain_id=store.chain_id)),
            store=store,
            signature_verifier=lambda transaction: bool(transaction.signature),
        )
        journal = ConsensusSigningJournal(
            Path(data_dir) / "consensus-signing.sqlite",
            chain_id=store.chain_id,
        )
        self._resources = dict(signer_resources)
        self._consensus_verifier = consensus_verifier
        self._peer_verifier = peer_verifier
        self._journal = journal
        self.runtime = LiveValidatorRuntime(
            pipeline=pipeline,
            schedule=schedule,
            signer_bindings=bindings,
            signer=lambda *_: (_ for _ in ()).throw(
                ValidatorNodeError("remote peer votes must be submitted explicitly")
            ),
            signature_verifier=self._verify_consensus,
            signing_journal=journal,
        )
        self._accepted_peer_votes: set[str] = set()
        self._last_finalized: FinalizedProposal | None = None

    def close(self) -> None:
        self._journal.close()

    def propose(self, *, round: int = 0) -> ExecutedProposal:
        self._accepted_peer_votes.clear()
        return self.runtime.propose(round=round)

    def submit(self, packet: AuthenticatedVote) -> FinalizedProposal | None:
        if packet.validator_id not in self._resources:
            raise ValidatorNodeError("vote is from an unbound validator")
        try:
            peer_ok = self._peer_verifier(
                packet.validator_id,
                packet.peer_signing_payload,
                packet.peer_signature,
            )
        except Exception as exc:
            raise ValidatorNodeError("peer vote authentication failed") from exc
        if peer_ok is not True:
            raise ValidatorNodeError("peer vote authentication failed")
        vote = FinalityVote(
            chain_id=packet.chain_id,
            height=packet.height,
            round=packet.round,
            block_hash=packet.block_hash,
            validator_id=packet.validator_id,
            signature=packet.signature,
        )
        result = self.runtime.accept_vote(vote)
        self._accepted_peer_votes.add(packet.validator_id)
        if result is not None:
            self._last_finalized = result
        return result

    def evidence(self) -> dict[str, Any]:
        runtime = self.runtime.evidence()
        last = self._last_finalized
        return {
            "schema_version": "junca-public-testnet-consensus-runtime/v1",
            "chain_id": runtime["chain_id"],
            "head_height": runtime["head_height"],
            "pending_height": runtime["pending_height"],
            "authenticated_vote_count": len(self._accepted_peer_votes),
            "required_vote_count": 3,
            "quorum_rule": "strictly-greater-than-two-thirds",
            "last_certificate_hash": (
                None if last is None else last.certificate.certificate_hash
            ),
            "last_certificate": (
                None if last is None else last.certificate.as_evidence()
            ),
            "signer_bindings": [
                {
                    "validator_id": validator_id,
                    "kms_resource_digest": hashlib.sha256(
                        self._resources[validator_id].encode()
                    ).hexdigest(),
                }
                for validator_id in sorted(self._resources)
            ],
            "private_key_material_accepted": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _verify_consensus(
        self, validator_id: str, payload: bytes, signature: bytes
    ) -> bool:
        resource = self._resources.get(validator_id)
        if resource is None:
            return False
        try:
            return (
                self._consensus_verifier(
                    validator_id, resource, payload, signature
                )
                is True
            )
        except Exception:
            return False


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_genesis(*, chain_id: int, validators: Sequence[str]) -> dict[str, Any]:
    """Return the deterministic, zero-allocation public-testnet genesis."""
    if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
        raise ValidatorNodeError("chain_id must be a positive integer")
    normalized = sorted({_validator_id(item) for item in validators})
    if len(normalized) != 3:
        raise ValidatorNodeError("public testnet genesis requires exactly 3 validators")
    identity = {
        "schema_version": GENESIS_SCHEMA,
        "chain_id": chain_id,
        "network": "public-testnet",
        "notice": NETWORK_LABEL,
        "governance": "JAIOS Institutional Governance",
        "validator_ids": normalized,
        "allocations": {},
        "mainnet": False,
        "monetary_value": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    identity["genesis_hash"] = "0x" + hashlib.sha256(canonical_json(identity)).hexdigest()
    return identity


def load_genesis(path: str | Path) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidatorNodeError("unable to read genesis document") from exc
    if not isinstance(document, dict):
        raise ValidatorNodeError("genesis must be a JSON object")
    supplied_hash = document.pop("genesis_hash", None)
    expected_hash = "0x" + hashlib.sha256(canonical_json(document)).hexdigest()
    document["genesis_hash"] = supplied_hash
    if supplied_hash != expected_hash:
        raise ValidatorNodeError("genesis_hash does not match canonical genesis")
    if (
        document.get("schema_version") != GENESIS_SCHEMA
        or document.get("network") != "public-testnet"
        or document.get("notice") != NETWORK_LABEL
        or document.get("mainnet") is not False
        or document.get("monetary_value") is not False
        or document.get("assets_moved") is not False
        or document.get("bridge_activated") is not False
        or document.get("allocations") != {}
    ):
        raise ValidatorNodeError("genesis violates public-testnet safety policy")
    validators = document.get("validator_ids")
    if not isinstance(validators, list) or len(validators) != 3:
        raise ValidatorNodeError("genesis requires exactly 3 validators")
    return document


@dataclass
class NodeState:
    store: PersistentStateStore
    chain_id: int
    genesis_hash: str
    validator_id: str
    signer_resource: str
    started_at: int
    peer_count: int = 0
    consensus: PublicTestnetConsensus | None = None
    kms: AwsKmsSecp256k1Adapter | None = None
    peer_transport: PrivateVpcPeerTransport | None = None
    consensus_lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False
    )

    def evidence(self) -> dict[str, Any]:
        # Return one atomic view of the durable head and in-memory certificate.
        # Without the shared lock, a health read could observe the old head and
        # the new certificate while the peer receiver commits finality.
        with self.consensus_lock:
            head = self.store.head()
            evidence = {
                "status": "healthy",
                "network": NETWORK_LABEL,
                "chain_id": self.chain_id,
                "validator_id": self.validator_id,
                "head_height": head.height,
                "head_hash": head.block_hash,
                "genesis_hash": self.genesis_hash,
                "signer_resource_digest": hashlib.sha256(
                    self.signer_resource.encode()
                ).hexdigest(),
                "private_key_material_accepted": False,
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            }
            if self.consensus is not None:
                evidence["consensus"] = self.consensus.evidence()
            return evidence

    def rpc(self, method: str, params: Any) -> Any:
        if not isinstance(params, list):
            raise ValidatorNodeError("params must be a list")
        head = self.store.head()
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return hex(head.height)
        if method == "net_peerCount":
            return hex(self.peer_count)
        if method == "web3_clientVersion":
            return CLIENT_VERSION
        if method == "eth_getBlockByNumber":
            if params not in (["latest", False], ["latest", True]):
                raise ValidatorNodeError("only the latest block is available")
            return {
                "number": hex(head.height),
                "hash": head.block_hash,
                "parentHash": head.parent_hash,
                "stateRoot": head.state_root,
                "timestamp": hex(self.started_at),
                "transactions": [],
            }
        if method == "junca_health":
            return self.evidence()
        if method == "junca_propose":
            if self.consensus is None:
                raise ValidatorNodeError("consensus runtime is not configured")
            if params not in ([], [0]):
                raise ValidatorNodeError("junca_propose accepts only round zero")
            with self.consensus_lock:
                return self.consensus.propose(round=0).as_evidence()
        if method == "junca_submitVote":
            if self.consensus is None:
                raise ValidatorNodeError("consensus runtime is not configured")
            if len(params) != 1 or not isinstance(params[0], dict):
                raise ValidatorNodeError("junca_submitVote requires one vote object")
            packet = _authenticated_vote(params[0])
            with self.consensus_lock:
                result = self.consensus.submit(packet)
            return {
                "status": "FINALIZED" if result is not None else "VOTE_ACCEPTED",
                "height": packet.height,
                "head_height": self.store.head_height,
                "certificate": (
                    None if result is None else result.certificate.as_evidence()
                ),
            }
        if method == "junca_broadcastVote":
            if (
                self.consensus is None
                or self.kms is None
                or self.peer_transport is None
                or params != []
            ):
                raise ValidatorNodeError("network consensus runtime is not configured")
            # Peer receiver threads and the local JSON-RPC thread share one
            # proposal/finality machine.  Keep proposal selection, KMS signing,
            # and local delivery atomic so concurrent SSM broadcasts cannot
            # create competing local proposals or mutate the machine mid-vote.
            with self.consensus_lock:
                proposal = self.consensus.runtime.pending_proposal
                if proposal is None:
                    proposal = self.consensus.propose()
                unsigned = FinalityVote(
                    chain_id=self.chain_id,
                    height=proposal.height,
                    round=self.consensus.runtime.current_round,
                    block_hash=proposal.block_hash,
                    validator_id=self.validator_id,
                    signature=b"",
                )
                signature = self.kms.sign(
                    self.signer_resource, unsigned.signing_payload
                )
                pending = AuthenticatedVote(
                    chain_id=unsigned.chain_id,
                    height=unsigned.height,
                    round=unsigned.round,
                    block_hash=unsigned.block_hash,
                    validator_id=unsigned.validator_id,
                    signature=signature,
                    peer_signature=b"pending",
                )
                packet = AuthenticatedVote(
                    **{
                        **pending.__dict__,
                        "peer_signature": self.kms.sign(
                            self.signer_resource, pending.peer_signing_payload
                        ),
                    }
                )
                self.peer_transport.broadcast(packet)
            return {"status": "BROADCAST", "height": proposal.height}
        raise ValidatorNodeError("method is not allowlisted")


def make_handler(state: NodeState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "JUNCAValidator/1"

        def do_GET(self) -> None:
            if self.path not in ("/health", "/healthz"):
                self.send_error(404)
                return
            self._json(200, state.evidence())

        def do_POST(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValidatorNodeError("invalid request size")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValidatorNodeError("invalid JSON-RPC envelope")
                result = state.rpc(str(request.get("method", "")), request.get("params"))
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
            except (json.JSONDecodeError, ValidatorNodeError) as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": str(exc)},
                }
            self._json(200, response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: int, body: Mapping[str, Any]) -> None:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def initialize_state(
    genesis: Mapping[str, Any], data_dir: str | Path, validator_id: str, signer: str
) -> NodeState:
    chain_id = genesis.get("chain_id")
    if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
        raise ValidatorNodeError("genesis chain_id is invalid")
    validator_id = _validator_id(validator_id)
    if validator_id not in genesis["validator_ids"]:
        raise ValidatorNodeError("validator_id is not in genesis validator set")
    if not signer.startswith(("arn:aws:kms:", "kms://", "hsm://")):
        raise ValidatorNodeError("signer-resource must be a KMS/HSM identifier")
    target = Path(data_dir)
    target.mkdir(mode=0o750, parents=True, exist_ok=True)
    store = PersistentStateStore(target / "state.sqlite", chain_id=chain_id)
    config = ProtocolConfig(chain_id=chain_id)
    store.initialize_genesis(
        block_hash=str(genesis["genesis_hash"]),
        accounts={},
        base_fee_per_gas=config.initial_base_fee,
    )
    return NodeState(
        store=store,
        chain_id=chain_id,
        genesis_hash=str(genesis["genesis_hash"]),
        validator_id=validator_id,
        signer_resource=signer,
        started_at=int(datetime.now(timezone.utc).timestamp()),
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="junca-chain-node")
    result.add_argument("--genesis", required=True)
    result.add_argument("--data-dir", default="/var/lib/junca")
    result.add_argument("--validator-id", default=os.getenv("VALIDATOR_ID", ""))
    result.add_argument("--signer-resource", default=os.getenv("SIGNER_RESOURCE_ARN", ""))
    result.add_argument("--http.addr", dest="http_addr", default="127.0.0.1")
    result.add_argument("--http.port", dest="http_port", type=int, default=8545)
    # Compatibility flags are accepted but do not weaken the read-only boundary.
    result.add_argument("--config")
    result.add_argument("--http.api")
    result.add_argument("--mine", action="store_true")
    result.add_argument(
        "--validator-signer",
        action="append",
        default=_environment_assignments("VALIDATOR_SIGNER_BINDINGS"),
        help="validator-id=AWS-KMS-key-ARN; exactly three required for network mode",
    )
    result.add_argument(
        "--peer",
        action="append",
        default=_environment_assignments("VALIDATOR_PEER_ENDPOINTS"),
        help="validator-id=private-ip:30303; exactly three required for network mode",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.http_port <= 65535:
        raise ValidatorNodeError("http.port is invalid")
    genesis = load_genesis(args.genesis)
    state = initialize_state(
        genesis, args.data_dir, args.validator_id, args.signer_resource
    )
    transport: PrivateVpcPeerTransport | None = None
    if args.validator_signer or args.peer:
        resources = _parse_assignments(args.validator_signer, "validator signer")
        endpoints = _parse_peer_endpoints(args.peer)
        expected_validators = set(genesis["validator_ids"])
        if set(resources) != expected_validators or set(endpoints) != expected_validators:
            raise ValidatorNodeError(
                "network bindings must exactly match the genesis validator set"
            )
        if resources.get(args.validator_id) != args.signer_resource:
            raise ValidatorNodeError(
                "local signer must match the assigned genesis validator binding"
            )
        kms = AwsKmsSecp256k1Adapter()
        consensus = PublicTestnetConsensus(
            store=state.store,
            data_dir=args.data_dir,
            signer_resources=resources,
            consensus_verifier=lambda _id, resource, payload, signature: kms.verify(
                resource, payload, signature
            ),
            peer_verifier=lambda validator_id, payload, signature: kms.verify(
                resources[validator_id], payload, signature
            ),
        )

        def receive(packet: AuthenticatedVote) -> None:
            with state.consensus_lock:
                if consensus.runtime.pending_proposal is None:
                    consensus.propose(round=packet.round)
                consensus.submit(packet)

        transport = PrivateVpcPeerTransport(
            validator_id=args.validator_id,
            endpoints=endpoints,
            receive_vote=receive,
        )
        state.consensus = consensus
        state.kms = kms
        state.peer_transport = transport
        transport.start()
    server = ThreadingHTTPServer((args.http_addr, args.http_port), make_handler(state))

    def terminate(*_: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    finally:
        if transport is not None:
            transport.close()
        if state.consensus is not None:
            state.consensus.close()
        state.store.close()
        server.server_close()
    return 0


def _validator_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValidatorNodeError("validator identifier is invalid")
    if not all(character.isalnum() or character in "-_" for character in value):
        raise ValidatorNodeError("validator identifier is invalid")
    return value


def _environment_assignments(name: str) -> list[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    result = [item.strip() for item in value.split(",")]
    if any(not item for item in result):
        raise ValidatorNodeError(f"{name} contains an empty assignment")
    return result


def _parse_assignments(values: Sequence[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise ValidatorNodeError(f"{label} assignment is invalid")
        identity, assigned = value.split("=", 1)
        identity = _validator_id(identity)
        if identity in result or not assigned:
            raise ValidatorNodeError(f"{label} assignment is invalid")
        result[identity] = assigned
    if len(result) != 3:
        raise ValidatorNodeError(f"{label} requires exactly 3 assignments")
    return result


def _parse_peer_endpoints(values: Sequence[str]) -> dict[str, tuple[str, int]]:
    assignments = _parse_assignments(values, "peer")
    result: dict[str, tuple[str, int]] = {}
    for identity, endpoint in assignments.items():
        try:
            host, port_text = endpoint.rsplit(":", 1)
            port = int(port_text)
        except (ValueError, TypeError) as exc:
            raise ValidatorNodeError("peer endpoint is invalid") from exc
        if not host or port != 30303:
            raise ValidatorNodeError("peer endpoint must use port 30303")
        result[identity] = (host, port)
    return result


def _authenticated_vote(value: Mapping[str, Any]) -> AuthenticatedVote:
    required = {
        "chain_id",
        "height",
        "round",
        "block_hash",
        "validator_id",
        "signature",
        "peer_signature",
    }
    if set(value) != required:
        raise ValidatorNodeError("authenticated vote fields are invalid")
    numeric = (value["chain_id"], value["height"], value["round"])
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in numeric
    ) or value["chain_id"] == 0:
        raise ValidatorNodeError("authenticated vote numeric identity is invalid")
    if (
        not isinstance(value["block_hash"], str)
        or len(value["block_hash"]) != 66
        or not value["block_hash"].startswith("0x")
    ):
        raise ValidatorNodeError("authenticated vote block hash is invalid")
    try:
        signature = bytes.fromhex(value["signature"])
        peer_signature = bytes.fromhex(value["peer_signature"])
    except (TypeError, ValueError) as exc:
        raise ValidatorNodeError("authenticated vote signatures are invalid") from exc
    if not signature or not peer_signature:
        raise ValidatorNodeError("authenticated vote signatures are invalid")
    return AuthenticatedVote(
        chain_id=value["chain_id"],
        height=value["height"],
        round=value["round"],
        block_hash=value["block_hash"],
        validator_id=_validator_id(value["validator_id"]),
        signature=signature,
        peer_signature=peer_signature,
    )


def _vote_frame(packet: AuthenticatedVote) -> bytes:
    body = canonical_json(
        {
            "chain_id": packet.chain_id,
            "height": packet.height,
            "round": packet.round,
            "block_hash": packet.block_hash,
            "validator_id": packet.validator_id,
            "signature": packet.signature.hex(),
            "peer_signature": packet.peer_signature.hex(),
        }
    )
    if len(body) > 16_384:
        raise ValidatorNodeError("peer vote frame exceeds size boundary")
    return struct.pack(">I", len(body)) + body


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ValidatorNodeError("peer vote frame is truncated")
        chunks.extend(chunk)
    return bytes(chunks)


def _kms_arn(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("arn:aws:kms:")
        or ":key/" not in value
        or len(value) > 512
    ):
        raise ValidatorNodeError("AWS KMS key ARN is invalid")
    return value


def _der_to_raw(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) < 8 or value[0] != 0x30:
        raise ValidatorNodeError("AWS KMS signature DER is invalid")
    index = 2
    if value[1] & 0x80:
        count = value[1] & 0x7F
        index = 2 + count
    if index >= len(value) or value[index] != 0x02:
        raise ValidatorNodeError("AWS KMS signature DER is invalid")
    r_length = value[index + 1]
    r = value[index + 2:index + 2 + r_length]
    index += 2 + r_length
    if index + 2 > len(value) or value[index] != 0x02:
        raise ValidatorNodeError("AWS KMS signature DER is invalid")
    s_length = value[index + 1]
    s = value[index + 2:index + 2 + s_length]
    if index + 2 + s_length != len(value):
        raise ValidatorNodeError("AWS KMS signature DER is invalid")
    r = r.lstrip(b"\x00")
    s = s.lstrip(b"\x00")
    if not 1 <= len(r) <= 32 or not 1 <= len(s) <= 32:
        raise ValidatorNodeError("AWS KMS signature scalar is invalid")
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def _raw_to_der(value: bytes) -> bytes:
    if len(value) != 64:
        raise ValidatorNodeError("consensus signature must be 64 bytes")

    def integer(scalar: bytes) -> bytes:
        scalar = scalar.lstrip(b"\x00") or b"\x00"
        if scalar[0] & 0x80:
            scalar = b"\x00" + scalar
        return b"\x02" + bytes([len(scalar)]) + scalar

    body = integer(value[:32]) + integer(value[32:])
    return b"\x30" + bytes([len(body)]) + body


if __name__ == "__main__":
    raise SystemExit(main())
