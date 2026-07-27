from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "infra/aws/public-testnet"
WORKFLOW = ROOT / ".github/workflows/junca-validator-state-migration.yml"
CONTROLLER = ROOT / "scripts/junca_validator_state_migration.sh"
NODE_MIGRATION = ROOT / "scripts/junca_migrate_validator_state_node.sh"
AUTHORIZATION = "PUBLIC_TESTNET_VALIDATOR_STATE_MIGRATION"


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

    def test_expected_migration_entrypoints_exist(self) -> None:
        for path in (WORKFLOW, CONTROLLER, NODE_MIGRATION):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"missing migration entrypoint: {path}")

    def test_provisioning_is_separate_opt_in_and_enable_implies_provision(
        self,
    ) -> None:
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
        self.assertIn(
            "!var.enable_validator_state_volumes ||",
            self.runtime,
        )
        self.assertIn(
            "var.provision_validator_state_volumes",
            self.runtime,
        )

    def test_provisioned_volumes_remain_exact_three_retained_and_encrypted(
        self,
    ) -> None:
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
        ):
            self.assertIn(required, volume)
        for required in (
            "force_detach = false",
            "stop_instance_before_detaching = true",
            "aws_instance.validator[count.index].id",
        ):
            self.assertIn(required, attachment)
        self.assertIn('output "validator_state_volume_readback"', self.outputs)

    def test_workflow_is_signed_one_file_oidc_gated_and_serialized(
        self,
    ) -> None:
        for required in (
            "push:",
            "config/junca_validator_state_migration_request.json",
            "Verify signed migration request-only main commit",
            ".commit.verification.verified == true",
            '.commit.verification.reason == "valid"',
            "(.files | length) == 1",
            ".files[0].filename == $path",
            "junca_validator_state_migration_request.py",
            "environment: public-testnet",
            "id-token: write",
            "contents: read",
            "cancel-in-progress: false",
            "aws-actions/configure-aws-credentials@",
            "hashicorp/setup-terraform@",
            "scripts/junca_validator_state_migration.sh",
            AUTHORIZATION,
            "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment",
        ):
            self.assertIn(required, self.workflow)
        self.assertRegex(
            self.workflow,
            re.compile(
                r"group:\s*junca-public-testnet-aws-foundation",
                re.MULTILINE,
            ),
        )
        self.assertNotIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("workflow_run:", self.workflow)
        self.assertNotIn("inputs.authorize_migration", self.workflow)

    def test_workflow_emits_exact_next_phase_binding(self) -> None:
        for required in (
            "junca-validator-state-migration-binding/v1",
            "junca-validator-state-migration-binding.json",
            "migration_run_id",
            "migration_run_head_sha",
            "migration_request_sha256",
            "migration_evidence_sha256",
            'sha256sum --check SHA256SUMS',
        ):
            self.assertIn(required, self.workflow)

    def test_workflow_and_controller_preserve_release_boundaries(self) -> None:
        combined = self.workflow + "\n" + self.controller
        for boundary in (
            "mainnet_changed",
            "assets_moved",
            "bridge_activated",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, combined)
                self.assertRegex(
                    combined,
                    re.compile(rf"{boundary}[\"']?\s*[:=]\s*false"),
                )
        self.assertNotIn("mainnet-apply", combined.lower())
        self.assertNotIn("bridge-apply", combined.lower())
        self.assertNotIn("asset-issuance", combined.lower())

    def test_controller_reads_existing_state_and_accepts_additions_only_plan(
        self,
    ) -> None:
        for required in (
            "junca-social-ecosystem-chain-tfstate-595710543956-us-east-1",
            "junca-social-ecosystem-chain-testnet-lock",
            'terraform -chdir="$runtime_dir" init',
            'terraform -chdir="$runtime_dir" output -json',
            'terraform -chdir="$runtime_dir" plan',
            'terraform -chdir="$runtime_dir" show -json',
            "provision_validator_state_volumes: true",
            "aws_(ebs_volume|volume_attachment)\\\\.validator_state",
        ):
            self.assertIn(required, self.controller)
        self.assertRegex(
            self.controller,
            re.compile(r"(create|\"create\").*(delete|update|replace)", re.DOTALL),
        )
        self.assertRegex(
            self.controller,
            re.compile(r"(resource_changes|change\.actions)"),
        )
        self.assertRegex(
            self.controller,
            re.compile(r"(length|wc -l).*(==|=).*6", re.DOTALL),
        )
        for prohibited in (
            "terraform state rm",
            "terraform state mv",
            "terraform import",
            "bootstrap-apply",
            "infra/aws/bootstrap",
        ):
            self.assertNotIn(prohibited, self.controller)

    def test_controller_requires_exact_three_and_migrates_one_at_a_time(
        self,
    ) -> None:
        for required in (
            "validator_instance_ids",
            "validator_state_volume_readback",
            "aws ssm send-command",
            "wait_ssm_command",
            "junca_migrate_validator_state_node.sh",
        ):
            self.assertIn(required, self.controller)
        self.assertRegex(
            self.controller,
            re.compile(r"(instances|instance_ids).*3", re.DOTALL),
        )
        self.assertRegex(
            self.controller,
            re.compile(r"(volumes|volume_ids).*3", re.DOTALL),
        )
        self.assertRegex(
            self.controller,
            re.compile(r"for\s+.*validator|for\s+.*instance", re.DOTALL),
        )
        self.assertNotRegex(
            self.controller,
            re.compile(r"send-command[^\n]*&"),
        )

    def test_controller_snapshots_each_root_volume_and_marks_verified_pass(
        self,
    ) -> None:
        for required in (
            "RootDeviceName",
            "BlockDeviceMappings",
            "aws ec2 create-snapshot",
            "aws ec2 wait snapshot-completed",
            "VERIFIED_PASS",
            "aws ec2 create-tags",
        ):
            self.assertIn(required, self.controller)
        self.assertRegex(
            self.controller,
            re.compile(r"(rollback|Rollback).*(snapshot|Snapshot)", re.DOTALL),
        )
        self.assertRegex(
            self.controller,
            re.compile(r"(MigrationState|MigrationStatus).*VERIFIED_PASS"),
        )

    def test_node_migration_resolves_and_mounts_the_exact_volume_id(
        self,
    ) -> None:
        self.assertRegex(
            self.node,
            re.compile(r"vol-\[0-9a-f\]\{8,17\}|vol-\[0-9a-f\]\+"),
        )
        self.assertRegex(
            self.node,
            re.compile(r"/dev/disk/by-id/|ebsnvme-id"),
        )
        self.assertIn("/var/lib/junca", self.node)
        self.assertRegex(
            self.node,
            re.compile(r"(findmnt|lsblk|udevadm).*(volume|vol-)", re.DOTALL),
        )
        self.assertNotRegex(
            self.node,
            re.compile(r"mount\s+/dev/sdf"),
        )

    def test_node_migration_stops_copies_verifies_and_can_rollback(self) -> None:
        for required in (
            "systemctl stop junca-validator",
            "systemctl start junca-validator",
            "cp -a --preserve=all",
            "import sqlite3",
            "PRAGMA integrity_check",
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
        self.assertRegex(
            self.node,
            re.compile(r"(umount|unmount).*(mount|bind)", re.DOTALL),
        )

    def test_node_migration_never_formats_nonempty_or_unresolved_storage(
        self,
    ) -> None:
        self.assertRegex(
            self.node,
            re.compile(r"(wipefs|blkid|lsblk).*(mkfs)", re.DOTALL),
        )
        self.assertRegex(
            self.node,
            re.compile(r"(empty|EMPTY|unformatted|UNFORMATTED).*(mkfs)", re.DOTALL),
        )
        self.assertNotIn("force_detach", self.node)
        self.assertNotIn("terraform", self.node)


if __name__ == "__main__":
    unittest.main()
