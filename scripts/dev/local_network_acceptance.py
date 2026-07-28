#!/usr/bin/env python3
"""Acceptance test for the isolated JUNCA three-validator Docker network."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker/local-network/compose.yaml"
ARTIFACT_DIR = ROOT / "artifacts/local-network"
PORTS = {
    "validator-01": 18545,
    "validator-02": 18546,
    "validator-03": 18547,
}
HEALTH_ENDPOINTS = {
    validator_id: f"http://127.0.0.1:{port}/health"
    for validator_id, port in PORTS.items()
}
RPC_ENDPOINTS = {
    validator_id: f"http://127.0.0.1:{port}/"
    for validator_id, port in PORTS.items()
}


def read_health(validator_id: str) -> dict[str, object]:
    with urlopen(HEALTH_ENDPOINTS[validator_id], timeout=3) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get("validator_id") != validator_id:
        raise RuntimeError(f"invalid health response from {validator_id}")
    if value.get("mainnet_changed") is not False:
        raise RuntimeError("local network violated Mainnet boundary")
    if value.get("assets_moved") is not False:
        raise RuntimeError("local network violated asset boundary")
    if value.get("bridge_activated") is not False:
        raise RuntimeError("local network violated bridge boundary")
    return value


def snapshot(validators: tuple[str, ...]) -> dict[str, dict[str, object]]:
    return {validator_id: read_health(validator_id) for validator_id in validators}


def broadcast_vote(
    validator_id: str,
    *,
    allow_peer_failure: bool = False,
) -> dict[str, object]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": f"acceptance-{validator_id}",
            "method": "junca_broadcastVote",
            "params": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        RPC_ENDPOINTS[validator_id],
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid JSON-RPC response from {validator_id}")
    error = value.get("error")
    if error is not None:
        message = error.get("message") if isinstance(error, dict) else str(error)
        if allow_peer_failure and message == "peer vote delivery failed":
            return {"validator_id": validator_id, "expected_error": message}
        raise RuntimeError(f"{validator_id} broadcast failed: {message}")
    result = value.get("result")
    if not isinstance(result, dict) or result.get("status") != "BROADCAST":
        raise RuntimeError(f"invalid broadcast result from {validator_id}")
    return {"validator_id": validator_id, **result}


def drive_finality(
    validators: tuple[str, ...],
    *,
    allow_peer_failure: bool = False,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for validator_id in validators:
        results.append(
            broadcast_vote(
                validator_id,
                allow_peer_failure=allow_peer_failure,
            )
        )
        time.sleep(0.5)
    return results


def write_diagnostic(
    *,
    label: str,
    value: dict[str, dict[str, object]] | None,
    error: Exception | None,
) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "junca-local-network-diagnostic/v1",
        "label": label,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": value,
        "error": None if error is None else f"{type(error).__name__}: {error}",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    (ARTIFACT_DIR / "diagnostic.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n"
    )


def wait_for(
    operation: Callable[[], dict[str, dict[str, object]]],
    predicate: Callable[[dict[str, dict[str, object]]], bool],
    *,
    timeout: int,
    label: str,
) -> dict[str, dict[str, object]]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    last_value: dict[str, dict[str, object]] | None = None
    next_report = 0.0
    while time.monotonic() < deadline:
        try:
            last_value = operation()
            last_error = None
            if predicate(last_value):
                return last_value
            if time.monotonic() >= next_report:
                print(json.dumps({"label": label, "snapshot": last_value}, sort_keys=True))
                next_report = time.monotonic() + 5
        except (OSError, RuntimeError, URLError, json.JSONDecodeError) as exc:
            last_error = exc
            if time.monotonic() >= next_report:
                print(json.dumps({"label": label, "error": str(exc)}, sort_keys=True))
                next_report = time.monotonic() + 5
        time.sleep(1)
    write_diagnostic(label=label, value=last_value, error=last_error)
    message = f"timed out waiting for {label}"
    if last_error is not None:
        message += f": {last_error}"
    raise RuntimeError(message)


def converged(value: dict[str, dict[str, object]], minimum_height: int) -> bool:
    heights = {item.get("head_height") for item in value.values()}
    hashes = {item.get("head_hash") for item in value.values()}
    certificate_hashes = {
        (
            item.get("consensus", {}).get("last_certificate_hash")
            if isinstance(item.get("consensus"), dict)
            else None
        )
        for item in value.values()
    }
    statuses = {item.get("status") for item in value.values()}
    return (
        len(heights) == 1
        and len(hashes) == 1
        and len(certificate_hashes) == 1
        and None not in certificate_hashes
        and statuses == {"healthy"}
        and next(iter(heights), -1) >= minimum_height
    )


def compose(*arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        cwd=ROOT,
        check=True,
    )


def source_sha() -> str:
    supplied = os.getenv("GITHUB_SHA", "")
    if len(supplied) == 40:
        return supplied
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def main() -> int:
    all_validators = tuple(PORTS)
    active_validators = ("validator-01", "validator-02")

    ready = wait_for(
        lambda: snapshot(all_validators),
        lambda value: all(item.get("status") == "healthy" for item in value.values()),
        timeout=60,
        label="three-validator readiness",
    )
    if {item.get("head_height") for item in ready.values()} != {0}:
        raise RuntimeError("fresh local network did not start from genesis height")

    initial_inputs = drive_finality(all_validators)
    baseline = wait_for(
        lambda: snapshot(all_validators),
        lambda value: converged(value, 1),
        timeout=60,
        label="initial deterministic authenticated finality",
    )
    baseline_height = int(baseline["validator-01"]["head_height"])

    compose("stop", "validator-03")
    time.sleep(2)
    quorum_loss_inputs = drive_finality(
        active_validators,
        allow_peer_failure=True,
    )
    stalled_start = wait_for(
        lambda: snapshot(active_validators),
        lambda value: len({item.get("head_height") for item in value.values()}) == 1,
        timeout=30,
        label="two-validator stable head",
    )
    stalled_height = int(stalled_start["validator-01"]["head_height"])
    time.sleep(6)
    stalled_end = snapshot(active_validators)
    if any(
        int(item["head_height"]) != stalled_height for item in stalled_end.values()
    ):
        write_diagnostic(label="strict quorum violation", value=stalled_end, error=None)
        raise RuntimeError("two validators advanced finality without strict quorum")

    compose("start", "validator-03")
    wait_for(
        lambda: snapshot(all_validators),
        lambda value: all(item.get("status") == "healthy" for item in value.values()),
        timeout=60,
        label="validator restart readiness",
    )
    recovery_inputs = drive_finality(all_validators)
    recovered = wait_for(
        lambda: snapshot(all_validators),
        lambda value: converged(value, stalled_height + 1),
        timeout=60,
        label="deterministic validator restart recovery and resumed finality",
    )

    evidence = {
        "schema_version": "junca-local-network-acceptance/v2",
        "state": "ACCEPTED",
        "network": "isolated-local-development-only",
        "source_commit": source_sha(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "input_mode": "deterministic-allowlisted-junca_broadcastVote",
        "initial_inputs": initial_inputs,
        "baseline": baseline,
        "quorum_loss": {
            "stopped_validator": "validator-03",
            "inputs": quorum_loss_inputs,
            "head_height": stalled_height,
            "observation_seconds": 6,
            "false_finality_observed": False,
        },
        "recovery_inputs": recovery_inputs,
        "recovery": recovered,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    encoded = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
    evidence["evidence_sha256"] = hashlib.sha256(encoded).hexdigest()
    target = ARTIFACT_DIR / "acceptance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    print(target)
    print(
        json.dumps(
            {
                "baseline_height": baseline_height,
                "stalled_height": stalled_height,
                "recovered_height": recovered["validator-01"]["head_height"],
                "state": "ACCEPTED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
