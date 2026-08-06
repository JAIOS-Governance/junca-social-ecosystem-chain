#!/usr/bin/env python3
"""Reconcile Health, Explorer and RPC into one authoritative JSEC public state."""
from __future__ import annotations

import argparse
import json
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
    headers = {"Accept": "application/json", "User-Agent": "JSEC-Runtime-Reconciler/2.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def rpc(method: str, params: list[Any], request_id: int) -> Any:
    payload = fetch_json(RPC, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    if not isinstance(payload, dict) or "result" not in payload:
        raise ValueError(f"invalid RPC response for {method}")
    return payload["result"]


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
    values: list[int] = []
    for path, value in walk_values(payload):
        if not path or path[-1].lower() not in lowered:
            continue
        try:
            values.append(int(value, 16) if isinstance(value, str) and value.lower().startswith("0x") else int(value))
        except (TypeError, ValueError):
            pass
    return max(values) if values else None


def pick_text(payload: Any, names: tuple[str, ...]) -> str | None:
    lowered = {name.lower() for name in names}
    for path, value in walk_values(payload):
        if path and path[-1].lower() in lowered and isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def source_state(name: str, payload: Any) -> dict[str, Any]:
    return {
        "source": name,
        "finalized_height": pick_int(payload, ("finalized_height", "finalizedHeight", "height", "block_height")),
        "finalized_hash": pick_text(payload, ("finalized_hash", "finalizedHash", "hash", "block_hash")),
        "timestamp": pick_text(payload, ("finalized_timestamp", "finalizedTimestamp", "timestamp", "block_timestamp")),
    }


def normalize(output: Path) -> int:
    observed_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    payloads: dict[str, Any] = {}
    for name, url in (("health", HEALTH), ("explorer", EXPLORER)):
        try:
            payloads[name] = fetch_json(url)
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}")

    try:
        rpc_chain_id = int(str(rpc("eth_chainId", [], 1)), 16)
        rpc_head = int(str(rpc("eth_blockNumber", [], 2)), 16)
    except Exception as exc:
        rpc_chain_id = None
        rpc_head = None
        errors.append(f"rpc:{type(exc).__name__}")

    observations = [source_state(name, payload) for name, payload in payloads.items()]
    candidates = sorted(
        [row for row in observations if isinstance(row.get("finalized_height"), int)],
        key=lambda row: (row["finalized_height"], row["source"] == "health"),
        reverse=True,
    )

    selected: dict[str, Any] | None = None
    rejected: list[dict[str, Any]] = []
    if rpc_chain_id == CHAIN_ID and rpc_head is not None:
        for candidate in candidates:
            height = candidate["finalized_height"]
            if height > rpc_head:
                rejected.append({**candidate, "reason": "ahead_of_rpc_head"})
                continue
            try:
                block = rpc("eth_getBlockByNumber", [hex(height), False], 100 + len(rejected))
            except Exception as exc:
                rejected.append({**candidate, "reason": f"rpc_block_lookup:{type(exc).__name__}"})
                continue
            if not isinstance(block, dict) or not isinstance(block.get("hash"), str):
                rejected.append({**candidate, "reason": "rpc_block_missing"})
                continue
            rpc_hash = block["hash"].lower()
            source_hash = candidate.get("finalized_hash")
            if source_hash and source_hash != rpc_hash:
                rejected.append({**candidate, "rpc_hash": rpc_hash, "reason": "source_hash_conflicts_with_rpc"})
                continue
            selected = {
                "finalized_height": height,
                "finalized_hash": rpc_hash,
                "finalized_timestamp": block.get("timestamp"),
                "selected_from": candidate["source"],
                "selection_rule": "highest reported finalized height validated against canonical RPC block",
            }
            break

    if selected is None and rpc_chain_id == CHAIN_ID and rpc_head is not None:
        block = rpc("eth_getBlockByNumber", [hex(rpc_head), False], 999)
        if isinstance(block, dict) and isinstance(block.get("hash"), str):
            selected = {
                "finalized_height": rpc_head,
                "finalized_hash": block["hash"].lower(),
                "finalized_timestamp": block.get("timestamp"),
                "selected_from": "rpc",
                "selection_rule": "RPC canonical head used because finalized source metadata was unavailable or stale",
            }

    if selected is None:
        raise SystemExit("No canonical JSEC runtime state could be resolved")

    corrections = []
    for row in observations:
        differs = row.get("finalized_height") != selected["finalized_height"] or (
            row.get("finalized_hash") is not None and row.get("finalized_hash") != selected["finalized_hash"]
        )
        corrections.append({
            "source": row["source"],
            "observed_height": row.get("finalized_height"),
            "observed_hash": row.get("finalized_hash"),
            "action": "align_to_canonical" if differs else "already_aligned",
            "canonical_height": selected["finalized_height"],
            "canonical_hash": selected["finalized_hash"],
        })

    result = {
        "schema": "jsec-public-runtime-reconciliation/v2",
        "observed_at": observed_at,
        "authority": "JAIOS Institutional Governance",
        "status": "canonicalized",
        "canonical_network": "JUNCA Social Ecosystem Chain Public Testnet",
        "source_urls": {"health": HEALTH, "explorer": EXPLORER, "rpc": RPC},
        "source_observations": observations,
        "rejected_candidates": rejected,
        "correction_directives": corrections,
        "public_state": {
            "chain_id": CHAIN_ID,
            "chain_id_hex": CHAIN_ID_HEX,
            **selected,
            "rpc_block_height": rpc_head,
            "access": "read-only",
        },
        "errors": errors,
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
