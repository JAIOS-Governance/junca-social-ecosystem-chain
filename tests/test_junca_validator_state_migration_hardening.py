from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
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


def extract_controller_function(name: str) -> str:
    lines = CONTROLLER.splitlines(keepends=True)
    start = lines.index(f"{name}() {{\n")
    for end in range(start + 1, len(lines)):
        if lines[end] == "}\n":
            return "".join(lines[start : end + 1])
    raise AssertionError(f"unterminated shell function: {name}")


class ValidatorStateMigrationHardeningTests(unittest.TestCase):
    @staticmethod
    def attachment_readback(tags: list[dict[str, str]]) -> dict[str, object]:
        return {
            "Volumes": [
                {
                    "VolumeId": "vol-0123456789abcdef0",
                    "AvailabilityZone": "us-east-1a",
                    "Encrypted": True,
                    "VolumeType": "gp3",
                    "Size": 200,
                    "Iops": 6000,
                    "Throughput": 250,
                    "Tags": tags,
                }
            ]
        }

    def run_attachment_readback(
        self,
        tags: list[dict[str, str]],
    ) -> subprocess.CompletedProcess[str]:
        with TemporaryDirectory() as temporary:
            readback = Path(temporary) / "volume.json"
            readback.write_text(
                json.dumps(self.attachment_readback(tags)),
                encoding="utf-8",
            )
            program = (
                "set -euo pipefail\n"
                + extract_controller_function(
                    "validate_state_volume_attachment_readback"
                )
                + 'validate_state_volume_attachment_readback "$1" '
                + '"vol-0123456789abcdef0" "us-east-1a"\n'
            )
            return subprocess.run(
                ["bash", "-c", program, "attachment-readback", str(readback)],
                check=False,
                text=True,
                capture_output=True,
            )

    @staticmethod
    def acceptance_plan(
        snapshot_id: str | None,
        *,
        remove_boundary: str | None = None,
    ) -> dict[str, object]:
        after_tags = {
            "AssetsMoved": "false",
            "BridgeActivated": "false",
            "FailureDomain": "us-east-1a",
            "JuncaFilesystemVerified": "true",
            "JuncaFinalityCertificateBackfilled": "true",
            "JuncaMigrationState": "VERIFIED_PASS",
            "JuncaRollbackSnapshotId": "snap-0123456789abcdef0",
            "JuncaStateStoreIntegrity": "true",
            "MainnetChanged": "false",
            "MigrationRequired": "false",
            "Name": "junca-testnet-validator-01-state",
            "PublicTestnetOnly": "true",
            "StatePath": "/var/lib/junca",
            "Validator": "01",
        }
        if remove_boundary is not None:
            after_tags.pop(remove_boundary)
        physical = {
            "encrypted": True,
            "type": "gp3",
            "size": 200,
            "iops": 6000,
            "throughput": 250,
            "snapshot_id": snapshot_id,
        }
        return {
            "resource_changes": [
                {
                    "address": "aws_ebs_volume.validator_state[0]",
                    "change": {
                        "actions": ["update"],
                        "before": {
                            **physical,
                            "tags": {
                                "FailureDomain": "us-east-1a",
                                "Name": "junca-testnet-validator-01-state",
                                "Validator": "01",
                            },
                        },
                        "after": {
                            **physical,
                            "tags": after_tags,
                        },
                    },
                }
            ]
        }

    def run_acceptance_plan(
        self,
        plan: dict[str, object],
    ) -> subprocess.CompletedProcess[str]:
        with TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            snapshots = json.dumps(
                [
                    "snap-0123456789abcdef0",
                    "snap-1123456789abcdef0",
                    "snap-2123456789abcdef0",
                ]
            )
            program = (
                "set -euo pipefail\n"
                + extract_controller_function(
                    "validate_state_volume_acceptance_plan"
                )
                + 'validate_state_volume_acceptance_plan "$1" "$2"\n'
            )
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    program,
                    "acceptance-plan",
                    str(plan_path),
                    snapshots,
                ],
                check=False,
                text=True,
                capture_output=True,
            )

    def test_attachment_readback_accepts_only_pending_or_verified_state(
        self,
    ) -> None:
        base_tags = [
            {"Key": "StatePath", "Value": "/var/lib/junca"},
            {"Key": "PublicTestnetOnly", "Value": "true"},
            {"Key": "MainnetChanged", "Value": "false"},
            {"Key": "AssetsMoved", "Value": "false"},
            {"Key": "BridgeActivated", "Value": "false"},
        ]
        pending = [
            *base_tags,
            {"Key": "MigrationRequired", "Value": "true"},
        ]
        accepted = [
            *base_tags,
            {"Key": "MigrationRequired", "Value": "false"},
            {"Key": "JuncaMigrationState", "Value": "VERIFIED_PASS"},
            {"Key": "JuncaFilesystemVerified", "Value": "true"},
            {"Key": "JuncaStateStoreIntegrity", "Value": "true"},
            {
                "Key": "JuncaFinalityCertificateBackfilled",
                "Value": "true",
            },
            {
                "Key": "JuncaRollbackSnapshotId",
                "Value": "snap-0123456789abcdef0",
            },
        ]
        self.assertEqual(self.run_attachment_readback(pending).returncode, 0)
        self.assertEqual(self.run_attachment_readback(accepted).returncode, 0)

        rejected = [
            [
                *pending,
                {"Key": "JuncaMigrationState", "Value": "VERIFIED_PASS"},
            ],
            [
                *pending,
                {"Key": "JuncaFilesystemVerified", "Value": "true"},
            ],
            [
                tag
                for tag in accepted
                if tag["Key"] != "JuncaStateStoreIntegrity"
            ],
            [
                {
                    **tag,
                    "Value": "snapshot-not-canonical",
                }
                if tag["Key"] == "JuncaRollbackSnapshotId"
                else tag
                for tag in accepted
            ],
            [
                *accepted,
                {"Key": "JuncaMigrationState", "Value": "VERIFIED_PASS"},
            ],
        ]
        for tags in rejected:
            with self.subTest(tags=tags):
                self.assertNotEqual(
                    self.run_attachment_readback(copy.deepcopy(tags)).returncode,
                    0,
                )

    def test_acceptance_plan_allows_only_absent_snapshot_source(
        self,
    ) -> None:
        for snapshot_id in (None, ""):
            with self.subTest(snapshot_id=snapshot_id):
                self.assertEqual(
                    self.run_acceptance_plan(
                        self.acceptance_plan(snapshot_id)
                    ).returncode,
                    0,
                )
        self.assertNotEqual(
            self.run_acceptance_plan(
                self.acceptance_plan("snap-99999999999999999")
            ).returncode,
            0,
        )

    def test_acceptance_plan_prohibits_boundary_tag_removal(self) -> None:
        for boundary in (
            "MainnetChanged",
            "AssetsMoved",
            "BridgeActivated",
        ):
            with self.subTest(boundary=boundary):
                self.assertNotEqual(
                    self.run_acceptance_plan(
                        self.acceptance_plan("", remove_boundary=boundary)
                    ).returncode,
                    0,
                )

    def test_evidence_array_lengths_are_parenthesized_before_boolean_gates(
        self,
    ) -> None:
        self.assertIn(
            "($invocation | length) == 1 and",
            CONTROLLER,
        )
        self.assertIn(
            "($binding | length) == 1 and",
            CONTROLLER,
        )
        self.assertNotIn("$invocation | length == 1", CONTROLLER)
        self.assertNotIn("$binding | length == 1", CONTROLLER)

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
            '.change.after.snapshot_id == ""',
            ".change.after.tags | keys | sort",
            "JuncaRollbackSnapshotId",
            '.change.after.tags.MainnetChanged == "false"',
            '.change.after.tags.AssetsMoved == "false"',
            '.change.after.tags.BridgeActivated == "false"',
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
            "filesystem_label_expected=JUNCA_VALIDATOR_",
            'mkfs.ext4 -q -m 0 -L "$filesystem_label_expected" "$device" >&2',
            "blkid -c /dev/null",
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

    def test_ext4_label_repair_is_limited_to_exact_empty_label(self) -> None:
        label_line = next(
            line
            for line in NODE.splitlines()
            if line.startswith("filesystem_label_expected=")
        )
        expected_label = label_line.split("=", 1)[1]
        self.assertLessEqual(len(expected_label.encode("ascii")), 16)
        self.assertEqual(expected_label, "JUNCA_VALIDATOR_")
        unmounted = 'test -z "$(findmnt -rn -S "$resolved_device" -o TARGET)"'
        read_label = (
            'blkid -c /dev/null -o value -s LABEL "$device" '
            '2>/dev/null || true'
        )
        empty_label = 'if [[ -z "$filesystem_label" ]]; then'
        relabel = 'e2label "$device" "$filesystem_label_expected"'
        readback = (
            'blkid -c /dev/null -o value -s LABEL "$device"'
        )
        final_gate = (
            'test "$filesystem_label" = "$filesystem_label_expected"'
        )
        for required in (
            unmounted,
            'test "$filesystem" = ext4',
            read_label,
            empty_label,
            relabel,
            readback,
            final_gate,
        ):
            self.assertIn(required, NODE)
        self.assertLess(NODE.index(unmounted), NODE.index(read_label))
        self.assertLess(NODE.index(empty_label), NODE.index(relabel))
        readback_index = NODE.index(readback, NODE.index(relabel))
        self.assertLess(NODE.index(relabel), readback_index)
        self.assertLess(readback_index, NODE.index(final_gate))

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
