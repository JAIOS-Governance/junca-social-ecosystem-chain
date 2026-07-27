#!/usr/bin/env python3
"""Live, read-only acceptance checks for JUNCA Public Testnet endpoints.

This script is intentionally separate from the unit-test suite because it
performs external HTTPS requests.  It never submits a transaction; the only
unsafe request is a method-name probe whose required result is rejection.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HEALTH_URL = "https://health.jaios-governance.org/health"
EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json"
RPC_URL = "https://rpc.jaios-governance.org/"
SAFE_RPC_METHODS: Mapping[str, list[Any]] = {
    "eth_chainId": [],
    "eth_blockNumber": [],
    "eth_getBlockByNumber": ["latest", False],
    "net_peerCount": [],
    "web3_clientVersion": [],
}
UNSAFE_RPC_METHODS = (
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "admin_peers",
    "debug_traceBlock",
    "personal_unlockAccount",
    "miner_start",
    "junca_health",
    "junca_propose",
    "junca_submitVote",
    "junca_broadcastVote",
)
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")


class AcceptanceError(RuntimeError):
    """Raised when a public endpoint violates its acceptance contract."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: Mapping[str, Any]


Transport = Callable[[str, str, Mapping[str, Any] | None], HttpResponse]


def https_json_transport(
    method: str, url: str, payload: Mapping[str, Any] | None
) -> HttpResponse:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (OSError, URLError) as exc:
        raise AcceptanceError(f"{url}: endpoint unavailable") from exc
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{url}: response is not valid JSON") from exc
    if not isinstance(body, Mapping):
        raise AcceptanceError(f"{url}: response must be a JSON object")
    return HttpResponse(status, body)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _verify_boundaries(body: Mapping[str, Any], endpoint: str) -> None:
    for field in BOUNDARY_FIELDS:
        _require(body.get(field) is False, f"{endpoint}: {field} must be false")


def _rpc_payload(request_id: str, method: str, params: list[Any]) -> Mapping[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def run_acceptance(transport: Transport = https_json_transport) -> Mapping[str, Any]:
    checks: dict[str, Any] = {}

    health = transport("GET", HEALTH_URL, None)
    _require(health.status == 200, "health: expected HTTP 200")
    _require(health.body.get("status") == "healthy", "health: status is not healthy")
    _require(health.body.get("read_only") is True, "health: read_only must be true")
    _verify_boundaries(health.body, "health")
    checks["health"] = "PASS"

    explorer = transport("GET", EXPLORER_URL, None)
    _require(explorer.status == 200, "explorer: expected HTTP 200")
    _require(explorer.body.get("status") == "ready", "explorer: status is not ready")
    _require(
        explorer.body.get("finalized_only") is True,
        "explorer: finalized_only must be true",
    )
    _verify_boundaries(explorer.body, "explorer")
    head = explorer.body.get("head")
    _require(isinstance(head, Mapping), "explorer: finalized head is missing")
    _require(
        isinstance(head.get("height"), int) and head["height"] >= 0,
        "explorer: invalid finalized height",
    )
    _require(
        isinstance(head.get("hash"), str) and head["hash"].startswith("0x"),
        "explorer: invalid finalized hash",
    )
    _require(
        isinstance(head.get("signed_power"), int)
        and isinstance(head.get("total_power"), int)
        and 0 < head["signed_power"] <= head["total_power"],
        "explorer: invalid finality power",
    )
    checks["explorer"] = {
        "result": "PASS",
        "finalized_height": head["height"],
        "finalized_hash": head["hash"],
        "signed_power": head["signed_power"],
        "total_power": head["total_power"],
    }

    safe_results: dict[str, Any] = {}
    for index, (method, params) in enumerate(SAFE_RPC_METHODS.items(), start=1):
        request_id = f"safe-{index}"
        response = transport("POST", RPC_URL, _rpc_payload(request_id, method, params))
        _require(response.status == 200, f"rpc {method}: expected HTTP 200")
        _require(response.body.get("jsonrpc") == "2.0", f"rpc {method}: invalid version")
        _require(response.body.get("id") == request_id, f"rpc {method}: id mismatch")
        _require("result" in response.body, f"rpc {method}: result is missing")
        _require("error" not in response.body, f"rpc {method}: unexpected error")
        safe_results[method] = response.body["result"]
    checks["safe_rpc"] = {"result": "PASS", "methods": sorted(safe_results)}

    for index, method in enumerate(UNSAFE_RPC_METHODS, start=1):
        request_id = f"unsafe-{index}"
        response = transport("POST", RPC_URL, _rpc_payload(request_id, method, []))
        _require(response.status == 403, f"rpc {method}: expected HTTP 403")
        error = response.body.get("error")
        _require(isinstance(error, Mapping), f"rpc {method}: error is missing")
        _require(error.get("code") == -32601, f"rpc {method}: expected -32601")
        _require(response.body.get("id") == request_id, f"rpc {method}: id mismatch")
    checks["unsafe_rpc_rejection"] = {
        "result": "PASS",
        "methods": list(UNSAFE_RPC_METHODS),
    }

    return {
        "status": "PASS",
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "endpoints": {
            "health": HEALTH_URL,
            "explorer": EXPLORER_URL,
            "rpc": RPC_URL,
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compact", action="store_true", help="emit compact JSON instead of indented JSON"
    )
    args = parser.parse_args()
    try:
        report = run_acceptance()
    except AcceptanceError as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                ensure_ascii=False,
                indent=None if args.compact else 2,
            )
        )
        return 1
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
