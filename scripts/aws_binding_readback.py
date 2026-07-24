#!/usr/bin/env python3
"""Produce redacted, fail-closed AWS binding evidence for the JUNCA public testnet."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

GOVERNANCE = "JAIOS Institutional Governance"
NETWORK = "Public Testnet / No Monetary Value"
DOMAIN = "jaios-governance.org"
ENDPOINTS = {
    "rpc": f"https://rpc.{DOMAIN}",
    "explorer": f"https://explorer.{DOMAIN}",
    "health": f"https://health.{DOMAIN}",
}


def aws_json(arguments: list[str], *, optional: bool = False) -> dict[str, Any]:
    command = ["aws", *arguments, "--output", "json", "--no-cli-pager"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        if optional:
            return {"status": "UNAVAILABLE"}
        raise RuntimeError(f"AWS readback failed: {' '.join(command[:3])}")
    return json.loads(result.stdout or "{}")


def require(value: Any, label: str) -> Any:
    if value is None or value == "" or value == []:
        raise RuntimeError(f"Required binding is absent: {label}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-northeast-1"))
    parser.add_argument("--deployment-role-arn", default=os.getenv("AWS_DEPLOYMENT_ROLE_ARN"))
    parser.add_argument("--signer-arn", action="append", default=[])
    parser.add_argument("--output", default="aws-binding-readback.json")
    args = parser.parse_args()

    identity = aws_json(["sts", "get-caller-identity"])
    account_id = require(identity.get("Account"), "AWS account ID")
    caller_arn = require(identity.get("Arn"), "AWS caller ARN")

    organization = aws_json(["organizations", "describe-organization"], optional=True)
    zones = aws_json(["ec2", "describe-availability-zones", "--region", args.region])
    available = sorted(
        z["ZoneName"] for z in zones.get("AvailabilityZones", []) if z.get("State") == "available"
    )
    if len(available) < 3:
        raise RuntimeError("Fewer than three available failure domains")

    hosted = aws_json([
        "route53", "list-hosted-zones-by-name", "--dns-name", DOMAIN, "--max-items", "1"
    ])
    candidates = [
        z for z in hosted.get("HostedZones", [])
        if z.get("Name", "").rstrip(".") == DOMAIN and not z.get("Config", {}).get("PrivateZone")
    ]
    hosted_zone = require(candidates[0] if candidates else None, "public Route53 hosted zone")
    hosted_zone_id = require(hosted_zone.get("Id", "").split("/")[-1], "hosted zone ID")
    hosted_zone_readback = aws_json(["route53", "get-hosted-zone", "--id", hosted_zone_id])
    name_servers = require(
        hosted_zone_readback.get("DelegationSet", {}).get("NameServers", []),
        "Route53 delegation name servers",
    )

    role_arn = require(args.deployment_role_arn, "deployment role ARN")
    role_name = role_arn.rsplit("/", 1)[-1]
    role = aws_json(["iam", "get-role", "--role-name", role_name]).get("Role", {})
    if role.get("Arn") != role_arn:
        raise RuntimeError("Deployment role ARN readback mismatch")

    signer_arns = args.signer_arn or [
        os.getenv("AWS_VALIDATOR_01_SIGNER_ARN", ""),
        os.getenv("AWS_VALIDATOR_02_SIGNER_ARN", ""),
        os.getenv("AWS_VALIDATOR_03_SIGNER_ARN", ""),
    ]
    signer_arns = [require(v, f"validator signer {i + 1}") for i, v in enumerate(signer_arns)]
    if len(signer_arns) != 3 or len(set(signer_arns)) != 3:
        raise RuntimeError("Exactly three distinct signer resources are required")

    signers = []
    for index, signer_arn in enumerate(signer_arns, start=1):
        key = aws_json(["kms", "describe-key", "--key-id", signer_arn, "--region", args.region]).get("KeyMetadata", {})
        if not key.get("Enabled") or key.get("KeyState") != "Enabled":
            raise RuntimeError(f"Validator signer {index} is not enabled")
        signers.append({
            "validator": f"validator-{index:02d}",
            "resource_arn": signer_arn,
            "key_id": key.get("KeyId"),
            "key_state": key.get("KeyState"),
            "key_manager": key.get("KeyManager"),
            "origin": key.get("Origin"),
        })

    evidence = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "official_chain_name": "JUNCA Social Ecosystem Chain",
        "governance": GOVERNANCE,
        "network_label": NETWORK,
        "aws": {
            "account_id": account_id,
            "caller_arn": caller_arn,
            "organization_id": organization.get("Organization", {}).get("Id"),
            "region": args.region,
            "failure_domains": available[:3],
            "deployment_role_arn": role_arn,
        },
        "dns": {
            "domain": DOMAIN,
            "hosted_zone_id": hosted_zone_id,
            "name_servers": sorted(name_servers),
            "planned_endpoints": ENDPOINTS,
        },
        "validator_signers": signers,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "bridge_route": "PAUSED",
        },
        "secrets_included": False,
        "status": "AWS_BINDING_READBACK_VERIFIED",
    }

    output = Path(args.output)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    Path(f"{args.output}.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence": str(output), "sha256": digest}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1)
