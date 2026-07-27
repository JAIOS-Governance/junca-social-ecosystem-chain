from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (
    ROOT / "scripts/junca_validator_state_migration.sh"
).read_text(encoding="utf-8")
NODE = (
    ROOT / "scripts/junca_migrate_validator_state_node.sh"
).read_text(encoding="utf-8")
WORKFLOW = (
    ROOT / ".github/workflows/junca-validator-state-migration.yml"
).read_text(encoding="utf-8")


class ValidatorStateMigrationHardeningTests(unittest.TestCase):
    def test_provision_plan_is_fixed_property_allowlist_and_rerunnable(
        self,
    ) -> None:
        for required in (
            "0|1|2)",
            "($changes | length) <= 3",
            '.change.actions == ["create"]',
            '.change.after.encrypted == true',
            '.change.after.type == "gp3"',
            ".change.after.size == 200",
            ".change.after.iops == 6000",
            ".change.after.throughput == 250",
            "-target=aws_ebs_volume.validator_state",
            "aws ec2 attach-volume",
            'attachment_identity="/dev/sdf:${volume_id}:${instance_id}"',
            'grep -Fxq "$attachment_address"',
            'terraform -chdir="$runtime_dir" import',
            "-lock-timeout=5m",
            'state show -no-color',
            "terraform-version.json",
            'select(.DeviceName == "/dev/sdf")',
            '$state_devices[0].Ebs.VolumeId == $volume_id',
            "describe-instance-status",
            "StandardErrorContent // empty",
            "submission_path",
            "list-command-invocations",
            "list-commands --command-id",
            'recovery-${current_instance}.json',
            "validator-state-preflight.tfplan",
            "validator-state-preflight-plan.json",
            "] | length == 0",
        ):
            self.assertIn(required, CONTROLLER)
        for prohibited in ("aws ec2 detach-volume", "--force-detach"):
            self.assertNotIn(prohibited, CONTROLLER)
        self.assertIn(
            'all($values[]; . == null or . == "")',
            CONTROLLER,
        )
        restored_readback = CONTROLLER.split(
            'restored_snapshot_ids="$(',
            1,
        )[1].split(')"', 1)[0]
        self.assertIn("jq -c '", restored_readback)
        self.assertNotIn("jq -ce '", restored_readback)

    def test_acceptance_plan_allows_only_exact_tag_updates(self) -> None:
        for required in (
            'capture("\\\\[(?<index>[0-2])\\\\]$")',
            ".change.before | del(.tags, .tags_all)",
            ".change.after | del(.tags, .tags_all)",
            '.change.after.type == "gp3"',
            ".change.after.size == 200",
            ".change.after.iops == 6000",
            ".change.after.throughput == 250",
            ".change.after.tags | keys | sort",
            "JuncaRollbackSnapshotId",
        ):
            self.assertIn(required, CONTROLLER)
        self.assertLess(
            CONTROLLER.index('if [[ "$already_accepted" == true ]]'),
            CONTROLLER.index("validator-state-acceptance.tfplan"),
        )
        self.assertLess(
            CONTROLLER.index("validator-state-acceptance.tfplan"),
            CONTROLLER.index("post-migration-outputs.json"),
        )

    def test_copy_verifies_content_ownership_mode_xattrs_and_hardlinks(
        self,
    ) -> None:
        for required in (
            "cp -a --preserve=all",
            "write_metadata_manifest",
            "os.lstat",
            "stat.S_IMODE",
            '"uid": value.st_uid',
            '"gid": value.st_gid',
            "os.listxattr",
            "os.getxattr",
            '"hardlink_group"',
            '"sha256"',
            'cmp "$source_manifest" "$target_manifest"',
            "copy_manifest_sha256",
            'test "$filesystem" = ext4',
            "JUNCA_VALIDATOR_STATE",
            'rmdir "$temporary_mount/lost+found"',
            'if [[ -f "$temporary_mount/state.sqlite" ]]',
            'local rollback_status="$1"',
            'local rollback_line="${2:-unknown}"',
            'local rollback_command="${3:-unknown}"',
            "JUNCA_MIGRATION_FAILURE",
            'trap \'rollback "$?" "$LINENO" "$BASH_COMMAND"\' ERR EXIT',
            "trap 'rollback 130' INT",
            "trap 'rollback 143' TERM",
        ):
            self.assertIn(required, NODE)

    def test_quorum_checkpoints_bind_canonical_finality_continuity(
        self,
    ) -> None:
        for required in (
            "quorum-checkpoints.json",
            ".certificate == $expected.certificate",
            ".certificate_hash == $expected.certificate_hash",
            ".signer_resource_digest ==",
            ".private_key_material_accepted == false",
            '.network == "Public Testnet / No Monetary Value"',
            ".mainnet_changed == false",
            ".assets_moved == false",
            ".bridge_activated == false",
            "health_bindings",
            ".state.head.certificate_hash ==",
            ".state.certificate == null or",
            'quorum: "durable-certificate-3/3"',
            'local controller_status="$1"',
            "local attempt status",
            'exit "$controller_status"',
            "trap 'restart_on_controller_error \"$?\"' ERR EXIT",
            "trap 'restart_on_controller_error 130' INT",
            "trap 'restart_on_controller_error 143' TERM",
            "trap - ERR EXIT INT TERM",
            "prepare_finality_backfill_request",
            "require_migration_continuity",
            "junca-finality-certificate-backfill-request/v1",
            "durable-certificate-3/3",
            "JuncaFinalityCertificateBackfilled",
            "MOUNT_ACTIVATED_PENDING_FINALITY",
            'require_migration_continuity "migration-start"',
            'require_migration_continuity "validator-${validator_index}-after"',
        ):
            self.assertIn(required, CONTROLLER)

    def test_evidence_is_one_to_one_and_bound_to_request_run_and_head(
        self,
    ) -> None:
        for required in (
            "validator-mapping-bound.json",
            "exact one-to-one validator migration mapping required",
            "root_volume_id",
            ".VolumeId == $mapping.root_volume_id",
            "MigrationRequestSHA256",
            "GitHubEventSHA256",
            "GitHubRunId",
            "GitHubRunAttempt",
            "HeadCommit",
            "ssm_request_sha256",
            "migration_request_sha256",
            "github_event_sha256",
            "execution_binding",
            "finalized_head",
            "runtime_mount_verified: true",
            "immutable_runtime_mount_activation_pending: true",
        ):
            self.assertIn(required, CONTROLLER)
        for required in (
            "MIGRATION_REQUEST_SHA256:",
            ".execution_binding.migration_request_sha256 == $request",
            ".runtime_mount_verified == true",
            ".immutable_runtime_mount_activation_pending == true",
        ):
            self.assertIn(required, WORKFLOW)

    def test_existing_runtime_evidence_is_preserved_as_valid_json(self) -> None:
        self.assertIn(
            "jq -c '\n      "
            ".public_services_acceptance_readback.value.quorum_evidence_sha256",
            CONTROLLER,
        )
        self.assertIn(
            "jq -c '\n      "
            ".public_services_acceptance_readback.value.runtime_evidence_sha256",
            CONTROLLER,
        )
        self.assertIn(
            ".automatic_finality_readback.value.enabled // false",
            CONTROLLER,
        )


if __name__ == "__main__":
    unittest.main()
