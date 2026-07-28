#!/usr/bin/env python3
"""Vendor-neutral Prometheus exporter for JUNCA validator health evidence."""

from __future__ import annotations

from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import time
from typing import Any, Mapping, Sequence
from urllib.request import Request, urlopen


class MetricsError(ValueError):
    """Raised when validator evidence cannot be represented safely."""


def metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def numeric(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsError(f"{label} must be numeric")
    if value < 0:
        raise MetricsError(f"{label} must not be negative")
    return value


def render_metrics(
    snapshots: Mapping[str, Mapping[str, Any]], *, observed_at: float
) -> str:
    lines = [
        "# HELP junca_validator_up Validator health endpoint was read successfully.",
        "# TYPE junca_validator_up gauge",
        "# HELP junca_validator_finalized_height Durable finalized head height.",
        "# TYPE junca_validator_finalized_height gauge",
        "# HELP junca_validator_peer_count Validator peer count.",
        "# TYPE junca_validator_peer_count gauge",
        "# HELP junca_validator_authenticated_vote_count Authenticated votes for the current proposal.",
        "# TYPE junca_validator_authenticated_vote_count gauge",
        "# HELP junca_validator_required_vote_count Required votes for strict finality.",
        "# TYPE junca_validator_required_vote_count gauge",
        "# HELP junca_validator_recovery_required Validator reports recovery-required state.",
        "# TYPE junca_validator_recovery_required gauge",
        "# HELP junca_validator_evidence_timestamp_seconds Export observation time.",
        "# TYPE junca_validator_evidence_timestamp_seconds gauge",
        "# HELP junca_network_finalized_height_min Minimum finalized height across validators.",
        "# TYPE junca_network_finalized_height_min gauge",
        "# HELP junca_network_finalized_height_max Maximum finalized height across validators.",
        "# TYPE junca_network_finalized_height_max gauge",
        "# HELP junca_network_height_divergence Difference between maximum and minimum finalized height.",
        "# TYPE junca_network_height_divergence gauge",
        "# HELP junca_network_certificate_converged All available validators report one certificate hash.",
        "# TYPE junca_network_certificate_converged gauge",
        "# HELP junca_network_safety_boundary Safety flags remain unchanged.",
        "# TYPE junca_network_safety_boundary gauge",
    ]
    heights: list[int] = []
    certificates: set[str] = set()
    safety_ok = True

    for validator_id in sorted(snapshots):
        value = snapshots[validator_id]
        if not isinstance(value, Mapping):
            raise MetricsError("validator snapshot must be an object")
        if value.get("validator_id") != validator_id:
            raise MetricsError("validator identity does not match endpoint allocation")
        height = int(numeric(value.get("head_height"), "head_height"))
        peer_count = int(numeric(value.get("peer_count", 0), "peer_count"))
        consensus = value.get("consensus")
        if consensus is None:
            consensus = {}
        if not isinstance(consensus, Mapping):
            raise MetricsError("consensus evidence must be an object")
        vote_count = int(
            numeric(consensus.get("authenticated_vote_count", 0), "authenticated_vote_count")
        )
        required_votes = int(
            numeric(consensus.get("required_vote_count", 3), "required_vote_count")
        )
        certificate = consensus.get("last_certificate_hash")
        if certificate:
            if not isinstance(certificate, str):
                raise MetricsError("certificate hash must be a string")
            certificates.add(certificate.lower())
        recovery_required = 1 if value.get("status") == "recovery_required" else 0
        label = metric_label(validator_id)
        lines.extend(
            [
                f'junca_validator_up{{validator="{label}"}} 1',
                f'junca_validator_finalized_height{{validator="{label}"}} {height}',
                f'junca_validator_peer_count{{validator="{label}"}} {peer_count}',
                f'junca_validator_authenticated_vote_count{{validator="{label}"}} {vote_count}',
                f'junca_validator_required_vote_count{{validator="{label}"}} {required_votes}',
                f'junca_validator_recovery_required{{validator="{label}"}} {recovery_required}',
                f'junca_validator_evidence_timestamp_seconds{{validator="{label}"}} {observed_at:.3f}',
            ]
        )
        heights.append(height)
        for field in ("mainnet_changed", "assets_moved", "bridge_activated"):
            if value.get(field) is not False:
                safety_ok = False

    if not heights:
        raise MetricsError("at least one validator snapshot is required")
    minimum = min(heights)
    maximum = max(heights)
    lines.extend(
        [
            f"junca_network_finalized_height_min {minimum}",
            f"junca_network_finalized_height_max {maximum}",
            f"junca_network_height_divergence {maximum - minimum}",
            f"junca_network_certificate_converged {1 if len(certificates) <= 1 else 0}",
            f'junca_network_safety_boundary{{boundary="mainnet_changed_false"}} {1 if safety_ok else 0}',
            f'junca_network_safety_boundary{{boundary="assets_moved_false"}} {1 if safety_ok else 0}',
            f'junca_network_safety_boundary{{boundary="bridge_activated_false"}} {1 if safety_ok else 0}',
        ]
    )
    return "\n".join(lines) + "\n"


def read_snapshot(url: str, *, timeout: int) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "JUNCA-Observability/1"},
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read(1_000_001)
        if response.status != 200 or len(body) > 1_000_000:
            raise MetricsError("validator health response is unavailable or oversized")
    value = json.loads(body)
    if not isinstance(value, Mapping):
        raise MetricsError("validator health response must be an object")
    return value


