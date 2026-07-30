from __future__ import annotations

from copy import deepcopy
import unittest

from scripts.junca_validator_replacement_admission import (
    ContractError,
    SAFETY,
    build_admission,
)


ACCOUNT_ID = "123456789012"
NOW = 2_000_000_000
SLOT = 2_000_000_100
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
COMMIT = "e" * 40
IPS = ("10.67.16.10", "10.67.32.10", "10.67.48.10")
AZS = ("us-east-1a", "us-east-1b", "us-east-1c")


def target_groups() -> list[str]:
    return [
        (
            "arn:aws:elasticloadbalancing:us-east-1:"
            f"{ACCOUNT_ID}:targetgroup/junca-testnet-rpc/"
            "0123456789abcdef"
        ),
        (
            "arn:aws:elasticloadbalancing:us-east-1:"
            f"{ACCOUNT_ID}:targetgroup/junca-testnet-explorer/"
            "fedcba9876543210"
        ),
    ]


def manifest() -> dict[str, object]:
    validators: list[dict[str, object]] = []
    for index in range(1, 4):
        validators.append(
            {
                "validator_id": f"validator-{index:02d}",
                "launch_template_id": f"lt-{index:017x}",
                "launch_template_version": 7,
                "subnet_id": f"subnet-{index:017x}",
                "availability_zone": AZS[index - 1],
                "private_ip": IPS[index - 1],
                "instance_profile_arn": (
                    f"arn:aws:iam::{ACCOUNT_ID}:instance-profile/"
                    "junca-social-ecosystem-chain-testnet-validator-"
                    f"{index}"
                ),
                "security_group_id": f"sg-{index:017x}",
                "retained_volume_id": f"vol-{index:017x}",
                "target_group_arns": target_groups(),
                "kms_key_arn": (
                    f"arn:aws:kms:us-east-1:{ACCOUNT_ID}:key/"
                    f"00000000-0000-0000-0000-{index:012d}"
                ),
                "user_data_sha256": f"{index}" * 64,
                "launch_template_data_sha256": f"{index + 3}" * 64,
            }
        )
    return {
        "schema": (
            "junca-public-testnet-validator-replacement-contract/v1"
        ),
        "account_id": ACCOUNT_ID,
        "region": "us-east-1",
        "automation_document_name": "JuncaPTReplaceValidator",
        "automation_document_version": 3,
        "automation_document_sha256": SHA_A,
        "automation_role_arn": (
            f"arn:aws:iam::{ACCOUNT_ID}:role/"
            "JuncaPTValidatorReplaceAutomationRole"
        ),
        "lock_table_arn": (
            f"arn:aws:dynamodb:us-east-1:{ACCOUNT_ID}:"
            "table/JuncaPTValidatorReplacementLock"
        ),
        "evidence_bucket_arn": (
            "arn:aws:s3:::"
            f"junca-public-testnet-replacement-evidence-{ACCOUNT_ID}"
        ),
        "validators": validators,
        "safety": dict(SAFETY),
    }


def request() -> dict[str, object]:
    return {
        "ValidatorId": "validator-01",
        "AmiId": "ami-0123456789abcdef0",
        "ExpectedArtifactSha256": SHA_A,
        "ExpectedGenesisSha256": SHA_B,
        "ReleaseManifestSha256": SHA_C,
        "SourceCommit": COMMIT,
        "SlotEpochSeconds": SLOT,
    }


def fleet() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    contracts = manifest()["validators"]
    assert isinstance(contracts, list)
    for index, contract in enumerate(contracts, start=1):
        assert isinstance(contract, dict)
        validator_id = f"validator-{index:02d}"
        result.append(
            {
                "validator_id": validator_id,
                "instance_id": f"i-{index:017x}",
                "ami_id": f"ami-{index + 8:017x}",
                "state": "running",
                "private_ip": contract["private_ip"],
                "subnet_id": contract["subnet_id"],
                "availability_zone": contract["availability_zone"],
                "instance_profile_arn": contract["instance_profile_arn"],
                "security_group_ids": [contract["security_group_id"]],
                "volume_id": contract["retained_volume_id"],
                "target_group_arns": contract["target_group_arns"],
                "public_ip": None,
                "tags": {
                    "ValidatorId": validator_id,
                    "Project": "JUNCA Social Ecosystem Chain",
                    "Governance": "JAIOS Institutional Governance",
                    "Network": "Public Testnet",
                    "MonetaryUse": "None",
                    **SAFETY,
                },
            }
        )
    return result


