from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.junca_aws_canonical_inventory import InventoryError, build_inventory

ROOT = Path(__file__).resolve().parents[1]


class AwsCanonicalInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.responses = {
            ("sts", "get-caller-identity"): {
                "Account": "595710543956",
                "Arn": "arn:aws:sts::595710543956:assumed-role/test/session",
            },
            ("ec2", "describe-vpcs"): {
                "Vpcs": [
                    {
                        "VpcId": "vpc-1",
                        "CidrBlock": "10.67.0.0/16",
                        "IsDefault": False,
                        "Tags": [{"Key": "Name", "Value": "junca-testnet"}],
                    }
                ]
            },
            ("ec2", "describe-subnets"): {
                "Subnets": [
                    {
                        "SubnetId": f"subnet-{index}",
                        "VpcId": "vpc-1",
                        "AvailabilityZone": f"us-east-1{letter}",
                        "CidrBlock": f"10.67.{index}.0/24",
                        "MapPublicIpOnLaunch": False,
                        "Tags": [],
                    }
                    for index, letter in enumerate(("a", "b", "c"), start=1)
                ]
            },
            ("route53", "list-hosted-zones-by-name"): {
                "HostedZones": [
                    {
                        "Id": "/hostedzone/Z0336017285464TX0NT1G",
                        "Name": "jaios-governance.org.",
                        "Config": {"PrivateZone": False},
                    }
                ]
            },
            ("kms", "list-aliases"): {
                "Aliases": [
                    {"AliasName": "alias/junca-validator-01", "TargetKeyId": "key-1"}
                ]
            },
            ("ec2", "describe-images"): {"Images": []},
            ("ecr", "describe-repositories"): {"repositories": []},
            ("s3api", "list-buckets"): {
                "Buckets": [{"Name": "junca-public-testnet-tf-state"}]
            },
            ("dynamodb", "list-tables"): {
                "TableNames": ["junca-public-testnet-terraform-lock"]
            },
        }

    def run_aws(self, arguments):
        return self.responses[(arguments[0], arguments[1])]

    def test_redacted_inventory_preserves_release_boundary(self) -> None:
        inventory = build_inventory(region="us-east-1", run=self.run_aws)
        self.assertEqual(inventory["account_id"], "595710543956")
        self.assertEqual(len(inventory["subnets"]), 3)
        self.assertEqual(inventory["hosted_zones"][0]["zone_id"], "Z0336017285464TX0NT1G")
        self.assertFalse(inventory["private_key_material_included"])
        self.assertFalse(inventory["deployment_performed"])
        self.assertFalse(inventory["mainnet_changed"])
        self.assertFalse(inventory["assets_moved"])
        self.assertFalse(inventory["bridge_activated"])

    def test_invalid_account_identity_fails_closed(self) -> None:
        self.responses[("sts", "get-caller-identity")]["Account"] = "invalid"
        with self.assertRaisesRegex(InventoryError, "account identity"):
            build_inventory(region="us-east-1", run=self.run_aws)

    def test_retired_handoff_subject_is_recorded_as_prohibited_legacy(self) -> None:
        handoff = json.loads(
            (
                ROOT
                / "infrastructure/aws/public-testnet-oidc-trust-handoff.json"
            ).read_text(encoding="utf-8")
        )
        expected = (
            "repo:JAIOS-Governance@308604370/"
            "junca-social-ecosystem-chain@1310568313:"
            "environment:public-testnet"
        )
        cloud_role_policy = json.loads(
            (
                ROOT / "config/junca_public_testnet_cloud_role_policy.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(handoff["state"], "RETIRED_NON_EXECUTABLE")
        self.assertFalse(handoff["executable"])
        self.assertEqual(handoff["prohibited_legacy_subject"], expected)
        self.assertEqual(
            cloud_role_policy["prohibited_legacy_subject"],
            expected,
        )
        for executable_field in (
            "minimum_statement_patch",
            "readback_command",
            "rollback_policy",
            "workflow_rerun_url",
            "target_role_arns",
            "expected_subject",
            "current_token_subject",
        ):
            self.assertNotIn(executable_field, handoff)
        for retired_path in handoff["retired_artifacts"]:
            self.assertFalse((ROOT / retired_path).exists(), retired_path)
        self.assertFalse(handoff["deployment_performed"])

    def test_inventory_workflow_is_deleted_and_quarantined_by_policy(self) -> None:
        workflow = ROOT / ".github/workflows/junca-chain-aws-canonical-inventory.yml"
        self.assertFalse(workflow.exists())
        policy = json.loads(
            (
                ROOT / "config/junca_public_testnet_cloud_role_policy.json"
            ).read_text(encoding="utf-8")
        )
        entries = {
            item["workflow"]: item
            for item in policy["quarantine"]
        }
        entry = entries["junca-chain-aws-canonical-inventory.yml"]
        self.assertEqual(
            entry["original_name"],
            "JUNCA Chain AWS Canonical Inventory",
        )
        self.assertIn("scoped Observer readback", entry["retired_reason"])


if __name__ == "__main__":
    unittest.main()
