#!/usr/bin/env python3
"""Validate one repository-authorized validator release request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-validator-ami-build-request/v1"
APPROVAL_PHRASE = "PUBLIC_TESTNET_IMMUTABLE_AMI_BUILD"
FOUNDATION_RESUME_SCHEMA_VERSION = (
    "junca-validator-foundation-resume-request/v1"
)
FOUNDATION_RESUME_APPROVAL_PHRASE = "PUBLIC_TESTNET_ROLLOUT"
FOUNDATION_RESUME_MODE = "foundation-resume-only"
FOUNDATION_WORKFLOW = (
    ".github/workflows/junca-validator-foundation-release.yml"
)
NETWORK = "Public Testnet"
ENVIRONMENT = "public-testnet"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
NONCE = re.compile(r"^[a-z0-9][a-z0-9-]{15,127}$")
EXPECTED_BOUNDARIES = {
    "terraform_state_changed": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
EXPECTED_FOUNDATION_RESUME_BOUNDARIES = {
    "rebuild_ami": False,
    "rebuild_manifest": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
OUTPUT_FIELDS = (
    "request_type",
    "source_run_id",
    "source_commit",
    "node_artifact_name",
    "genesis_artifact_name",
    "node_sha256",
    "genesis_sha256",
    "request_sha256",
    "migration_run_id",
    "migration_evidence_sha256",
    "ami_run_id",
    "manifest_gate_run_id",
    "resume_run_id",
    "renew_expired_epoch",
    "renewal_preserve_prefix_count",
    "target_workflow",
    "one_shot_nonce",
)
RUNTIME_REQUEST_FIELDS = {
    "schema_version",
    "state",
    "network",
    "environment",
    "approval_phrase",
    "source_run_id",
    "source_commit",
    "node_artifact_name",
    "genesis_artifact_name",
    "node_sha256",
    "genesis_sha256",
    "boundaries",
    "request_sha256",
}
MIGRATION_BINDING_FIELDS = {
    "migration_run_id",
    "migration_evidence_sha256",
}
FOUNDATION_RESUME_REQUEST_FIELDS = {
    "schema_version",
    "state",
    "network",
    "environment",
    "mode",
    "approval_phrase",
    "ami_run_id",
    "manifest_gate_run_id",
    "resume_run_id",
    "target_workflow",
    "one_shot_nonce",
    "boundaries",
    "request_sha256",
}
FOUNDATION_RESUME_RENEWAL_FIELDS = {
    "renew_expired_epoch",
    "renewal_preserve_prefix_count",
}


class RequestValidationError(ValueError):
    """Raised when a request does not satisfy the fail-closed contract."""


def canonical_request_sha256(request: Mapping[str, Any]) -> str:
    # The runtime artifact identity is intentionally independent of the
    # completed durable-state migration.  This preserves the already approved
    # immutable AMI request digest while a later signed request binds the exact
    # migration run and evidence into the release phase.
    excluded = {"request_sha256"}
    if request.get("schema_version") == SCHEMA_VERSION:
        excluded |= MIGRATION_BINDING_FIELDS
    payload = {key: value for key, value in request.items() if key not in excluded}
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_request(
    request: Mapping[str, Any],
    *,
    require_migration_binding: bool = False,
) -> dict[str, str]:
    if request.get("schema_version") == FOUNDATION_RESUME_SCHEMA_VERSION:
        return _validate_foundation_resume_request(request)

    fields = set(request)
    if fields not in (
        RUNTIME_REQUEST_FIELDS,
        RUNTIME_REQUEST_FIELDS | MIGRATION_BINDING_FIELDS,
    ):
        raise RequestValidationError("request fields do not match the v1 contract")
    has_migration_binding = MIGRATION_BINDING_FIELDS <= fields
    if require_migration_binding and not has_migration_binding:
        raise RequestValidationError("completed migration binding is required")
    if request["schema_version"] != SCHEMA_VERSION:
        raise RequestValidationError("schema_version mismatch")
    if request["state"] != "AUTHORIZED":
        raise RequestValidationError("request is not authorized")
    if request["network"] != NETWORK:
        raise RequestValidationError("network mismatch")
    if request["environment"] != ENVIRONMENT:
        raise RequestValidationError("environment mismatch")
    if request["approval_phrase"] != APPROVAL_PHRASE:
        raise RequestValidationError("approval phrase mismatch")
    if request["boundaries"] != EXPECTED_BOUNDARIES:
        raise RequestValidationError("release boundary mismatch")

    source_run_id = str(request["source_run_id"])
    source_commit = str(request["source_commit"])
    node_sha256 = str(request["node_sha256"])
    genesis_sha256 = str(request["genesis_sha256"])
    if not RUN_ID.fullmatch(source_run_id):
        raise RequestValidationError("source_run_id must be a positive integer")
    if not HEX_40.fullmatch(source_commit):
        raise RequestValidationError("source_commit must be lowercase SHA-1")
    if not HEX_64.fullmatch(node_sha256):
        raise RequestValidationError("node_sha256 must be lowercase SHA-256")
    if not HEX_64.fullmatch(genesis_sha256):
        raise RequestValidationError("genesis_sha256 must be lowercase SHA-256")
    if has_migration_binding:
        migration_run_id = str(request["migration_run_id"])
        migration_evidence_sha256 = str(request["migration_evidence_sha256"])
        if not RUN_ID.fullmatch(migration_run_id):
            raise RequestValidationError(
                "migration_run_id must be a positive integer"
            )
        if not HEX_64.fullmatch(migration_evidence_sha256):
            raise RequestValidationError(
                "migration_evidence_sha256 must be lowercase SHA-256"
            )

    expected_node_artifact = f"junca-validator-runtime-{source_run_id}"
    expected_genesis_artifact = f"junca-validator-genesis-{source_run_id}"
    if request["node_artifact_name"] != expected_node_artifact:
        raise RequestValidationError("node artifact is not bound to source_run_id")
    if request["genesis_artifact_name"] != expected_genesis_artifact:
        raise RequestValidationError("genesis artifact is not bound to source_run_id")

    expected_digest = canonical_request_sha256(request)
    if request["request_sha256"] != expected_digest:
        raise RequestValidationError("request_sha256 mismatch")

    outputs = {field: str(request.get(field, "")) for field in OUTPUT_FIELDS}
    outputs["request_type"] = "ami-build"
    return outputs


def _validate_foundation_resume_request(
    request: Mapping[str, Any],
) -> dict[str, str]:
    request_fields = set(request)
    if request_fields not in (
        FOUNDATION_RESUME_REQUEST_FIELDS,
        FOUNDATION_RESUME_REQUEST_FIELDS | FOUNDATION_RESUME_RENEWAL_FIELDS,
    ):
        raise RequestValidationError(
            "request fields do not match the foundation resume v1 contract"
        )
    if request["state"] != "AUTHORIZED":
        raise RequestValidationError("request is not authorized")
    if request["network"] != NETWORK:
        raise RequestValidationError("network mismatch")
    if request["environment"] != ENVIRONMENT:
        raise RequestValidationError("environment mismatch")
    if request["mode"] != FOUNDATION_RESUME_MODE:
        raise RequestValidationError("foundation resume mode mismatch")
    if request["approval_phrase"] != FOUNDATION_RESUME_APPROVAL_PHRASE:
        raise RequestValidationError("approval phrase mismatch")
    if request["target_workflow"] != FOUNDATION_WORKFLOW:
        raise RequestValidationError("target workflow mismatch")
    if request["boundaries"] != EXPECTED_FOUNDATION_RESUME_BOUNDARIES:
        raise RequestValidationError("release boundary mismatch")

    for field in ("ami_run_id", "manifest_gate_run_id", "resume_run_id"):
        if not RUN_ID.fullmatch(str(request[field])):
            raise RequestValidationError(f"{field} must be a positive integer")
    if not NONCE.fullmatch(str(request["one_shot_nonce"])):
        raise RequestValidationError("one_shot_nonce format is invalid")

    renew_expired_epoch = str(request.get("renew_expired_epoch", "NONE"))
    renewal_preserve_prefix_count = str(
        request.get("renewal_preserve_prefix_count", "0")
    )
    if renew_expired_epoch not in ("NONE", "RENEW_EXPIRED_QUIESCED_EPOCH"):
        raise RequestValidationError("expired epoch renewal phrase is invalid")
    if renewal_preserve_prefix_count not in ("0", "1", "2", "3"):
        raise RequestValidationError("renewal preserve prefix count is invalid")
    if renew_expired_epoch == "NONE":
        if renewal_preserve_prefix_count != "0":
            raise RequestValidationError(
                "epoch renewal prefix requires explicit authorization"
            )
    elif renewal_preserve_prefix_count == "0":
        raise RequestValidationError(
            "expired epoch renewal requires a preserved target prefix"
        )

    expected_digest = canonical_request_sha256(request)
    if request["request_sha256"] != expected_digest:
        raise RequestValidationError("request_sha256 mismatch")

    outputs = {field: str(request.get(field, "")) for field in OUTPUT_FIELDS}
    outputs["renew_expired_epoch"] = renew_expired_epoch
    outputs["renewal_preserve_prefix_count"] = renewal_preserve_prefix_count
    outputs["request_type"] = "foundation-resume"
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--seal-missing-digest",
        action="store_true",
        help="Set an empty request_sha256 before validating a manual request.",
    )
    parser.add_argument(
        "--require-migration-binding",
        action="store_true",
        help="Require an exact completed migration run and evidence digest.",
    )
    args = parser.parse_args()

    raw = json.loads(args.request.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RequestValidationError("request must be a JSON object")
    if args.seal_missing_digest:
        if raw.get("request_sha256") not in ("", None):
            raise RequestValidationError("manual request digest must start empty")
        raw["request_sha256"] = canonical_request_sha256(raw)
    outputs = validate_request(
        raw,
        require_migration_binding=args.require_migration_binding,
    )
    rendered = "".join(f"{key}={outputs[key]}\n" for key in OUTPUT_FIELDS)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
