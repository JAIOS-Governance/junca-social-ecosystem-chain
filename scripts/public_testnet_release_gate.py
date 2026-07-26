#!/usr/bin/env python3
"""Aggregate public-testnet evidence into one deterministic, fail-closed release decision."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CHAIN_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
NETWORK_LABEL = "Public Testnet / No Monetary Value"
AWS_ACCOUNT_ID = "595710543956"
AWS_REGION = "us-east-1"
EXPECTED_HOSTS = {
    "rpc": "rpc.jaios-governance.org",
    "explorer": "explorer.jaios-governance.org",
    "health": "health.jaios-governance.org",
}


def read_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Evidence must be a JSON object: {path}")
    return value


def check_https_endpoint(name: str, value: Any, failures: list[str]) -> None:
    if not isinstance(value, str):
        failures.append(f"endpoint.{name}:missing")
        return
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != EXPECTED_HOSTS[name] or parsed.port not in (None, 443):
        failures.append(f"endpoint.{name}:canonical_https_mismatch")


def evaluate(
    binding: dict[str, Any],
    runtime: dict[str, Any],
    rollback: dict[str, Any],
    predeployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []

    if predeployment is not None:
        if predeployment.get("decision") != "PREDEPLOYMENT_ACCEPTED":
            failures.append("predeployment.decision:not_accepted")
        if predeployment.get("accepted") is not True:
            failures.append("predeployment.accepted:not_true")
        if predeployment.get("live_runtime_verified") is not False:
            failures.append("predeployment.live_runtime_verified:must_be_false")
        pre_boundary = predeployment.get("release_boundary", {})
        for field in ("mainnet_changed", "assets_moved", "bridge_activated"):
            if pre_boundary.get(field) is not False:
                failures.append(f"predeployment.release_boundary.{field}:not_false")
        if pre_boundary.get("bridge_route") != "PAUSED":
            failures.append("predeployment.release_boundary.bridge_route:not_paused")

    for source_name, source in (("binding", binding), ("runtime", runtime), ("rollback", rollback)):
        if source.get("official_chain_name") != CHAIN_NAME:
            failures.append(f"{source_name}.official_chain_name:mismatch")
        if source.get("governance") != GOVERNANCE:
            failures.append(f"{source_name}.governance:mismatch")
        if source.get("network_label") != NETWORK_LABEL:
            failures.append(f"{source_name}.network_label:mismatch")

    if binding.get("status") != "AWS_BINDING_READBACK_VERIFIED":
        failures.append("binding.status:not_verified")
    aws = binding.get("aws", {})
    if aws.get("account_id") != AWS_ACCOUNT_ID:
        failures.append("binding.aws.account_id:mismatch")
    if aws.get("region") != AWS_REGION:
        failures.append("binding.aws.region:mismatch")
    failure_domains = aws.get("failure_domains", [])
    if (
        len(failure_domains) != 3
        or len(set(failure_domains)) != 3
        or any(not isinstance(zone, str) or not zone.startswith(AWS_REGION) for zone in failure_domains)
    ):
        failures.append("binding.failure_domains:not_three")
    signers = binding.get("validator_signers", [])
    signer_arns = [s.get("resource_arn") for s in signers if isinstance(s, dict)]
    signer_prefix = f"arn:aws:kms:{AWS_REGION}:{AWS_ACCOUNT_ID}:key/"
    if (
        len(signers) != 3
        or len(set(signer_arns)) != 3
        or None in signer_arns
        or any(not isinstance(arn, str) or not arn.startswith(signer_prefix) for arn in signer_arns)
    ):
        failures.append("binding.validator_signers:not_three_distinct")

    gates = runtime.get("gates", {})
    required_runtime_gates = (
        "https", "tls", "dns", "chain_id", "genesis_identity", "advancing_head",
        "finalized_head", "validator_quorum", "peer_connectivity", "rpc_envelope",
        "unsafe_rpc_rejection", "rate_limit", "explorer_parity", "health",
        "monitoring", "restart_recovery", "rollback_readiness",
    )
    for gate in required_runtime_gates:
        if gates.get(gate) is not True:
            failures.append(f"runtime.gates.{gate}:not_passed")
    if runtime.get("validator_quorum") != "3/3":
        failures.append("runtime.validator_quorum:not_3_of_3")

    endpoints = runtime.get("public_endpoints", {})
    for name in EXPECTED_HOSTS:
        check_https_endpoint(name, endpoints.get(name), failures)

    required_rollback_gates = (
        "endpoint_withdrawal", "bridge_pause", "logs_audit", "checkpoint",
        "binary_restore", "genesis_restore", "snapshot_restore", "quorum_recovery",
        "read_only_endpoint_recovery", "explorer_parity_recovery",
    )
    rollback_gates = rollback.get("gates", {})
    for gate in required_rollback_gates:
        if rollback_gates.get(gate) is not True:
            failures.append(f"rollback.gates.{gate}:not_passed")

    identities = {
        (source.get("chain_id"), source.get("genesis_hash"))
        for source in (binding, runtime, rollback)
    }
    source_commits = {source.get("source_commit") for source in (binding, runtime, rollback)}
    if any(not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) for commit in source_commits):
        failures.append("source_commit:missing_or_invalid")
    elif len(source_commits) != 1:
        failures.append("source_commit:mismatch")
    if any(chain_id in (None, "") or genesis in (None, "") for chain_id, genesis in identities):
        failures.append("chain_identity:missing")
    elif len(identities) != 1:
        failures.append("chain_identity:mismatch")

    for source_name, source in (("binding", binding), ("runtime", runtime), ("rollback", rollback)):
        boundary = source.get("release_boundary", {})
        if boundary.get("mainnet_changed") is not False:
            failures.append(f"{source_name}.release_boundary.mainnet_changed:not_false")
        if boundary.get("assets_moved") is not False:
            failures.append(f"{source_name}.release_boundary.assets_moved:not_false")
        if boundary.get("bridge_activated") is not False:
            failures.append(f"{source_name}.release_boundary.bridge_activated:not_false")
        if boundary.get("bridge_route") != "PAUSED":
            failures.append(f"{source_name}.release_boundary.bridge_route:not_paused")

    failures = sorted(set(failures))
    accepted = not failures
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "official_chain_name": CHAIN_NAME,
        "governance": GOVERNANCE,
        "network_label": NETWORK_LABEL,
        "decision": "PUBLIC_TESTNET_ACCEPTED" if accepted else "PUBLIC_TESTNET_REJECTED",
        "accepted": accepted,
        "source_commit": next(iter(source_commits)) if len(source_commits) == 1 else None,
        "failure_count": len(failures),
        "failures": failures,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "bridge_route": "PAUSED",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--rollback", required=True)
    parser.add_argument("--predeployment", required=True)
    parser.add_argument("--output", default="public-testnet-release-decision.json")
    args = parser.parse_args()

    decision = evaluate(
        read_json(args.binding),
        read_json(args.runtime),
        read_json(args.rollback),
        read_json(args.predeployment),
    )
    output = Path(args.output)
    output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    Path(f"{args.output}.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"decision": decision["decision"], "sha256": digest}))
    return 0 if decision["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
