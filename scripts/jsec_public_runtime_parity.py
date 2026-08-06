#!/usr/bin/env python3
"""Normalize public JSEC runtime evidence and fail closed on any disagreement."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEALTH = "https://health.jaios-governance.org/health"
EXPLORER = "https://explorer.jaios-governance.org/explorer.json"
RPC = "https://rpc.jaios-governance.org/"
CHAIN_ID = 20260723
CHAIN_ID_HEX = "0x1352773"


def fetch_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Accept": "application/json", "User-Agent": "JSEC-Runtime-Parity/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def walk_values(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_values(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_values(child, path + (str(index),))
    else:
        yield path, value


def pick_int(payload: Any, names: tuple[str, ...]) -> int | None:
    lowered = {name.lower() for name in names}
    candidates: list[int] = []
    for path, value in walk_values(payload):
        if not path or path[-1].lower() not in lowered:
            continue
        try:
            if isinstance(value, str) and value.lower().startswith("0x"):
                candidates.append(int(value, 16))
            else:
                candidates.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(candidates) if candidates else None


def pick_text(payload: Any, names: tuple[str, ...]) -> str | None:
    lowered = {name.lower() for name in names}
    for path, value in walk_values(payload):
        if path and path[-1].lower() in lowered and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize(output: Path) -> int:
    observed_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    try:
        health = fetch_json(HEALTH)
    except Exception as exc:
        health = None
        errors.append(f"health:{type(exc).__name__}")
    try:
        explorer = fetch_json(EXPLORER)
    except Exception as exc:
        explorer = None
        errors.append(f"explorer:{type(exc).__name__}")
    try:
        rpc_chain = fetch_json(RPC, {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []})
        rpc_height = fetch_json(RPC, {"jsonrpc": "2.0", "id": 2, "method": "eth_blockNumber", "params": []})
    except Exception as exc:
        rpc_chain = None
        rpc_height = None
        errors.append(f"rpc:{type(exc).__name__}")

    health_height = pick_int(health, ("finalized_height", "finalizedHeight", "height", "block_height")) if health else None
    explorer_height = pick_int(explorer, ("finalized_height", "finalizedHeight", "height", "block_height")) if explorer else None
    health_hash = pick_text(health, ("finalized_hash", "finalizedHash", "hash", "block_hash")) if health else None
    explorer_hash = pick_text(explorer, ("finalized_hash", "finalizedHash", "hash", "block_hash")) if explorer else None

    rpc_chain_id = None
    if isinstance(rpc_chain, dict) and isinstance(rpc_chain.get("result"), str):
        try:
            rpc_chain_id = int(rpc_chain["result"], 16)
        except ValueError:
            errors.append("rpc_chain_id:invalid")
    rpc_block_height = None
    if isinstance(rpc_height, dict) and isinstance(rpc_height.get("result"), str):
        try:
            rpc_block_height = int(rpc_height["result"], 16)
        except ValueError:
            errors.append("rpc_height:invalid")

    checks = {
        "all_sources_reachable": not errors,
        "chain_id_matches": rpc_chain_id == CHAIN_ID,
        "health_explorer_height_matches": health_height is not None and health_height == explorer_height,
        "rpc_not_behind_finalized": rpc_block_height is not None and health_height is not None and rpc_block_height >= health_height,
        "hash_matches_when_available": not (health_hash and explorer_hash) or health_hash == explorer_hash,
    }
    verified = all(checks.values())
    public_state: dict[str, Any]
    if verified:
        public_state = {
            "chain_id": CHAIN_ID,
            "chain_id_hex": CHAIN_ID_HEX,
            "finalized_height": health_height,
            "finalized_hash": health_hash or explorer_hash,
            "rpc_block_height": rpc_block_height,
            "access": "read-only",
        }
    else:
        public_state = {
            "chain_id": CHAIN_ID,
            "chain_id_hex": CHAIN_ID_HEX,
            "status": "evidence_unavailable",
            "display_rule": "Do not display height, hash, peer or ready values until parity is restored."
        }

    result = {
        "schema": "jsec-public-runtime-parity/v1",
        "observed_at": observed_at,
        "authority": "JAIOS Institutional Governance",
        "status": "verified" if verified else "evidence_unavailable",
        "canonical_network": "JUNCA Social Ecosystem Chain Public Testnet",
        "source_urls": {"health": HEALTH, "explorer": EXPLORER, "rpc": RPC},
        "checks": checks,
        "errors": errors,
        "public_state": public_state,
        "safety_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(normalize(Path(args.output)))


if __name__ == "__main__":
    main()
