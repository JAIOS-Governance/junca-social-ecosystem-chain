"""Fail-closed public gateway for the JUNCA Public Testnet validator runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .explorer_page import EXPLORER_DOCUMENT


NOTICE = "Public Testnet / No Monetary Value"
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX_DIGEST = re.compile(r"^0x[0-9a-f]{64}$")
HEX_SIGNATURE = re.compile(r"^[0-9a-f]{128}$")
CERTIFICATE_PROOF_SCHEMA = "junca-public-finality-certificate-proof/v1"
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
ALLOWED_METHODS = frozenset(
    {
        "eth_blockNumber",
        "eth_chainId",
        "eth_getBlockByNumber",
        "net_peerCount",
        "web3_clientVersion",
    }
)
MAX_REQUEST_BYTES = 1_000_000
LOGO_PATH = Path(__file__).with_name("assets") / "junca-chain-logo-gold-on-navy.png"
ICON_PATH = Path(__file__).with_name("assets") / "junca-explorer-icon-gold-on-navy.png"
EXPLORER_MANIFEST = {
    "id": "/",
    "name": "JUNCA Social Ecosystem Chain Public Explorer",
    "short_name": "JUNCA Explorer",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#071827",
    "theme_color": "#071827",
    "icons": [
        {
            "src": "/explorer-icon.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        }
    ],
}


class PublicGatewayError(ValueError):
    """Raised when a request violates the public read-only boundary."""


@dataclass(frozen=True)
class UpstreamResponse:
    status: int
    body: Mapping[str, Any]


Transport = Callable[[str, Mapping[str, Any]], UpstreamResponse]


def validate_upstream(url: str) -> str:
    """Require an exact loopback HTTP upstream; validators remain non-public."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise PublicGatewayError(
            "upstream must be a loopback HTTP validator endpoint"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise PublicGatewayError("upstream port is invalid") from exc
    if port is None:
        raise PublicGatewayError("upstream must include an explicit port")
    return f"http://[{parsed.hostname}]:{port}/" if ":" in parsed.hostname else (
        f"http://{parsed.hostname}:{port}/"
    )


