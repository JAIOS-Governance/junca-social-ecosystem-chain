#!/usr/bin/env python3
"""Fail-closed admission for the fixed Public Testnet validator replacement.

This module does not mutate AWS.  It validates the immutable Security
Bootstrap contract, an exact-three live fleet readback, and the bounded
replacement request before producing the only accepted
``StartAutomationExecution`` payload for ``JuncaPTReplaceValidator``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence


class ContractError(ValueError):
    """Raised when replacement admission must fail closed."""


SCHEMA = "junca-public-testnet-validator-replacement-contract/v1"
AUTOMATION_DOCUMENT = "JuncaPTReplaceValidator"
REGION = "us-east-1"
MAX_START_HORIZON_SECONDS = 3600

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
AMI_RE = re.compile(r"^ami-[0-9a-f]{8,17}$")
EC2_ID_PATTERNS = {
    "launch_template_id": re.compile(r"^lt-[0-9a-f]{8,17}$"),
    "subnet_id": re.compile(r"^subnet-[0-9a-f]{8,17}$"),
    "security_group_id": re.compile(r"^sg-[0-9a-f]{8,17}$"),
    "retained_volume_id": re.compile(r"^vol-[0-9a-f]{8,17}$"),
    "instance_id": re.compile(r"^i-[0-9a-f]{8,17}$"),
}
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
PRIVATE_IPS = {
    "validator-01": "10.67.16.10",
    "validator-02": "10.67.32.10",
    "validator-03": "10.67.48.10",
}
SAFETY = {
    "MainnetChanged": "false",
    "AssetsMoved": "false",
    "BridgeActivated": "false",
    "MainnetActivationAuthorized": "false",
}

ROOT_KEYS = {
    "schema",
    "account_id",
    "region",
    "automation_document_name",
    "automation_document_version",
    "automation_document_sha256",
    "automation_role_arn",
    "lock_table_arn",
    "evidence_bucket_arn",
    "validators",
    "safety",
}
VALIDATOR_KEYS = {
    "validator_id",
    "launch_template_id",
    "launch_template_version",
    "subnet_id",
    "availability_zone",
    "private_ip",
    "instance_profile_arn",
    "security_group_id",
    "retained_volume_id",
    "target_group_arns",
    "kms_key_arn",
    "user_data_sha256",
    "launch_template_data_sha256",
}
REQUEST_KEYS = {
    "ValidatorId",
    "AmiId",
    "ExpectedArtifactSha256",
    "ExpectedGenesisSha256",
    "ReleaseManifestSha256",
    "SourceCommit",
    "SlotEpochSeconds",
}
FLEET_KEYS = {
    "validator_id",
    "instance_id",
    "ami_id",
    "state",
    "private_ip",
    "subnet_id",
    "availability_zone",
    "instance_profile_arn",
    "security_group_ids",
    "volume_id",
    "target_group_arns",
    "public_ip",
    "tags",
}
REQUIRED_TAGS = {
    "Project": "JUNCA Social Ecosystem Chain",
    "Governance": "JAIOS Institutional Governance",
    "Network": "Public Testnet",
    "MonetaryUse": "None",
    **SAFETY,
}


def _fail(message: str) -> None:
    raise ContractError(message)


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _fail(f"{label} keys differ: missing={missing}, extra={extra}")


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    return value


def _match(value: Any, pattern: re.Pattern[str], *, label: str) -> str:
    text = _string(value, label=label)
    if pattern.fullmatch(text) is None:
        _fail(f"{label} is not canonical")
    return text


def _positive_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _validate_account_arn(
    value: Any,
    *,
    account_id: str,
    service: str,
    resource_pattern: str,
    label: str,
    region: str = "",
) -> str:
    text = _string(value, label=label)
    expected = re.compile(
        rf"^arn:aws:{re.escape(service)}:{re.escape(region)}:"
        rf"{re.escape(account_id)}:{resource_pattern}$"
    )
    if expected.fullmatch(text) is None:
        _fail(f"{label} is outside the bound account/region/resource")
    return text


def validate_manifest(raw: Any) -> dict[str, Any]:
    manifest = dict(_mapping(raw, label="manifest"))
    _exact_keys(manifest, ROOT_KEYS, label="manifest")
    if manifest["schema"] != SCHEMA:
        _fail("manifest schema is not accepted")

    account_id = _match(
        manifest["account_id"], re.compile(r"^[0-9]{12}$"), label="account_id"
    )
    if manifest["region"] != REGION:
        _fail(f"region must be {REGION}")
    if manifest["automation_document_name"] != AUTOMATION_DOCUMENT:
        _fail("automation document name is not accepted")
    _positive_integer(
        manifest["automation_document_version"],
        label="automation_document_version",
    )
    _match(
        manifest["automation_document_sha256"],
        SHA256_RE,
        label="automation_document_sha256",
    )
    expected_role = (
        f"arn:aws:iam::{account_id}:role/"
        "JuncaPTValidatorReplaceAutomationRole"
    )
    if manifest["automation_role_arn"] != expected_role:
        _fail("automation_role_arn is not the fixed execution role")
    expected_lock = (
        f"arn:aws:dynamodb:{REGION}:{account_id}:"
        "table/JuncaPTValidatorReplacementLock"
    )
    if manifest["lock_table_arn"] != expected_lock:
        _fail("lock_table_arn is not the fixed serialization lock")
    expected_bucket = (
        "arn:aws:s3:::"
        f"junca-public-testnet-replacement-evidence-{account_id}"
    )
    if manifest["evidence_bucket_arn"] != expected_bucket:
        _fail("evidence_bucket_arn is not the fixed evidence destination")
    if manifest["safety"] != SAFETY:
        _fail("all constitutional safety boundaries must remain false")

    validators_raw = manifest["validators"]
    if not isinstance(validators_raw, list) or len(validators_raw) != 3:
        _fail("validators must contain exactly three contracts")
    validators: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_azs: set[str] = set()
    unique_fields = {
        "launch_template_id": set(),
        "subnet_id": set(),
        "private_ip": set(),
        "instance_profile_arn": set(),
        "retained_volume_id": set(),
        "kms_key_arn": set(),
    }

    for index, raw_validator in enumerate(validators_raw, start=1):
        validator = dict(
            _mapping(raw_validator, label=f"validators[{index - 1}]")
        )
        _exact_keys(
            validator,
            VALIDATOR_KEYS,
            label=f"validators[{index - 1}]",
        )
        validator_id = validator["validator_id"]
        expected_id = f"validator-{index:02d}"
        if validator_id != expected_id:
            _fail("validators must be ordered validator-01..validator-03")
        if validator_id in seen_ids:
            _fail("validator identity is duplicated")
        seen_ids.add(validator_id)

        for field, pattern in EC2_ID_PATTERNS.items():
            if field in validator:
                _match(
                    validator[field],
                    pattern,
                    label=f"{validator_id}.{field}",
                )
        _positive_integer(
            validator["launch_template_version"],
            label=f"{validator_id}.launch_template_version",
        )
        az = _string(
            validator["availability_zone"],
            label=f"{validator_id}.availability_zone",
        )
        if re.fullmatch(r"us-east-1[a-f]", az) is None or az in seen_azs:
            _fail("availability zones must be three distinct us-east-1 zones")
        seen_azs.add(az)
        if validator["private_ip"] != PRIVATE_IPS[validator_id]:
            _fail(f"{validator_id}.private_ip is not the fixed address")

        expected_profile = (
            f"arn:aws:iam::{account_id}:instance-profile/"
            f"junca-social-ecosystem-chain-testnet-validator-{index}"
        )
        if validator["instance_profile_arn"] != expected_profile:
            _fail(f"{validator_id}.instance_profile_arn is not fixed")
        _validate_account_arn(
            validator["kms_key_arn"],
            account_id=account_id,
            service="kms",
            region=REGION,
            resource_pattern=r"key/[0-9a-f-]{36}",
            label=f"{validator_id}.kms_key_arn",
        )
        _match(
            validator["user_data_sha256"],
            SHA256_RE,
            label=f"{validator_id}.user_data_sha256",
        )
        _match(
            validator["launch_template_data_sha256"],
            SHA256_RE,
            label=f"{validator_id}.launch_template_data_sha256",
        )

        target_groups = validator["target_group_arns"]
        if not isinstance(target_groups, list) or len(target_groups) != 2:
            _fail(f"{validator_id} must bind exactly two target groups")
        target_kinds: set[str] = set()
        for target in target_groups:
            text = _string(target, label=f"{validator_id}.target_group_arns")
            match = re.fullmatch(
                rf"arn:aws:elasticloadbalancing:{REGION}:{account_id}:"
                r"targetgroup/junca-testnet-(rpc|explorer)/[0-9a-f]{16}",
                text,
            )
            if match is None:
                _fail(f"{validator_id} has an unapproved target group")
            target_kinds.add(match.group(1))
        if target_kinds != {"rpc", "explorer"}:
            _fail(f"{validator_id} target groups must be rpc and explorer")

        for field, values in unique_fields.items():
            item = validator[field]
            if item in values:
                _fail(f"{field} must be unique per validator")
            values.add(item)
        validators.append(validator)

    manifest["validators"] = validators
    return manifest


def validate_request(raw: Any, *, now: int) -> dict[str, Any]:
    request = dict(_mapping(raw, label="request"))
    _exact_keys(request, REQUEST_KEYS, label="request")
    if request["ValidatorId"] not in VALIDATOR_IDS:
        _fail("ValidatorId is not accepted")
    _match(request["AmiId"], AMI_RE, label="AmiId")
    for name in (
        "ExpectedArtifactSha256",
        "ExpectedGenesisSha256",
        "ReleaseManifestSha256",
    ):
        _match(request[name], SHA256_RE, label=name)
    _match(request["SourceCommit"], COMMIT_RE, label="SourceCommit")
    epoch = _positive_integer(
        request["SlotEpochSeconds"],
        label="SlotEpochSeconds",
    )
    if epoch % 30 != 0:
        _fail("SlotEpochSeconds must be 30-second aligned")
    if epoch <= now:
        _fail("SlotEpochSeconds must be in the future")
    if epoch > now + MAX_START_HORIZON_SECONDS:
        _fail("SlotEpochSeconds exceeds the bounded start horizon")
    return request


def validate_fleet(
    raw: Any,
    *,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) != 3:
        _fail("fleet readback must contain exactly three validators")
    contracts = {
        item["validator_id"]: item for item in manifest["validators"]
    }
    fleet: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_instances: set[str] = set()
    for index, raw_instance in enumerate(raw):
        instance = dict(_mapping(raw_instance, label=f"fleet[{index}]"))
        _exact_keys(instance, FLEET_KEYS, label=f"fleet[{index}]")
        validator_id = instance["validator_id"]
        if validator_id not in contracts or validator_id in seen_ids:
            _fail("fleet identity must resolve exactly once")
        seen_ids.add(validator_id)
        contract = contracts[validator_id]
        instance_id = _match(
            instance["instance_id"],
            EC2_ID_PATTERNS["instance_id"],
            label=f"{validator_id}.instance_id",
        )
        if instance_id in seen_instances:
            _fail("fleet instance is duplicated")
        seen_instances.add(instance_id)
        _match(instance["ami_id"], AMI_RE, label=f"{validator_id}.ami_id")
        if instance["state"] != "running":
            _fail(f"{validator_id} must be running before replacement")
        comparisons = {
            "private_ip": "private_ip",
            "subnet_id": "subnet_id",
            "availability_zone": "availability_zone",
            "instance_profile_arn": "instance_profile_arn",
            "volume_id": "retained_volume_id",
            "target_group_arns": "target_group_arns",
        }
        for live_field, contract_field in comparisons.items():
            if instance[live_field] != contract[contract_field]:
                _fail(f"{validator_id}.{live_field} differs from contract")
        if instance["security_group_ids"] != [contract["security_group_id"]]:
            _fail(f"{validator_id}.security_group_ids differs from contract")
        if instance["public_ip"] is not None:
            _fail(f"{validator_id} must not have a public IP")
        tags = _mapping(instance["tags"], label=f"{validator_id}.tags")
        if tags.get("ValidatorId") != validator_id:
            _fail(f"{validator_id} identity tag differs")
        for key, expected in REQUIRED_TAGS.items():
            if tags.get(key) != expected:
                _fail(f"{validator_id} tag {key} differs")
        fleet.append(instance)
    if seen_ids != set(VALIDATOR_IDS):
        _fail("fleet is not the exact-three validator set")
    return sorted(fleet, key=lambda item: item["validator_id"])


def build_admission(
    manifest_raw: Any,
    request_raw: Any,
    fleet_raw: Any,
    *,
    now: int,
) -> dict[str, Any]:
    manifest = validate_manifest(manifest_raw)
    request = validate_request(request_raw, now=now)
    fleet = validate_fleet(fleet_raw, manifest=manifest)
    selected = next(
        item
        for item in fleet
        if item["validator_id"] == request["ValidatorId"]
    )
    if selected["ami_id"] == request["AmiId"]:
        _fail("candidate AMI equals the selected validator's current AMI")

    manifest_sha256 = _sha256(manifest)
    fleet_sha256 = _sha256(fleet)
    request_sha256 = _sha256(request)
    token_source = {
        "manifest_sha256": manifest_sha256,
        "fleet_sha256": fleet_sha256,
        "request_sha256": request_sha256,
    }
    client_token = hashlib.sha256(_canonical_json(token_source)).hexdigest()
    parameter_order = (
        "ValidatorId",
        "AmiId",
        "ExpectedArtifactSha256",
        "ExpectedGenesisSha256",
        "ReleaseManifestSha256",
        "SourceCommit",
        "SlotEpochSeconds",
    )
    parameters = {
        key: [str(request[key])]
        for key in parameter_order
    }
    return {
        "schema": "junca-public-testnet-validator-replacement-admission/v1",
        "decision": "ACCEPTED_FOR_FIXED_AUTOMATION_START",
        "manifest_sha256": manifest_sha256,
        "fleet_readback_sha256": fleet_sha256,
        "request_sha256": request_sha256,
        "selected_old_instance_id": selected["instance_id"],
        "selected_old_ami_id": selected["ami_id"],
        "serialization_lock": {
            "table_arn": manifest["lock_table_arn"],
            "key": "global",
            "validator_id": request["ValidatorId"],
            "client_token": client_token,
            "expires_not_before": request["SlotEpochSeconds"] + 3600,
        },
        "aws_request": {
            "DocumentName": manifest["automation_document_name"],
            "DocumentVersion": str(
                manifest["automation_document_version"]
            ),
            "Parameters": parameters,
            "ClientToken": client_token,
        },
        "required_independent_readback": {
            "document_sha256": manifest["automation_document_sha256"],
            "automation_role_arn": manifest["automation_role_arn"],
            "exact_old_instance_id": selected["instance_id"],
            "exact_retained_volume_id": next(
                item["retained_volume_id"]
                for item in manifest["validators"]
                if item["validator_id"] == request["ValidatorId"]
            ),
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        },
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--fleet-readback", type=Path, required=True)
    parser.add_argument("--now", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        result = build_admission(
            _load_json(args.manifest),
            _load_json(args.request),
            _load_json(args.fleet_readback),
            now=int(time.time()) if args.now is None else args.now,
        )
    except ContractError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
