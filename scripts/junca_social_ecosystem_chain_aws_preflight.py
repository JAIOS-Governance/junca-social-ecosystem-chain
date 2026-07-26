#!/usr/bin/env python3
"""Fail-closed static preflight for the canonical AWS Terraform boundary."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "infrastructure" / "aws"
REQUIRED_FILES = {
    "versions.tf", "variables.tf", "main.tf", "outputs.tf",
    "validator-user-data.sh.tftpl", "terraform.tfvars.example",
    "rpc-method-policy.json",
}
REQUIRED_MARKERS = {
    "JUNCA Social Ecosystem Chain",
    "JAIOS Institutional Governance",
    "Public Testnet / No Monetary Value",
    "deployment_enabled",
    "allowed_account_ids",
    "desired_count   = var.rpc_desired_count",
    "desired_count   = var.explorer_desired_count",
    "eth_sendRawTransaction",
    "aws_wafv2_web_acl",
    "aws_backup_plan",
    "aws_cloudwatch_metric_alarm",
    "validator_signer_kms_key_arns",
    "systemctl enable --now junca-validator.service",
    "sha256sum -c -",
    "JUNCA_SIGNER_KMS_ARN",
}
FORBIDDEN_SECRET_MARKERS = (
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "seed phrase",
)


def main() -> int:
    missing = sorted(REQUIRED_FILES - {item.name for item in AWS.iterdir()})
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(AWS.iterdir())
        if path.is_file()
    )
    missing_markers = sorted(marker for marker in REQUIRED_MARKERS if marker not in text)
    secret_findings = sorted(
        marker for marker in FORBIDDEN_SECRET_MARKERS if marker in text
    )
    evidence = {
        "schema_version": "junca-aws-preflight/v1",
        "chain_name": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "network_notice": "Public Testnet / No Monetary Value",
        "state": "BLOCKED_FAIL_CLOSED",
        "apply_authorized": False,
        "canonical_aws_binding_verified": False,
        "external_registrar": "XServer (planned; readback required)",
        "delegated_domain": "jaios-governance.org",
        "missing_files": missing,
        "missing_markers": missing_markers,
        "secret_findings": secret_findings,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
        "stop_conditions": [
            "AWS account or region not independently verified",
            "Route53 zone and external registrar NS delegation not read back",
            "three distinct Availability Zones not verified",
            "KMS/HSM signer resources or permissions not verified",
            "genesis, binary, image digests, DNS or TLS not verified",
            "runtime acceptance or rollback acceptance not PASS",
        ],
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if not missing and not missing_markers and not secret_findings else 1


if __name__ == "__main__":
    sys.exit(main())
