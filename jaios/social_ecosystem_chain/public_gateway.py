"""Fail-closed public gateway for the JUNCA Public Testnet validator runtime."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .explorer_page import EXPLORER_DOCUMENT


NOTICE = "Public Testnet / No Monetary Value"
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
    ) -> None:
        self.upstream = validate_upstream(upstream)
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
        healthy = evidence.get("status") == "healthy"
        certificate = (
            evidence.get("consensus", {}).get("last_certificate")
            if isinstance(evidence.get("consensus"), Mapping)
            else None
        )
        finalized = (
            isinstance(certificate, Mapping)
            and certificate.get("finality_status") == "FINALIZED"
            and certificate.get("height") == evidence.get("head_height")
            and certificate.get("block_hash") == evidence.get("head_hash")
        )
        body = {
            "schema_version": "junca-public-gateway-health/v1",
            "status": "healthy" if healthy else "unhealthy",
            "notice": NOTICE,
            "validator": {
                "head_height": evidence.get("head_height"),
                "head_hash": evidence.get("head_hash"),
            },
            "read_only": True,
            "finalized_only": True,
            "signed_power": certificate.get("signed_power") if finalized else None,
            "total_power": certificate.get("total_power") if finalized else None,
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
        finalized = (
            isinstance(certificate, Mapping)
            and certificate.get("finality_status") == "FINALIZED"
            and certificate.get("height") == evidence.get("head_height")
            and certificate.get("block_hash") == evidence.get("head_hash")
        )
        body = {
            "schema_version": "junca-public-explorer/v1",
            "notice": NOTICE,
            "finalized_only": True,
            "read_only": True,
            "status": "ready" if finalized else "syncing",
            "head": (
                {
                    "height": evidence.get("head_height"),
                    "hash": evidence.get("head_hash"),
                    "certificate_hash": evidence.get("consensus", {}).get(
                        "last_certificate_hash"
                    ),
                    "signed_power": certificate.get("signed_power"),
                    "total_power": certificate.get("total_power"),
                }
                if finalized
                else None
            ),
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        return (200 if finalized else 503), body

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

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=(), payment=()",
            )
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'",
            )
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
    gateway = PublicGateway(args.upstream)
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