class AdmissionTests(unittest.TestCase):
    def accept(
        self,
        manifest_value: object | None = None,
        request_value: object | None = None,
        fleet_value: object | None = None,
    ) -> dict[str, object]:
        return build_admission(
            manifest() if manifest_value is None else manifest_value,
            request() if request_value is None else request_value,
            fleet() if fleet_value is None else fleet_value,
            now=NOW,
        )

    def blocked(
        self,
        manifest_value: object | None = None,
        request_value: object | None = None,
        fleet_value: object | None = None,
    ) -> None:
        with self.assertRaises(ContractError):
            self.accept(manifest_value, request_value, fleet_value)

    def test_exact_contract_is_accepted(self) -> None:
        result = self.accept()
        self.assertEqual(
            result["decision"],
            "ACCEPTED_FOR_FIXED_AUTOMATION_START",
        )
        aws_request = result["aws_request"]
        self.assertIsInstance(aws_request, dict)
        assert isinstance(aws_request, dict)
        self.assertEqual(
            aws_request["DocumentName"],
            "JuncaPTReplaceValidator",
        )
        self.assertNotIn("AutomationAssumeRole", aws_request["Parameters"])
        self.assertEqual(
            result["serialization_lock"]["key"],  # type: ignore[index]
            "global",
        )

    def test_result_is_deterministic(self) -> None:
        self.assertEqual(self.accept(), self.accept())

    def test_extra_manifest_key_is_blocked(self) -> None:
        value = manifest()
        value["allow_arbitrary_shell"] = True
        self.blocked(manifest_value=value)

    def test_wrong_document_is_blocked(self) -> None:
        value = manifest()
        value["automation_document_name"] = "AWS-RunShellScript"
        self.blocked(manifest_value=value)

    def test_non_numeric_document_version_is_blocked(self) -> None:
        value = manifest()
        value["automation_document_version"] = "$LATEST"
        self.blocked(manifest_value=value)

    def test_cross_account_role_is_blocked(self) -> None:
        value = manifest()
        value["automation_role_arn"] = (
            "arn:aws:iam::999999999999:role/"
            "JuncaPTValidatorReplaceAutomationRole"
        )
        self.blocked(manifest_value=value)

    def test_wrong_lock_table_is_blocked(self) -> None:
        value = manifest()
        value["lock_table_arn"] = (
            f"arn:aws:dynamodb:us-east-1:{ACCOUNT_ID}:table/unsafe"
        )
        self.blocked(manifest_value=value)

    def test_true_safety_boundary_is_blocked(self) -> None:
        value = manifest()
        value["safety"]["MainnetChanged"] = "true"  # type: ignore[index]
        self.blocked(manifest_value=value)

    def test_duplicate_validator_identity_is_blocked(self) -> None:
        value = manifest()
        value["validators"][1]["validator_id"] = "validator-01"  # type: ignore[index]
        self.blocked(manifest_value=value)

    def test_wrong_private_ip_is_blocked(self) -> None:
        value = manifest()
        value["validators"][0]["private_ip"] = "10.67.16.11"  # type: ignore[index]
        self.blocked(manifest_value=value)

    def test_duplicate_availability_zone_is_blocked(self) -> None:
        value = manifest()
        value["validators"][1]["availability_zone"] = "us-east-1a"  # type: ignore[index]
        self.blocked(manifest_value=value)

    def test_duplicate_volume_is_blocked(self) -> None:
        value = manifest()
        value["validators"][1]["retained_volume_id"] = (  # type: ignore[index]
            value["validators"][0]["retained_volume_id"]  # type: ignore[index]
        )
        self.blocked(manifest_value=value)

    def test_unknown_target_group_is_blocked(self) -> None:
        value = manifest()
        value["validators"][0]["target_group_arns"][0] = (  # type: ignore[index]
            f"arn:aws:elasticloadbalancing:us-east-1:{ACCOUNT_ID}:"
            "targetgroup/unsafe/0123456789abcdef"
        )
        self.blocked(manifest_value=value)

    def test_request_extra_key_is_blocked(self) -> None:
        value = request()
        value["SubnetId"] = "subnet-0123456789abcdef0"
        self.blocked(request_value=value)

    def test_bad_candidate_ami_is_blocked(self) -> None:
        value = request()
        value["AmiId"] = "ami-latest"
        self.blocked(request_value=value)

    def test_bad_digest_is_blocked(self) -> None:
        value = request()
        value["ReleaseManifestSha256"] = "not-a-digest"
        self.blocked(request_value=value)

    def test_bad_source_commit_is_blocked(self) -> None:
        value = request()
        value["SourceCommit"] = "main"
        self.blocked(request_value=value)

    def test_past_epoch_is_blocked(self) -> None:
        value = request()
        value["SlotEpochSeconds"] = NOW - 30
        self.blocked(request_value=value)

    def test_unaligned_epoch_is_blocked(self) -> None:
        value = request()
        value["SlotEpochSeconds"] = SLOT + 1
        self.blocked(request_value=value)

    def test_far_future_epoch_is_blocked(self) -> None:
        value = request()
        value["SlotEpochSeconds"] = NOW + 3630
        self.blocked(request_value=value)

    def test_fourth_fleet_member_is_blocked(self) -> None:
        value = fleet()
        value.append(deepcopy(value[-1]))
        self.blocked(fleet_value=value)

    def test_duplicate_fleet_identity_is_blocked(self) -> None:
        value = fleet()
        value[1]["validator_id"] = "validator-01"
        self.blocked(fleet_value=value)

    def test_stopped_validator_is_blocked(self) -> None:
        value = fleet()
        value[0]["state"] = "stopped"
        self.blocked(fleet_value=value)

    def test_public_ip_is_blocked(self) -> None:
        value = fleet()
        value[0]["public_ip"] = "203.0.113.1"
        self.blocked(fleet_value=value)

    def test_wrong_security_group_is_blocked(self) -> None:
        value = fleet()
        value[0]["security_group_ids"] = ["sg-fffffffffffffffff"]
        self.blocked(fleet_value=value)

    def test_wrong_retained_volume_is_blocked(self) -> None:
        value = fleet()
        value[0]["volume_id"] = "vol-fffffffffffffffff"
        self.blocked(fleet_value=value)

    def test_missing_safety_tag_is_blocked(self) -> None:
        value = fleet()
        del value[0]["tags"]["BridgeActivated"]  # type: ignore[index]
        self.blocked(fleet_value=value)

    def test_true_live_safety_tag_is_blocked(self) -> None:
        value = fleet()
        value[0]["tags"]["AssetsMoved"] = "true"  # type: ignore[index]
        self.blocked(fleet_value=value)

    def test_noop_candidate_ami_is_blocked(self) -> None:
        value = request()
        value["AmiId"] = fleet()[0]["ami_id"]
        self.blocked(request_value=value)


if __name__ == "__main__":
    unittest.main()
