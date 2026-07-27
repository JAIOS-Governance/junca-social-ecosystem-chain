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
            "($changes | length) <= 6",
            '.change.actions == ["create"]',
            '.change.after.encrypted == true',
            '.change.after.type == "gp3"',
            ".change.after.size == 200",
            ".change.after.iops == 6000",
            ".change.after.throughput == 250",
            '.change.after.device_name == "/dev/sdf"',
            ".change.after.force_detach == false",
            ".change.after.stop_instance_before_detaching == true",
            "validator-state-preflight.tfplan",
            "validator-state-preflight-plan.json",
            "] | length == 0",
        ):
            self.assertIn(required, CONTROLLER)

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
        ):
            self.assertIn(required, NODE)

    def test_quorum_checkpoints_bind_canonical_finality_continuity(
        self,
    ) -> None:
        for required in (
            "quorum-checkpoints.json",
            ".consensus.last_certificate.signed_power == 3",
            ".consensus.last_certificate.total_power == 3",
            ".consensus.last_certificate.validator_ids == [",
            ".consensus.last_certificate.finality_status ==",
            ".signer_resource_digest ==",
            ".private_key_material_accepted == false",
            ".mainnet_changed == false",
            ".assets_moved == false",
            ".bridge_activated == false",
            "health_bindings",
            "$heights[0] >= $previous_height",
            "$hashes[0] == $previous_hash",
            "$certificates[0] == $previous_certificate",
            'quorum: "3/3"',
            'require_peer_health "$instance_id"',
            'require_peer_health ""',
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