def endpoint_assignments(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for assignment in value.split(","):
        assignment = assignment.strip()
        if not assignment or "=" not in assignment:
            raise MetricsError("validator endpoint assignment is invalid")
        validator_id, url = assignment.split("=", 1)
        if validator_id in result or not validator_id or not url.startswith("http://"):
            raise MetricsError("validator endpoint assignment is invalid")
        result[validator_id] = url
    if len(result) != 3:
        raise MetricsError("exactly three validator endpoints are required")
    return result


class ExporterState:
    def __init__(self, endpoints: Mapping[str, str], *, timeout: int) -> None:
        self.endpoints = dict(endpoints)
        self.timeout = timeout

    def metrics(self) -> str:
        observed_at = time.time()
        snapshots = {
            validator_id: read_snapshot(url, timeout=self.timeout)
            for validator_id, url in sorted(self.endpoints.items())
        }
        return render_metrics(snapshots, observed_at=observed_at)


def handler(state: ExporterState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send(200, "text/plain; charset=utf-8", b"ok\n")
                return
            if self.path != "/metrics":
                self._send(404, "text/plain; charset=utf-8", b"not found\n")
                return
            try:
                body = state.metrics().encode("utf-8")
                self._send(200, "text/plain; version=0.0.4; charset=utf-8", body)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                body = (f"# exporter error: {type(exc).__name__}\n").encode("utf-8")
                self._send(503, "text/plain; charset=utf-8", body)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def parser() -> ArgumentParser:
    result = ArgumentParser()
    result.add_argument("--addr", default="0.0.0.0")
    result.add_argument("--port", type=int, default=9108)
    result.add_argument("--timeout", type=int, default=3)
    result.add_argument(
        "--endpoints",
        default=os.getenv(
            "JUNCA_VALIDATOR_HEALTH_ENDPOINTS",
            "validator-01=http://172.30.0.11:8545/health,"
            "validator-02=http://172.30.0.12:8545/health,"
            "validator-03=http://172.30.0.13:8545/health",
        ),
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.timeout <= 30:
        raise MetricsError("exporter port or timeout is invalid")
    state = ExporterState(endpoint_assignments(args.endpoints), timeout=args.timeout)
    server = ThreadingHTTPServer((args.addr, args.port), handler(state))
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