def http_transport(upstream: str, payload: Mapping[str, Any]) -> UpstreamResponse:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        upstream,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            raw = response.read(MAX_REQUEST_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        raw = exc.read(MAX_REQUEST_BYTES + 1)
        status = exc.code
    except (OSError, URLError) as exc:
        raise PublicGatewayError("validator upstream is unavailable") from exc
    if len(raw) > MAX_REQUEST_BYTES:
        raise PublicGatewayError("validator upstream response is too large")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicGatewayError("validator upstream returned invalid JSON") from exc
    if not isinstance(body, Mapping):
        raise PublicGatewayError("validator upstream returned an invalid envelope")
    return UpstreamResponse(status=status, body=body)


class PublicGateway:
    """Read-only RPC proxy plus health and finalized-only explorer views."""

    def __init__(
        self,
        upstream: str = "http://127.0.0.1:8545/",
        *,
        transport: Transport | None = None,
        runtime_artifact_commit: str | None = None,
        genesis_sha256: str | None = None,
        node_artifact_sha256: str | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.upstream = validate_upstream(upstream)
        if runtime_artifact_commit is not None and not COMMIT_SHA.fullmatch(
            runtime_artifact_commit
        ):
            raise PublicGatewayError(
                "runtime artifact commit must be a lowercase 40-character SHA"
            )
        self.runtime_artifact_commit = runtime_artifact_commit
        for label, digest in (
            ("genesis SHA-256", genesis_sha256),
            ("node artifact SHA-256", node_artifact_sha256),
        ):
            if digest is not None and not DIGEST_SHA256.fullmatch(digest):
                raise PublicGatewayError(
                    f"{label} must be a lowercase 64-character digest"
                )
        self.genesis_sha256 = genesis_sha256
        self.node_artifact_sha256 = node_artifact_sha256
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).timestamp()
        )
        self._transport = transport or (
            lambda _upstream, payload: http_transport(self.upstream, payload)
        )

    def rpc(self, request: object) -> tuple[int, Mapping[str, Any]]:
        request_id: Any = None
        if not isinstance(request, Mapping):
            return 400, self._rpc_error(None, -32600, "invalid request")
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return 400, self._rpc_error(request_id, -32600, "invalid request")
        method = request.get("method")
        params = request.get("params")
        if not isinstance(method, str) or params is None:
            return 400, self._rpc_error(request_id, -32600, "invalid request")
        if method not in ALLOWED_METHODS:
            return 403, self._rpc_error(request_id, -32601, "method not found")

        upstream = self._transport(
            self.upstream,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
        )
        if upstream.status != 200:
            raise PublicGatewayError("validator upstream rejected the request")
        body = upstream.body
        if body.get("jsonrpc") != "2.0" or body.get("id") != request_id:
            raise PublicGatewayError("validator upstream envelope mismatch")
        if ("result" in body) == ("error" in body):
            raise PublicGatewayError("validator upstream response is ambiguous")
        return 200, body

    def health(self) -> tuple[int, Mapping[str, Any]]:
        evidence = self._validator_health()
        peer_count = self._hex_quantity(
            self._public_rpc_result("net_peerCount", [])
        )
        healthy = self._validator_is_ready(evidence, peer_count)
        body = {
            "schema_version": "junca-public-gateway-health/v1",
            "status": "healthy" if healthy else "unhealthy",
            "notice": NOTICE,
            "validator": {
                "head_height": evidence.get("head_height"),
                "head_hash": evidence.get("head_hash"),
                "head_timestamp": evidence.get("head_timestamp"),
                "peer_count": peer_count,
            },
            "read_only": True,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        return (200 if healthy else 503), body

    def explorer(self) -> tuple[int, Mapping[str, Any]]:
        evidence = self._validator_health()
        certificate = (
            evidence.get("consensus", {}).get("last_certificate")
            if isinstance(evidence.get("consensus"), Mapping)
            else None
        )
        certificate_proof = (
            evidence.get("consensus", {}).get(
                "last_certificate_proof"
            )
            if isinstance(evidence.get("consensus"), Mapping)
            else None
        )
        network = self._public_network_metadata()
        validator_ready = self._validator_is_ready(
            evidence,
            network.get("peer_count"),
        )
        block = (
            self._finalized_block_metadata(
                certificate.get("height"), certificate.get("block_hash")
            )
            if validator_ready and isinstance(certificate, Mapping)
            else None
        )
        finalized = (
            validator_ready
            and block is not None
            and block.get("timestamp")
            == hex(evidence.get("head_timestamp"))
        )
        body = {
            "schema_version": "junca-public-explorer/v5",
            "notice": NOTICE,
            "runtime_artifact": {
                "source_commit": self.runtime_artifact_commit,
                "genesis_sha256": self.genesis_sha256,
                "node_artifact_sha256": self.node_artifact_sha256,
                "evidence_source": "approved immutable validator runtime",
            },
            "finalized_only": True,
            "status": "ready" if finalized else "syncing",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "network": network,
            "head": (
                {
                    "height": evidence.get("head_height"),
                    "hash": evidence.get("head_hash"),
                    "certificate_hash": evidence.get("consensus", {}).get(
                        "last_certificate_hash"
                    ),
                    "signed_power": certificate.get("signed_power"),
                    "total_power": certificate.get("total_power"),
                    "certificate": certificate_proof,
                    "timestamp": block.get("timestamp") if block else None,
                    "parent_hash": block.get("parent_hash") if block else None,
                    "state_root": block.get("state_root") if block else None,
                    "transaction_count": (
                        block.get("transaction_count") if block else None
                    ),
                }
                if finalized
                else None
            ),
            "read_only": True,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        return (200 if finalized else 503), body

    def _validator_is_ready(
        self,
        evidence: Mapping[str, Any],
        rpc_peer_count: object,
    ) -> bool:
        head_height = evidence.get("head_height")
        head_hash = evidence.get("head_hash")
        head_timestamp = evidence.get("head_timestamp")
        interval = evidence.get("block_interval_seconds")
        epoch = evidence.get("slot_epoch_seconds")
        last_slot = evidence.get(
            "automatic_finality_last_successful_slot"
        )
        last_height = evidence.get(
            "automatic_finality_last_successful_height"
        )
        consensus = evidence.get("consensus")
        certificate = (
            consensus.get("last_certificate")
            if isinstance(consensus, Mapping)
            else None
        )
        certificate_hash = (
            consensus.get("last_certificate_hash")
            if isinstance(consensus, Mapping)
            else None
        )
        certificate_proof = (
            consensus.get("last_certificate_proof")
            if isinstance(consensus, Mapping)
            else None
        )
        health_gates = evidence.get("health_gates")
        now = int(self._clock())
        fresh_window = (
            max(120, interval * 3)
            if isinstance(interval, int)
            and not isinstance(interval, bool)
            else -1
        )
        return (
            evidence.get("status") == "healthy"
            and evidence.get("peer_count") == 2
            and rpc_peer_count == 2
            and isinstance(head_height, int)
            and not isinstance(head_height, bool)
            and head_height >= 1
            and isinstance(head_hash, str)
            and HEX_DIGEST.fullmatch(head_hash) is not None
            and isinstance(head_timestamp, int)
            and not isinstance(head_timestamp, bool)
            and 0 <= now - head_timestamp <= fresh_window
            and isinstance(interval, int)
            and not isinstance(interval, bool)
            and 5 <= interval <= 3600
            and isinstance(epoch, int)
            and not isinstance(epoch, bool)
            and epoch > 0
            and isinstance(last_slot, int)
            and not isinstance(last_slot, bool)
            and last_slot > 0
            and epoch + (last_slot * interval) == head_timestamp
            and last_height == head_height
            and evidence.get("automatic_finality_enabled") is True
            and evidence.get("automatic_finality_loop_running") is True
            and isinstance(consensus, Mapping)
            and consensus.get("head_height") == head_height
            and consensus.get("required_vote_count") == 3
            and isinstance(certificate, Mapping)
            and certificate.get("finality_status") == "FINALIZED"
            and certificate.get("height") == head_height
            and certificate.get("block_hash") == head_hash
            and certificate.get("signed_power") == 3
            and certificate.get("total_power") == 3
            and isinstance(certificate_hash, str)
            and HEX_DIGEST.fullmatch(certificate_hash) is not None
            and certificate.get("certificate_hash") == certificate_hash
            and self._certificate_proof_is_complete(
                certificate_proof,
                certificate,
            )
            and isinstance(health_gates, Mapping)
            and set(health_gates)
            == {
                "authenticated_peer_quorum",
                "automatic_finality",
                "current_three_of_three_certificate",
                "fresh_finalized_head",
            }
            and all(value is True for value in health_gates.values())
            and evidence.get("mainnet_changed") is False
            and evidence.get("assets_moved") is False
            and evidence.get("bridge_activated") is False
        )

    @staticmethod
    def _certificate_proof_is_complete(
        proof: object,
        certificate: Mapping[str, Any],
    ) -> bool:
        if (
            not isinstance(proof, Mapping)
            or set(proof) != {"schema_version", "certificate", "votes"}
            or proof.get("schema_version") != CERTIFICATE_PROOF_SCHEMA
            or proof.get("certificate") != certificate
            or certificate.get("validator_ids") != list(VALIDATOR_IDS)
        ):
            return False
        vote_hashes = certificate.get("vote_hashes")
        votes = proof.get("votes")
        if (
            not isinstance(vote_hashes, list)
            or len(vote_hashes) != 3
            or len(set(vote_hashes)) != 3
            or any(
                not isinstance(item, str)
                or HEX_DIGEST.fullmatch(item) is None
                for item in vote_hashes
            )
            or not isinstance(votes, list)
            or len(votes) != 3
        ):
            return False
        for validator_id, vote in zip(VALIDATOR_IDS, votes):
            if (
                not isinstance(vote, Mapping)
                or set(vote)
                != {
                    "chain_id",
                    "height",
                    "round",
                    "block_hash",
                    "validator_id",
                    "signature",
                }
                or vote.get("chain_id") != certificate.get("chain_id")
                or vote.get("height") != certificate.get("height")
                or vote.get("round") != certificate.get("round")
                or vote.get("block_hash") != certificate.get("block_hash")
                or vote.get("validator_id") != validator_id
                or not isinstance(vote.get("signature"), str)
                or HEX_SIGNATURE.fullmatch(vote["signature"]) is None
            ):
                return False
        return True

    def explorer_html(self) -> tuple[int, str]:
        status, _evidence = self.explorer()
        return status, EXPLORER_DOCUMENT

    def _validator_health(self) -> Mapping[str, Any]:
        response = self._transport(
            self.upstream,
            {"jsonrpc": "2.0", "id": "gateway-health", "method": "junca_health", "params": []},
        )
        if response.status != 200:
            raise PublicGatewayError("validator health upstream failed")
        body = response.body
        result = body.get("result")
        if (
            body.get("jsonrpc") != "2.0"
            or body.get("id") != "gateway-health"
            or not isinstance(result, Mapping)
        ):
            raise PublicGatewayError("validator health envelope is invalid")
        return result

    def _public_network_metadata(self) -> Mapping[str, Any]:
        chain_id = self._public_rpc_result("eth_chainId", [])
        peer_count = self._public_rpc_result("net_peerCount", [])
        client_version = self._public_rpc_result("web3_clientVersion", [])
        return {
            "chain_id": chain_id if isinstance(chain_id, str) else None,
            "chain_id_decimal": self._hex_quantity(chain_id),
            "client_version": (
                client_version if isinstance(client_version, str) else None
            ),
            "peer_count": self._hex_quantity(peer_count),
            "peer_count_hex": peer_count if isinstance(peer_count, str) else None,
        }

    def _finalized_block_metadata(
        self, height: object, expected_hash: object
    ) -> Mapping[str, Any] | None:
        if not isinstance(height, int) or height < 0 or not isinstance(expected_hash, str):
            return None
        block = self._public_rpc_result(
            "eth_getBlockByNumber", ["latest", False]
        )
        if (
            not isinstance(block, Mapping)
            or block.get("number") != hex(height)
            or block.get("hash") != expected_hash
        ):
            return None
        transactions = block.get("transactions")
        return {
            "timestamp": block.get("timestamp") if isinstance(block.get("timestamp"), str) else None,
            "parent_hash": block.get("parentHash") if isinstance(block.get("parentHash"), str) else None,
            "state_root": block.get("stateRoot") if isinstance(block.get("stateRoot"), str) else None,
            "transaction_count": (
                len(transactions) if isinstance(transactions, Sequence)
                and not isinstance(transactions, (str, bytes, bytearray)) else None
            ),
        }

    def _public_rpc_result(self, method: str, params: Sequence[object]) -> object:
        response = self._transport(
            self.upstream,
            {
                "jsonrpc": "2.0",
                "id": f"gateway-explorer-{method}",
                "method": method,
                "params": list(params),
            },
        )
        body = response.body
        if (
            response.status != 200
            or body.get("jsonrpc") != "2.0"
            or body.get("id") != f"gateway-explorer-{method}"
            or ("result" in body) == ("error" in body)
        ):
            return None
        return body.get("result")

    @staticmethod
    def _hex_quantity(value: object) -> int | None:
        if not isinstance(value, str) or not value.startswith("0x"):
            return None
        try:
            parsed = int(value, 16)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _rpc_error(request_id: Any, code: int, message: str) -> Mapping[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def make_handler(gateway: PublicGateway) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "JUNCAPublicGateway/1"

        def do_GET(self) -> None:
            try:
                if self.path in {"/health", "/healthz"}:
                    status, body = gateway.health()
                    self._json(status, body)
                elif self.path in {"/explorer.json"}:
                    status, body = gateway.explorer()
                    self._json(status, body)
                elif self.path in {"/", "/explorer"}:
                    status, body = gateway.explorer_html()
                    self._send(status, "text/html; charset=utf-8", body.encode())
                elif self.path == "/junca-chain-logo.png":
                    self._send(200, "image/png", LOGO_PATH.read_bytes(), cache=True)
                elif self.path == "/explorer-icon.png":
                    self._send(200, "image/png", ICON_PATH.read_bytes(), cache=True)
                elif self.path == "/manifest.webmanifest":
                    encoded = json.dumps(
                        EXPLORER_MANIFEST, sort_keys=True, separators=(",", ":")
                    ).encode()
                    self._send(200, "application/manifest+json", encoded)
                else:
                    self.send_error(404)
            except PublicGatewayError:
                self._json(503, {"status": "unavailable", "notice": NOTICE})

        def do_POST(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise PublicGatewayError("invalid request size")
                payload = json.loads(self.rfile.read(length))
                status, body = gateway.rpc(payload)
                self._json(status, body)
            except (ValueError, json.JSONDecodeError):
                self._json(
                    400, PublicGateway._rpc_error(None, -32600, "invalid request")
                )
            except PublicGatewayError:
                self._json(
                    503,
                    PublicGateway._rpc_error(
                        None, -32000, "validator upstream unavailable"
                    ),
                )

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: int, body: Mapping[str, Any]) -> None:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            self._send(status, "application/json", encoded)

        def _send(
            self, status: int, content_type: str, body: bytes, *, cache: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Cache-Control",
                "public, max-age=86400, immutable" if cache else "no-store",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="junca-public-gateway")
    result.add_argument("--upstream", default="http://127.0.0.1:8545/")
    result.add_argument("--http.addr", dest="http_addr", default="127.0.0.1")
    result.add_argument("--http.port", dest="http_port", type=int, default=8080)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.http_port <= 65535:
        raise PublicGatewayError("http.port is invalid")
    gateway = PublicGateway(
        args.upstream,
        runtime_artifact_commit=os.environ.get("JUNCA_RUNTIME_ARTIFACT_COMMIT"),
        genesis_sha256=os.environ.get("JUNCA_GENESIS_SHA256"),
        node_artifact_sha256=os.environ.get("JUNCA_NODE_ARTIFACT_SHA256"),
    )
    server = ThreadingHTTPServer(
        (args.http_addr, args.http_port), make_handler(gateway)
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
