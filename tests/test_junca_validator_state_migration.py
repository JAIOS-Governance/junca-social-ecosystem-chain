from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "infra/aws/public-testnet"
WORKFLOW = ROOT / ".github/workflows/junca-validator-state-migration.yml"
CONTROLLER = ROOT / "scripts/junca_validator_state_migration.sh"
NODE_MIGRATION = ROOT / "scripts/junca_migrate_validator_state_node.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _terraform_block(source: str, declaration: str) -> str:
    start = source.find(declaration)
    if start < 0:
        return ""
    opening = source.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return source[start:]


class ValidatorStateMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.variables = _read(TF_DIR / "variables.tf")
        cls.runtime = _read(TF_DIR / "main.tf")
        cls.volumes = _read(TF_DIR / "validator-state-volume.tf")
        cls.outputs = _read(TF_DIR / "outputs.tf")
        cls.workflow = _read(WORKFLOW)
        cls.controller = _read(CONTROLLER)
        cls.node = _read(NODE_MIGRATION)

    def test_expected_migration_artifacts_exist(self) -> None:
        for path in (WORKFLOW, CONTROLLER, NODE_MIGRATION):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing migration artifact: {path}")

    def test_workflow_is_manual_non_oidc_tombstone(self) -> None:
        for required in (
            "workflow_dispatch:",
            "environment: public-testnet",
            "contents: read",
            "cancel-in-progress: false",
            "blocked-until-non-oidc-authorization:",
            "State migration is not a steady-state GitHub OIDC operation.",
            "time-bounded non-OIDC Security Bootstrap session",
            "exit 1",
        ):
            self.assertIn(required, self.workflow)
        self.assertRegex(
            self.workflow,
            re.compile(
                r"group:\s*junca-public-testnet-aws-foundation",
                re.MULTILINE,
            ),
        )
        for forbidden in (
            "\n  push:",
            "workflow_run:",
            "id-token: write",
            "aws-actions/configure-aws-credentials@",
            "ACTIONS_ID_TOKEN_REQUEST_URL",
            "scripts/junca_validator_state_migration.sh",
            "terraform apply",
        ):
            self.assertNotIn(forbidden, self.workflow)

    def test_controller_is_a_no_aws_fail_closed_tombstone(self) -> None:
        for required in (
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "permanent fail-closed tombstone",
            "time-bounded non-OIDC Security Bootstrap procedure",
            "No AWS API call was attempted.",
            "exit 64",
        ):
            self.assertIn(required, self.controller)
        for forbidden in (
            "aws ",
            "AWS-RunShellScript",
            "send-command",
            "terraform ",
            "curl ",
            "python",
            "eval ",
        ):
            self.assertNotIn(forbidden, self.controller)

    def test_controller_exits_before_any_fake_aws_invocation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "aws-called"
            fake_aws = root / "aws"
            fake_aws.write_text(
                "#!/usr/bin/env bash\n"
                f"touch {marker!s}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_aws.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{root}:{environment['PATH']}"
            completed = subprocess.run(
                ["bash", str(CONTROLLER)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 64)
            self.assertIn("No AWS API call was attempted.", completed.stderr)
            self.assertFalse(marker.exists())

    def test_historical_evidence_binding_remains_digest_pinned(self) -> None:
        policy = json.loads(
            (
                ROOT
                / "config/junca_hardened_immutable_candidate_policy.json"
            ).read_text(encoding="utf-8")
        )
        binding = policy["migration_binding"]
        self.assertRegex(binding["run_id"], r"^[1-9][0-9]*$")
        self.assertRegex(binding["evidence_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("migration_run_id", self.workflow)

    def test_provisioning_is_separate_opt_in(self) -> None:
        provision = _terraform_block(
            self.variables,
            'variable "provision_validator_state_volumes"',
        )
        self.assertIn("type        = bool", provision)
        self.assertIn("default     = false", provision)
        for resource in (
            'resource "aws_ebs_volume" "validator_state"',
            'resource "aws_volume_attachment" "validator_state"',
        ):
            block = _terraform_block(self.volumes, resource)
            self.assertIn(
                "count = var.provision_validator_state_volumes ? 3 : 0",
                block,
            )
            self.assertNotIn(
                "count = var.enable_validator_state_volumes ? 3 : 0",
                block,
            )
        self.assertIn("!var.enable_validator_state_volumes ||", self.runtime)
        self.assertIn("var.provision_validator_state_volumes", self.runtime)

    def test_volumes_remain_exact_three_retained_and_encrypted(self) -> None:
        volume = _terraform_block(
            self.volumes,
            'resource "aws_ebs_volume" "validator_state"',
        )
        attachment = _terraform_block(
            self.volumes,
            'resource "aws_volume_attachment" "validator_state"',
        )
        for required in (
            "encrypted         = true",
            'type              = "gp3"',
            "prevent_destroy = true",
            'MigrationRequired = var.validator_state_migration_accepted ? "false" : "true"',
            'PublicTestnetOnly = "true"',
            'MainnetChanged    = "false"',
            'AssetsMoved       = "false"',
            'BridgeActivated   = "false"',
        ):
            self.assertIn(required, volume)
        for required in (
            "force_detach = false",
            "stop_instance_before_detaching = true",
            "aws_instance.validator[count.index].id",
        ):
            self.assertIn(required, attachment)
        self.assertIn('output "validator_state_volume_readback"', self.outputs)

    def test_node_utility_resolves_exact_volume_and_never_assumes_sdf(self) -> None:
        self.assertRegex(
            self.node,
            re.compile(r"vol-\[0-9a-f\]\{8,17\}|vol-\[0-9a-f\]\+"),
        )
        self.assertRegex(self.node, re.compile(r"/dev/disk/by-id/|ebsnvme-id"))
        self.assertIn("/var/lib/junca", self.node)
        self.assertNotRegex(self.node, re.compile(r"mount\s+/dev/sdf"))

    def test_node_utility_preserves_and_verifies_state(self) -> None:
        for required in (
            "systemctl stop junca-validator",
            "systemctl start junca-validator",
            "cp -a --preserve=all",
            "PRAGMA integrity_check",
            "write_metadata_manifest",
            "os.listxattr",
            '"hardlink_group"',
            'cmp "$source_manifest" "$target_manifest"',
            "rollback",
        ):
            self.assertIn(required, self.node)
        self.assertRegex(
            self.node,
            re.compile(
                r"(last_certificate|finalized_certificate|certificate_hash)",
                re.IGNORECASE,
            ),
        )
        self.assertRegex(
            self.node,
            re.compile(r"(trap|rollback).*(ERR|EXIT|RETURN)", re.DOTALL),
        )

    def test_node_utility_formats_only_an_exact_empty_target(self) -> None:
        self.assertRegex(
            self.node,
            re.compile(r"(wipefs|blkid|lsblk).*(mkfs)", re.DOTALL),
        )
        self.assertRegex(
            self.node,
            re.compile(
                r"(empty|EMPTY|unformatted|UNFORMATTED).*(mkfs)",
                re.DOTALL,
            ),
        )
        self.assertNotIn("force_detach", self.node)
        self.assertNotIn("terraform", self.node)


if __name__ == "__main__":
    unittest.main()
