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
VALIDATOR_IDS = tuple(PORTS)
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


def _hex_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 66
        and value.startswith("0x")
        and all(character in "0123456789abcdef" for character in value[2:])
    )


def _certificate_hash(certificate: dict[str, object]) -> str | None:
    body = {
        "block_hash": certificate.get("block_hash"),
        "chain_id": certificate.get("chain_id"),
        "height": certificate.get("height"),
        "round": certificate.get("round"),
        "signed_power": certificate.get("signed_power"),
        "total_power": certificate.get("total_power"),
        "validator_ids": certificate.get("validator_ids"),
        "vote_hashes": certificate.get("vote_hashes"),
    }
    if (
        not _hex_digest(body["block_hash"])
        or body["chain_id"] != 20260723
        or isinstance(body["height"], bool)
        or not isinstance(body["height"], int)
        or int(body["height"]) < 1
        or isinstance(body["round"], bool)
        or not isinstance(body["round"], int)
        or int(body["round"]) < 0
        or body["signed_power"] != 3
        or body["total_power"] != 3
        or body["validator_ids"] != list(VALIDATOR_IDS)
        or not isinstance(body["vote_hashes"], list)
        or len(body["vote_hashes"]) != 3
        or len(set(body["vote_hashes"])) != 3
        or not all(_hex_digest(item) for item in body["vote_hashes"])
    ):
        return None
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00" + encoded
    ).hexdigest()


def development_manual_mode_ready(
    value: dict[str, dict[str, object]],
) -> bool:
    """Require an exact reachable, intentionally non-operational local mode.

    The isolated simulation drives finality through the allowlisted
    ``junca_broadcastVote`` method. It must therefore keep automatic finality
    disabled and must never pass the production ``healthy`` contract.
    """

    if tuple(value) != VALIDATOR_IDS:
        return False
    for validator_id, item in value.items():
        gates = item.get("health_gates")
        automatic = item.get("automatic_finality")
        consensus = item.get("consensus")
        sync_recovery = item.get("sync_recovery")
        if (
            item.get("validator_id") != validator_id
            or item.get("status") != "unhealthy"
            or item.get("network") != "Public Testnet / No Monetary Value"
            or item.get("chain_id") != 20260723
            or isinstance(item.get("head_height"), bool)
            or not isinstance(item.get("head_height"), int)
            or int(item["head_height"]) < 0
            or not _hex_digest(item.get("head_hash"))
            or not _hex_digest(item.get("genesis_hash"))
            or item.get("head_timestamp") is not None
            and (
                isinstance(item.get("head_timestamp"), bool)
                or not isinstance(item.get("head_timestamp"), int)
                or int(item["head_timestamp"]) <= 0
            )
            or isinstance(item.get("peer_count"), bool)
            or not isinstance(item.get("peer_count"), int)
            or not 0 <= int(item["peer_count"]) <= 2
            or item.get("private_key_material_accepted") is not False
            or item.get("automatic_finality_enabled") is not False
            or item.get("automatic_finality_loop_running") is not False
            or item.get("block_interval_seconds") != 0
            or item.get("slot_epoch_seconds") != 0
            or not isinstance(gates, dict)
            or gates.get("automatic_finality") is not False
            or not isinstance(automatic, dict)
            or automatic.get("enabled") is not False
            or automatic.get("loop_running") is not False
            or automatic.get("block_interval_seconds") != 0
            or automatic.get("slot_epoch_seconds") != 0
            or not isinstance(consensus, dict)
            or consensus.get("schema_version")
            != "junca-public-testnet-consensus-runtime/v1"
            or consensus.get("chain_id") != 20260723
            or consensus.get("head_height") != item.get("head_height")
            or consensus.get("required_vote_count") != 3
            or consensus.get("quorum_rule")
            != "strictly-greater-than-two-thirds"
            or consensus.get("private_key_material_accepted") is not False
            or not isinstance(sync_recovery, dict)
            or sync_recovery.get("schema_version")
            != "junca-validator-sync-recovery/v1"
            or sync_recovery.get("recovery_action") != "CLEAN"
            or sync_recovery.get("chain_id") != 20260723
            or sync_recovery.get("genesis_hash") != item.get("genesis_hash")
        ):
            return False
    return True


def manual_finality_converged(
    value: dict[str, dict[str, object]], minimum_height: int
) -> bool:
    if not development_manual_mode_ready(value):
        return False
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
    exact_finality = []
    for item in value.values():
        gates = item["health_gates"]
        consensus = item.get("consensus")
        certificate = (
            consensus.get("last_certificate")
            if isinstance(consensus, dict)
            else None
        )
        certificate_hash = (
            _certificate_hash(certificate)
            if isinstance(certificate, dict)
            else None
        )
        exact_finality.append(
            item.get("peer_count") == 2
            and gates.get("authenticated_peer_quorum") is True
            and gates.get("current_three_of_three_certificate") is True
            and gates.get("fresh_finalized_head") is True
            and gates.get("automatic_finality") is False
            and isinstance(certificate, dict)
            and certificate.get("height") == item.get("head_height")
            and certificate.get("block_hash") == item.get("head_hash")
            and certificate.get("finality_status") == "FINALIZED"
            and certificate_hash is not None
            and certificate.get("certificate_hash") == certificate_hash
            and consensus.get("last_certificate_hash") == certificate_hash
        )
    return (
        len(heights) == 1
        and len(hashes) == 1
        and len(certificate_hashes) == 1
        and None not in certificate_hashes
        and all(exact_finality)
        and next(iter(heights), -1) >= minimum_height
    )


def compose(*arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        cwd=ROOT,
        check=True,
    )


def source_sha() -> str:
    for name in ("JUNCA_SOURCE_SHA", "GITHUB_SHA"):
        supplied = os.getenv(name, "").strip()
        if len(supplied) == 40 and all(character in "0123456789abcdef" for character in supplied.lower()):
            return supplied.lower()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def main() -> int:
    all_validators = VALIDATOR_IDS
    active_validators = ("validator-01", "validator-02")

    ready = wait_for(
        lambda: snapshot(all_validators),
        development_manual_mode_ready,
        timeout=60,
        label="three-validator manual-mode reachability",
    )
    if {item.get("head_height") for item in ready.values()} != {0}:
        raise RuntimeError("fresh local network did not start from genesis height")

    initial_inputs = drive_finality(all_validators)
    baseline = wait_for(
        lambda: snapshot(all_validators),
        lambda value: manual_finality_converged(value, 1),
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
        development_manual_mode_ready,
        timeout=60,
        label="validator restart manual-mode reachability",
    )
    recovery_inputs = drive_finality(all_validators)
    recovered = wait_for(
        lambda: snapshot(all_validators),
        lambda value: manual_finality_converged(value, stalled_height + 1),
        timeout=60,
        label="deterministic validator restart recovery and resumed finality",
    )

    evidence = {
        "schema_version": "junca-local-network-acceptance/v3",
        "state": "ACCEPTED",
        "network": "isolated-local-development-only",
        "source_commit": source_sha(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "input_mode": "deterministic-allowlisted-junca_broadcastVote",
        "production_health_claimed": False,
        "automatic_finality_enabled": False,
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
                "source_commit": evidence["source_commit"],
                "state": "ACCEPTED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
