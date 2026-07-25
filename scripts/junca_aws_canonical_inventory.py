#!/usr/bin/env python3
"""Collect redacted AWS binding candidates for the JUNCA public testnet."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


class InventoryError(RuntimeError):
    """Raised when the canonical AWS inventory cannot be read safely."""


AwsRunner = Callable[[Sequence[str]], Any]


def aws_json(arguments: Sequence[str]) -> Any:
    process = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise InventoryError(
            f"AWS readback failed for {arguments[0]} {arguments[1]}: "
            f"{process.stderr.strip()[:500]}"
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise InventoryError("AWS readback returned invalid JSON") from exc


def _tags(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("Key")): str(item.get("Value"))
        for item in items
        if item.get("Key") is not None
    }


def build_inventory(*, region: str, run: AwsRunner = aws_json) -> dict[str, Any]:
    identity = run(["sts", "get-caller-identity"])
    account_id = str(identity.get("Account", ""))
    if len(account_id) != 12 or not account_id.isdigit():
        raise InventoryError("AWS account identity is invalid")

    vpcs = run(["ec2", "describe-vpcs", "--region", region]).get("Vpcs", [])
    subnets = run(["ec2", "describe-subnets", "--region", region]).get("Subnets", [])
    zones = run(
        [
            "route53",
            "list-hosted-zones-by-name",
            "--dns-name",
            "jaios-governance.org",
            "--max-items",
            "10",
        ]
    ).get("HostedZones", [])
    aliases = run(["kms", "list-aliases", "--region", region, "--limit", "100"]).get(
        "Aliases", []
    )
    images = run(
        [
            "ec2",
            "describe-images",
            "--owners",
            "self",
            "--region",
            region,
            "--filters",
            "Name=state,Values=available",
        ]
    ).get("Images", [])
    repositories = run(["ecr", "describe-repositories", "--region", region]).get(
        "repositories", []
    )
    buckets = run(["s3api", "list-buckets"]).get("Buckets", [])
    tables = run(["dynamodb", "list-tables", "--region", region]).get(
        "TableNames", []
    )

    return {
        "schema_version": "junca-aws-canonical-inventory/v1",
        "chain": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "network": "Public Testnet / No Monetary Value",
        "account_id": account_id,
        "assumed_role_arn": str(identity.get("Arn", "")),
        "region": region,
        "vpcs": [
            {
                "vpc_id": item.get("VpcId"),
                "cidr": item.get("CidrBlock"),
                "is_default": item.get("IsDefault", False),
                "tags": _tags(item.get("Tags", [])),
            }
            for item in vpcs
        ],
        "subnets": [
            {
                "subnet_id": item.get("SubnetId"),
                "vpc_id": item.get("VpcId"),
                "availability_zone": item.get("AvailabilityZone"),
                "cidr": item.get("CidrBlock"),
                "public_ip_on_launch": item.get("MapPublicIpOnLaunch", False),
                "tags": _tags(item.get("Tags", [])),
            }
            for item in subnets
        ],
        "hosted_zones": [
            {
                "zone_id": str(item.get("Id", "")).removeprefix("/hostedzone/"),
                "name": item.get("Name"),
                "private": item.get("Config", {}).get("PrivateZone", False),
            }
            for item in zones
            if str(item.get("Name", "")).rstrip(".") == "jaios-governance.org"
        ],
        "kms_aliases": [
            {
                "alias": item.get("AliasName"),
                "target_key_id": item.get("TargetKeyId"),
            }
            for item in aliases
            if str(item.get("AliasName", "")).startswith("alias/junca")
        ],
        "owned_amis": [
            {
                "image_id": item.get("ImageId"),
                "name": item.get("Name"),
                "creation_date": item.get("CreationDate"),
                "architecture": item.get("Architecture"),
            }
            for item in images
        ],
        "ecr_repositories": [
            {
                "name": item.get("repositoryName"),
                "uri": item.get("repositoryUri"),
            }
            for item in repositories
            if "junca" in str(item.get("repositoryName", "")).lower()
        ],
        "state_bucket_candidates": [
            item.get("Name")
            for item in buckets
            if "junca" in str(item.get("Name", "")).lower()
            and any(token in str(item.get("Name", "")).lower() for token in ("state", "tf"))
        ],
        "lock_table_candidates": [
            name
            for name in tables
            if "junca" in str(name).lower()
            and any(token in str(name).lower() for token in ("lock", "terraform"))
        ],
        "private_key_material_included": False,
        "deployment_performed": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evidence = build_inventory(region=args.region)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
