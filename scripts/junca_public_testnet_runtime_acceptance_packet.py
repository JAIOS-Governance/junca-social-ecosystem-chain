#!/usr/bin/env python3
"""Collect repeatable live Public Testnet endpoint acceptance evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.junca_public_testnet_endpoint_test import (
    AcceptanceError,
    EXPLORER_URL,
    HEALTH_URL,
    RPC_URL,
    HttpResponse,
    https_json_transport,
)


SCAN_URL = "https://scan.jaios-governance.org/"
EXPECTED_SCAN_LOCATION = "https://explorer.jaios-governance.org:443/"
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rpc(method: str, params: list[Any], request_id: str) -> HttpResponse:
    return https_json_transport(
        "POST",
        RPC_URL,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
    )


def _scan_redirect() -> dict[str, Any]:
    opener = build_opener(_NoRedirect)
    request = Request(SCAN_URL, method="GET")
    try:
        response = opener.open(request, timeout=10)
        status = response.status
        location = response.headers.get("Location")
        response.close()
    except HTTPError as exc:
        status = exc.code
        location = exc.headers.get("Location")
    except (OSError, URLError) as exc:
        return {
            "url": SCAN_URL,
            "status": None,
            "location": None,
            "accepted": False,
            "error": type(exc).__name__,
        }
    return {
        "url": SCAN_URL,
        "status": status,
        "location": location,
        "accepted": status == 301 and location == EXPECTED_SCAN_LOCATION,
    }


def _boundary_ok(body: Mapping[str, Any]) -> bool:
    return all(body.get(field) is False for field in BOUNDARY_FIELDS)


def _hex_int(value: object) -> int | None:
    if not isinstance(value, str) or not value.startswith("0x"):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def collect_observation(index: int) -> dict[str, Any]:
    health = https_json_transport("GET", HEALTH_URL, None)
    explorer = https_json_transport("GET", EXPLORER_URL, None)
    block_number = _rpc("eth_blockNumber", [], f"packet-{index}-height")
    block = _rpc(
        "eth_getBlockByNumber",
        ["latest", False],
        f"packet-{index}-block",
    )
    chain_id = _rpc("eth_chainId", [], f"packet-{index}-chain")
    peer_count = _rpc("net_peerCount", [], f"packet-{index}-peers")
    client_version = _rpc(
        "web3_clientVersion",
        [],
        f"packet-{index}-client",
    )

    explorer_head = explorer.body.get("head")
    explorer_network = explorer.body.get("network")
    rpc_block = block.body.get("result")
    failures: list[str] = []
    if health.status != 200 or health.body.get("status") != "healthy":
        failures.append("health:not_healthy")
    if explorer.status != 200 or explorer.body.get("status") != "ready":
        failures.append("explorer:not_ready")
    if not _boundary_ok(health.body) or not _boundary_ok(explorer.body):
        failures.append("boundary:not_false")
    if not isinstance(explorer_head, Mapping):
        failures.append("explorer:head_missing")
        explorer_head = {}
    if not isinstance(explorer_network, Mapping):
        failures.append("explorer:network_missing")
        explorer_network = {}
    if not isinstance(rpc_block, Mapping):
        failures.append("rpc:block_missing")
        rpc_block = {}

    explorer_height = explorer_head.get("height")
    health_validator = health.body.get("validator")
    health_height = (
        health_validator.get("head_height")
        if isinstance(health_validator, Mapping)
        else None
    )
    rpc_height = _hex_int(block_number.body.get("result"))
    if not (
        isinstance(explorer_height, int)
        and explorer_height == health_height == rpc_height
    ):
        failures.append("height:health_explorer_rpc_mismatch")
    if not (
        rpc_block.get("number") == block_number.body.get("result")
        and rpc_block.get("hash") == explorer_head.get("hash")
        and rpc_block.get("timestamp") == explorer_head.get("timestamp")
        and rpc_block.get("stateRoot") == explorer_head.get("state_root")
    ):
        failures.append("block:rpc_explorer_mismatch")
    if not (
        chain_id.body.get("result") == explorer_network.get("chain_id")
        and peer_count.body.get("result")
        == explorer_network.get("peer_count_hex")
        and client_version.body.get("result")
        == explorer_network.get("client_version")
    ):
        failures.append("network:rpc_explorer_mismatch")
    if not (
        explorer_head.get("signed_power") == 3
        and explorer_head.get("total_power") == 3
        and isinstance(explorer_head.get("certificate_hash"), str)
    ):
        failures.append("certificate:not_exact_three")

    return {
        "index": index,
        "observed_at": _utc_now(),
        "accepted": not failures,
        "failures": failures,
        "health": {"status": health.status, "body": health.body},
        "explorer": {"status": explorer.status, "body": explorer.body},
        "rpc": {
            "block_number": block_number.body,
            "block": block.body,
            "chain_id": chain_id.body,
            "peer_count": peer_count.body,
            "client_version": client_version.body,
        },
        "normalized": {
            "height": explorer_height,
            "hash": explorer_head.get("hash"),
            "timestamp": explorer_head.get("timestamp"),
            "timestamp_decimal": _hex_int(explorer_head.get("timestamp")),
            "state_root": explorer_head.get("state_root"),
            "certificate_hash": explorer_head.get("certificate_hash"),
            "signed_power": explorer_head.get("signed_power"),
            "total_power": explorer_head.get("total_power"),
            "peer_count": explorer_network.get("peer_count"),
        },
    }


def _unsafe_rejection() -> dict[str, Any]:
    methods = ("eth_sendRawTransaction", "admin_peers")
    results: dict[str, Any] = {}
    accepted = True
    for index, method in enumerate(methods, start=1):
        try:
            response = _rpc(
                method,
                ["0x00"] if index == 1 else [],
                f"unsafe-{index}",
            )
        except AcceptanceError as exc:
            accepted = False
            results[method] = {
                "status": None,
                "accepted": False,
                "error": str(exc),
            }
            continue
        error = response.body.get("error")
        passed = (
            response.status == 403
            and isinstance(error, Mapping)
            and error.get("code") == -32601
        )
        accepted = accepted and passed
        results[method] = {
            "status": response.status,
            "body": response.body,
            "accepted": passed,
        }
    return {"accepted": accepted, "methods": results}


def build_packet(observations: list[dict[str, Any]], interval: int) -> dict[str, Any]:
    failures: list[str] = []
    if any(not item["accepted"] for item in observations):
        failures.append("endpoint_parity:not_continuously_accepted")
    heights = [item["normalized"]["height"] for item in observations]
    timestamps = [
        item["normalized"]["timestamp_decimal"] for item in observations
    ]
    certificates = [
        item["normalized"]["certificate_hash"] for item in observations
    ]
    peer_counts = [item["normalized"]["peer_count"] for item in observations]
    metadata_by_hash: dict[str, tuple[object, object, object]] = {}
    for item in observations:
        normalized = item["normalized"]
        block_hash = normalized["hash"]
        metadata = (
            normalized["timestamp"],
            normalized["state_root"],
            normalized["certificate_hash"],
        )
        if (
            isinstance(block_hash, str)
            and block_hash in metadata_by_hash
            and metadata_by_hash[block_hash] != metadata
        ):
            failures.append("block:same_hash_metadata_changed")
            break
        if isinstance(block_hash, str):
            metadata_by_hash[block_hash] = metadata
    if not all(
        isinstance(left, int)
        and isinstance(right, int)
        and right > left
        for left, right in zip(heights, heights[1:])
    ):
        failures.append("head:not_advancing_each_observation")
    if not all(
        isinstance(left, int)
        and isinstance(right, int)
        and right > left
        for left, right in zip(timestamps, timestamps[1:])
    ):
        failures.append("timestamp:not_advancing_each_observation")
    if len(set(certificates)) != len(certificates):
        failures.append("certificate:not_advancing_each_observation")
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 2
        for value in peer_counts
    ):
        failures.append("peers:not_exact_public_quorum")

    unsafe = _unsafe_rejection()
    if not unsafe["accepted"]:
        failures.append("unsafe_rpc:not_rejected")
    scan = _scan_redirect()
    if not scan["accepted"]:
        failures.append("scan:redirect_mismatch")
    return {
        "schema_version": "junca-public-testnet-live-acceptance-packet/v1",
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "observation_count": len(observations),
        "observation_interval_seconds": interval,
        "observed_from": observations[0]["observed_at"],
        "observed_to": observations[-1]["observed_at"],
        "observations": observations,
        "unsafe_rpc_rejection": unsafe,
        "scan_redirect": scan,
        "replay": {
            "command": (
                "python scripts/junca_public_testnet_runtime_acceptance_packet.py "
                f"--observations {len(observations)} "
                f"--interval-seconds {interval} --output <evidence.json>"
            )
        },
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=int, default=3)
    parser.add_argument("--interval-seconds", type=int, default=35)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.observations < 3:
        parser.error("--observations must be at least 3")
    if args.interval_seconds < 30:
        parser.error("--interval-seconds must be at least 30")

    observations: list[dict[str, Any]] = []
    collection_error: str | None = None
    for index in range(1, args.observations + 1):
        try:
            observations.append(collect_observation(index))
        except AcceptanceError as exc:
            collection_error = str(exc)
            break
        if index < args.observations:
            time.sleep(args.interval_seconds)
    if collection_error is None:
        packet = build_packet(observations, args.interval_seconds)
    else:
        packet = {
            "schema_version": "junca-public-testnet-live-acceptance-packet/v1",
            "scope": "Public Testnet Runtime Acceptance / Read-only",
            "status": "FAIL",
            "failures": ["observation:endpoint_unavailable"],
            "collection_error": collection_error,
            "requested_observation_count": args.observations,
            "observation_count": len(observations),
            "observation_interval_seconds": args.interval_seconds,
            "observed_from": (
                observations[0]["observed_at"] if observations else None
            ),
            "observed_to": (
                observations[-1]["observed_at"] if observations else None
            ),
            "observations": observations,
            "release_boundary": {
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            },
        }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": packet["status"],
                "failures": packet["failures"],
                "output": str(target),
            },
            sort_keys=True,
        )
    )
    return 0 if packet["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
