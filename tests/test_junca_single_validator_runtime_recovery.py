import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/junca_public_testnet_single_validator_runtime_recovery.sh"
WORKFLOW = ROOT / ".github/workflows/junca-emergency-validator01-runtime-recovery-v2.yml"
FOUNDATION = ROOT / "scripts/junca_public_testnet_foundation.sh"


class SingleValidatorRuntimeRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.foundation = FOUNDATION.read_text(encoding="utf-8")

    def test_workflow_is_exact_main_only_and_serialized(self) -> None:
        self.assertIn("branches: [main]", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("RECOVER_EXACT_VALIDATOR_01_RUNTIME", self.workflow)
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("group: junca-public-testnet-aws-foundation", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("permissions:\n  contents: read\n  id-token: write", self.workflow)

    def test_incident_target_is_exact_and_public_testnet_only(self) -> None:
        for expected in (
            "EXPECTED_VALIDATOR_ID: validator-01",
            "EXPECTED_INSTANCE_ID: i-0b15c21a599bf41be",
            "EXPECTED_AMI_ID: ami-0ddf86c982e6b1cba",
            "EXPECTED_STATE_VOLUME_ID: vol-0277b6a13ecf87efe",
            "EXPECTED_RUNTIME_SHA256: cf1ca0039d7855e5dc9cd2bda00d8ea691bb702966fa538c4510195a8926317f",
        ):
            self.assertIn(expected, self.workflow)
        self.assertIn('test "$EXPECTED_VALIDATOR_ID" = "validator-01"', self.script)
        self.assertIn('Key == "PublicTestnetOnly"', self.script)
        self.assertNotIn("terraform apply", self.script)
        self.assertNotIn("terminate-instances", self.script)
        self.assertNotIn("detach-volume", self.script)

    def test_all_read_only_admission_precedes_service_recovery(self) -> None:
        recovery = self.script.index("ensure_validator_service_available \\")
        for admission in (
            "aws sts get-caller-identity",
            "aws ec2 describe-instances",
            "aws ec2 describe-volumes",
            "terraform -chdir=infra/aws/public-testnet output -json",
            "read_instance_ami_binding",
        ):
            self.assertLess(self.script.index(admission), recovery)

    def test_instance_admission_jq_compiles_accepts_exact_and_rejects_drift(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq is not installed")
        instance_section = self.script.split(
            "aws ec2 describe-instances", 1
        )[1].split("aws ec2 describe-volumes", 1)[0]
        match = re.search(
            r'''--arg\s+volume\s+.*?\s+'(.*?)'\s+
                artifacts/runtime-recovery/instance\.json''',
            instance_section,
            re.DOTALL | re.VERBOSE,
        )
        self.assertIsNotNone(match)
        jq_filter = match.group(1)
        exact = {
            "Reservations": [{"Instances": [{
                "InstanceId": "i-0b15c21a599bf41be",
                "ImageId": "ami-0ddf86c982e6b1cba",
                "State": {"Name": "running"},
                "Tags": [
                    {"Key": "Validator", "Value": "01"},
                    {"Key": "Network", "Value": "Public Testnet"},
                    {"Key": "MonetaryUse", "Value": "None"},
                ],
                "BlockDeviceMappings": [{
                    "DeviceName": "/dev/sdf",
                    "Ebs": {
                        "VolumeId": "vol-0277b6a13ecf87efe",
                        "Status": "attached",
                        "DeleteOnTermination": False,
                    },
                }],
            }]}],
        }

        def run(payload: dict) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    "jq", "-e",
                    "--arg", "expected_instance", "i-0b15c21a599bf41be",
                    "--arg", "ami", "ami-0ddf86c982e6b1cba",
                    "--arg", "volume", "vol-0277b6a13ecf87efe",
                    jq_filter,
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )

        accepted = run(exact)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        drifted = json.loads(json.dumps(exact))
        drifted["Reservations"][0]["Instances"][0]["ImageId"] = "ami-deadbeef"
        rejected = run(drifted)
        self.assertNotEqual(rejected.returncode, 0)

    def test_recovery_reuses_audited_helper_and_is_fail_closed(self) -> None:
        self.assertIn("JUNCA_FOUNDATION_LIBRARY_ONLY=true", self.script)
        self.assertIn("ensure_validator_service_available", self.script)
        self.assertIn(".runtime_env_repaired == true", self.script)
        self.assertIn(".runtime_env_source == \"canonical\"", self.script)
        self.assertIn(".health_validator_id == \"validator-01\"", self.script)
        self.assertIn("terraform_apply_executed: false", self.script)
        self.assertIn("instance_replacement_executed: false", self.script)

    def test_library_mode_exits_before_terraform(self) -> None:
        guard = self.foundation.index("JUNCA_FOUNDATION_LIBRARY_ONLY")
        terraform = self.foundation.index(
            "terraform -chdir=infra/aws/bootstrap init", guard
        )
        self.assertLess(guard, terraform)
        self.assertIn("return 0", self.foundation[guard:terraform])

    def test_safety_boundaries_are_explicit(self) -> None:
        for boundary in (
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "mainnet_activation_authorized: false",
        ):
            self.assertIn(boundary, self.script)


if __name__ == "__main__":
    unittest.main()
