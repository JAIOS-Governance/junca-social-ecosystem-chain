from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts/junca_validator_state_migration.sh"
WORKFLOW = ROOT / ".github/workflows/junca-validator-state-migration.yml"


class ValidatorStateMigrationHardeningTests(unittest.TestCase):
    def test_tombstone_is_valid_bash(self) -> None:
        completed = subprocess.run(
            ["bash", "-n", str(CONTROLLER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_repository_execution_paths_do_not_use_generic_run_shell(self) -> None:
        offenders: list[str] = []
        for root in (ROOT / "scripts", ROOT / ".github" / "workflows"):
            for path in root.rglob("*"):
                if (
                    not path.is_file()
                    or path.suffix not in {".py", ".sh", ".yaml", ".yml"}
                ):
                    continue
                source = path.read_text(encoding="utf-8")
                if "AWS-RunShellScript" in source:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_workflow_and_controller_cannot_reach_cloud_credentials(self) -> None:
        combined = (
            CONTROLLER.read_text(encoding="utf-8")
            + "\n"
            + WORKFLOW.read_text(encoding="utf-8")
        )
        for forbidden in (
            "id-token: write",
            "configure-aws-credentials",
            "ACTIONS_ID_TOKEN_REQUEST_URL",
            "aws ssm",
            "aws ec2",
            "aws iam",
            "aws kms",
            "terraform apply",
        ):
            self.assertNotIn(forbidden, combined)

    def test_safety_boundaries_remain_explicit_in_public_testnet_state(self) -> None:
        volumes = (
            ROOT / "infra/aws/public-testnet/validator-state-volume.tf"
        ).read_text(encoding="utf-8")
        for required in (
            'PublicTestnetOnly = "true"',
            'MainnetChanged    = "false"',
            'AssetsMoved       = "false"',
            'BridgeActivated   = "false"',
            "prevent_destroy = true",
            "force_detach = false",
        ):
            self.assertIn(required, volumes)


if __name__ == "__main__":
    unittest.main()
