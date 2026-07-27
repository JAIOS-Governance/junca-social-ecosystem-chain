#!/usr/bin/env python3
"""Validate one repository-authorized immutable validator AMI build request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-validator-ami-build-request/v1"
APPROVAL_PHRASE = "PUBLIC_TESTNET_IMMUTABLE_AMI_BUILD"
NETWORK = "Public Testnet"
ENVIRONMENT = "public-testnet"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
EXPECTED_BOUNDARIES = {
    "terraform_state_changed": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
OUTPUT_FIELDS = (
    "source_run_id",
    "source_commit",
    "node_artifact_name",
    "genesis_artifact_name",
    "node_sha256",
    "genesis_sha256",
    "request_sha256",
)


class RequestValidationError(ValueError):
    """Raised when a request does not satisfy the fail-closed contract."""


def canonical_request_sha256(request: Mapping[str, Any]) -> str:
    payload = dict(request)
    payload.pop("request_sha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_request(request: Mapping[str, Any]) -> dict[str, str]:
    if set(request) != {
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
    }:
        raise RequestValidationError("request fields do not match the v1 contract")
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

    expected_node_artifact = f"junca-validator-runtime-{source_run_id}"
    expected_genesis_artifact = f"junca-validator-genesis-{source_run_id}"
    if request["node_artifact_name"] != expected_node_artifact:
        raise RequestValidationError("node artifact is not bound to source_run_id")
    if request["genesis_artifact_name"] != expected_genesis_artifact:
        raise RequestValidationError("genesis artifact is not bound to source_run_id")

    expected_digest = canonical_request_sha256(request)
    if request["request_sha256"] != expected_digest:
        raise RequestValidationError("request_sha256 mismatch")

    return {field: str(request[field]) for field in OUTPUT_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--seal-missing-digest",
        action="store_true",
        help="Set an empty request_sha256 before validating a manual request.",
    )
    args = parser.parse_args()

    raw = json.loads(args.request.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RequestValidationError("request must be a JSON object")
    if args.seal_missing_digest:
        if raw.get("request_sha256") not in ("", None):
            raise RequestValidationError("manual request digest must start empty")
        raw["request_sha256"] = canonical_request_sha256(raw)
    outputs = validate_request(raw)
    rendered = "".join(f"{key}={outputs[key]}\n" for key in OUTPUT_FIELDS)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
