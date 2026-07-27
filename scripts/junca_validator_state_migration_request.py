#!/usr/bin/env python3
"""Validate one signed Public Testnet validator-state migration request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-validator-state-migration-request/v1"
APPROVAL_PHRASE = "PUBLIC_TESTNET_VALIDATOR_STATE_MIGRATION"
NETWORK = "Public Testnet"
ENVIRONMENT = "public-testnet"
AWS_ACCOUNT_ID = "595710543956"
AWS_REGION = "us-east-1"
STATE_BUCKET_NAME = (
    "junca-social-ecosystem-chain-tfstate-595710543956-us-east-1"
)
LOCK_TABLE_NAME = "junca-social-ecosystem-chain-testnet-lock"
DEPLOYMENT_ROLE_ARN = (
    "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment"
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_BOUNDARIES = {
    "bootstrap_changed": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
REQUEST_FIELDS = {
    "schema_version",
    "state",
    "network",
    "environment",
    "approval_phrase",
    "aws_account_id",
    "aws_region",
    "terraform_state_bucket",
    "dynamodb_lock_table",
    "deployment_role_arn",
    "boundaries",
    "request_sha256",
}


class RequestValidationError(ValueError):
    """Raised when a migration request fails the exact fail-closed contract."""


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
    if set(request) != REQUEST_FIELDS:
        raise RequestValidationError(
            "request fields do not match the migration v1 contract"
        )
    expected = {
        "schema_version": SCHEMA_VERSION,
        "state": "AUTHORIZED",
        "network": NETWORK,
        "environment": ENVIRONMENT,
        "approval_phrase": APPROVAL_PHRASE,
        "aws_account_id": AWS_ACCOUNT_ID,
        "aws_region": AWS_REGION,
        "terraform_state_bucket": STATE_BUCKET_NAME,
        "dynamodb_lock_table": LOCK_TABLE_NAME,
        "deployment_role_arn": DEPLOYMENT_ROLE_ARN,
        "boundaries": EXPECTED_BOUNDARIES,
    }
    for field, value in expected.items():
        if request[field] != value:
            raise RequestValidationError(f"{field} mismatch")
    request_sha256 = str(request["request_sha256"])
    if not HEX_64.fullmatch(request_sha256):
        raise RequestValidationError(
            "request_sha256 must be lowercase SHA-256"
        )
    if request_sha256 != canonical_request_sha256(request):
        raise RequestValidationError("request_sha256 mismatch")
    return {"request_sha256": request_sha256}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    raw = json.loads(args.request.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RequestValidationError("request must be a JSON object")
    outputs = validate_request(raw)
    rendered = f"request_sha256={outputs['request_sha256']}\n"
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
