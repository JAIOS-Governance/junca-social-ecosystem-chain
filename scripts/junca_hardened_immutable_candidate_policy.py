#!/usr/bin/env python3
"""Validate the authorized hardened immutable Public Testnet candidate policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "junca-hardened-immutable-candidate-policy/v1"
NETWORK = "Public Testnet"
ENVIRONMENT = "public-testnet"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
VALIDATOR_IDS = ["validator-01", "validator-02", "validator-03"]
REQUIRED_RUNTIME_CONTRACT = {
    "validator-runtime",
    "explorer-runtime",
    "read-only-rpc-runtime",
    "systemd-units",
    "non-root-runtime-identity",
    "boot-auto-start",
    "required-port-listen",
    "health-endpoints",
    "retained-ebs-state-recovery",
    "genesis-runtime-digest-binding",
    "source-ami-manifest-request-binding",
    "restart-acceptance",
    "fail-closed-startup",
}
REQUIRED_ACCEPTANCE_GATES = {
    "new-immutable-ami",
    "pre-rollout-baseline",
    "manifest",
    "terraform-no-destroy",
    "validator-01",
    "validator-02",
    "validator-03",
    "same-finalized-head",
    "quorum-3-of-3",
    "continuous-block-production",
    "explorer-health-rpc-readback",
    "canonical-endpoint-publication",
    "restart-failure-recovery",
    "24-hour-soak",
    "release-evidence",
}
BOUNDARIES = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
    "public_rpc_read_only": True,
    "transaction_submission_enabled": False,
    "mainnet_activation_authorized": False,
}


class HardenedCandidatePolicyError(ValueError):
    """Raised when release policy or candidate reuse violates the contract."""


def canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    payload = dict(policy)
    payload.pop("policy_sha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_policy(policy: Mapping[str, Any]) -> dict[str, str]:
    required_fields = {
        "schema_version",
        "state",
        "network",
        "environment",
        "minimum_hardened_main_commit",
        "migration_binding",
        "retired_candidates",
        "required_runtime_contract",
        "rolling_release",
        "acceptance",
        "boundaries",
        "policy_sha256",
    }
    if set(policy) != required_fields:
        raise HardenedCandidatePolicyError("policy fields do not match v1")
    if policy["schema_version"] != SCHEMA_VERSION:
        raise HardenedCandidatePolicyError("schema_version mismatch")
    if policy["state"] != "AUTHORIZED":
        raise HardenedCandidatePolicyError("policy is not authorized")
    if policy["network"] != NETWORK or policy["environment"] != ENVIRONMENT:
        raise HardenedCandidatePolicyError("network or environment mismatch")
    minimum = str(policy["minimum_hardened_main_commit"])
    if not HEX_40.fullmatch(minimum):
        raise HardenedCandidatePolicyError("minimum hardened commit is invalid")

    migration = policy["migration_binding"]
    if not isinstance(migration, Mapping) or set(migration) != {
        "run_id",
        "evidence_sha256",
    }:
        raise HardenedCandidatePolicyError("migration binding is invalid")
    migration_run_id = str(migration["run_id"])
    migration_digest = str(migration["evidence_sha256"])
    if not RUN_ID.fullmatch(migration_run_id):
        raise HardenedCandidatePolicyError("migration run ID is invalid")
    if not HEX_64.fullmatch(migration_digest):
        raise HardenedCandidatePolicyError("migration evidence digest is invalid")

    retired = policy["retired_candidates"]
    if not isinstance(retired, list) or not retired:
        raise HardenedCandidatePolicyError(
            "at least one retired candidate is required"
        )
    retired_request_digests: list[str] = []
    retired_ami_runs: list[str] = []
    retired_sources: list[str] = []
    for item in retired:
        if not isinstance(item, Mapping) or set(item) != {
            "candidate_id",
            "source_commit",
            "request_sha256",
            "ami_run_id",
            "manifest_gate_run_id",
            "preserve_for_audit",
            "acceptance_eligible",
            "foundation_resume_allowed",
            "reason",
        }:
            raise HardenedCandidatePolicyError(
                "retired candidate fields are invalid"
            )
        source = str(item["source_commit"])
        request_digest = str(item["request_sha256"])
        ami_run = str(item["ami_run_id"])
        manifest_run = str(item["manifest_gate_run_id"])
        if not HEX_40.fullmatch(source) or not HEX_64.fullmatch(request_digest):
            raise HardenedCandidatePolicyError("retired provenance is invalid")
        if not RUN_ID.fullmatch(ami_run) or not RUN_ID.fullmatch(manifest_run):
            raise HardenedCandidatePolicyError("retired run binding is invalid")
        if item["preserve_for_audit"] is not True:
            raise HardenedCandidatePolicyError(
                "retired candidate must remain auditable"
            )
        if item["acceptance_eligible"] is not False:
            raise HardenedCandidatePolicyError(
                "retired candidate cannot be acceptance eligible"
            )
        if item["foundation_resume_allowed"] is not False:
            raise HardenedCandidatePolicyError(
                "retired candidate resume must be disabled"
            )
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise HardenedCandidatePolicyError("retirement reason is required")
        retired_request_digests.append(request_digest)
        retired_ami_runs.append(ami_run)
        retired_sources.append(source)
    if len(set(retired_request_digests)) != len(retired_request_digests):
        raise HardenedCandidatePolicyError("retired request digest is duplicated")
    if len(set(retired_ami_runs)) != len(retired_ami_runs):
        raise HardenedCandidatePolicyError("retired AMI run is duplicated")

    contract = policy["required_runtime_contract"]
    if not isinstance(contract, list) or set(contract) != REQUIRED_RUNTIME_CONTRACT:
        raise HardenedCandidatePolicyError("runtime contract is incomplete")
    if len(contract) != len(set(contract)):
        raise HardenedCandidatePolicyError(
            "runtime contract contains duplicates"
        )

    rolling = policy["rolling_release"]
    if not isinstance(rolling, Mapping) or rolling != {
        "strategy": "one-validator-at-a-time",
        "validator_order": VALIDATOR_IDS,
        "max_validator_replacements_per_apply": 1,
        "terraform_destroy_allowed": False,
        "parallel_replacement_allowed": False,
        "preserve_terraform_state": True,
        "preserve_retained_ebs": True,
        "require_same_finalized_head_before_next": True,
        "require_quorum": "3/3",
        "require_healthy_public_gateway": True,
    }:
        raise HardenedCandidatePolicyError("rolling release policy mismatch")

    acceptance = policy["acceptance"]
    if not isinstance(acceptance, Mapping) or set(acceptance) != {
        "required_gates",
        "final_marker",
    }:
        raise HardenedCandidatePolicyError("acceptance policy is invalid")
    gates = acceptance["required_gates"]
    if not isinstance(gates, list) or set(gates) != REQUIRED_ACCEPTANCE_GATES:
        raise HardenedCandidatePolicyError("acceptance gates are incomplete")
    if len(gates) != len(set(gates)):
        raise HardenedCandidatePolicyError(
            "acceptance gates contain duplicates"
        )
    if acceptance["final_marker"] != "PUBLIC_TESTNET_RUNTIME_ACCEPTED":
        raise HardenedCandidatePolicyError(
            "final acceptance marker mismatch"
        )
    if policy["boundaries"] != BOUNDARIES:
        raise HardenedCandidatePolicyError("safety boundary mismatch")

    expected_digest = canonical_policy_sha256(policy)
    if policy["policy_sha256"] != expected_digest:
        raise HardenedCandidatePolicyError("policy_sha256 mismatch")

    return {
        "policy_sha256": expected_digest,
        "minimum_hardened_main_commit": minimum,
        "migration_run_id": migration_run_id,
        "migration_evidence_sha256": migration_digest,
        "retired_request_sha256_csv": ",".join(retired_request_digests),
        "retired_ami_run_id_csv": ",".join(retired_ami_runs),
        "retired_source_commit_csv": ",".join(retired_sources),
    }


def reject_retired_request(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    outputs = validate_policy(policy)
    retired_requests = set(outputs["retired_request_sha256_csv"].split(","))
    retired_runs = set(outputs["retired_ami_run_id_csv"].split(","))
    retired_sources = set(outputs["retired_source_commit_csv"].split(","))
    if str(request.get("request_sha256", "")) in retired_requests:
        raise HardenedCandidatePolicyError(
            "retired request digest is not eligible"
        )
    if str(request.get("ami_run_id", "")) in retired_runs:
        raise HardenedCandidatePolicyError("retired AMI run cannot be resumed")
    if str(request.get("source_commit", "")) in retired_sources:
        raise HardenedCandidatePolicyError(
            "retired source commit is not eligible"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--candidate-source-commit")
    parser.add_argument("--candidate-request-sha256")
    parser.add_argument("--candidate-ami-run-id")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise HardenedCandidatePolicyError("policy must be a JSON object")
    outputs = validate_policy(policy)

    if args.request:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise HardenedCandidatePolicyError("request must be a JSON object")
        reject_retired_request(request, policy)

    synthetic_request = {
        "source_commit": args.candidate_source_commit or "",
        "request_sha256": args.candidate_request_sha256 or "",
        "ami_run_id": args.candidate_ami_run_id or "",
    }
    if any(synthetic_request.values()):
        reject_retired_request(synthetic_request, policy)

    rendered = "".join(f"{key}={value}\n" for key, value in outputs.items())
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
