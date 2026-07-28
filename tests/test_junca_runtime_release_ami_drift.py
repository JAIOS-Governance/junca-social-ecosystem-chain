from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import junca_runtime_release_evidence_collector_drift as drift
from tests import test_junca_runtime_release_evidence_collector as canonical_test


DRIFT_AMI = "ami-22222222222222222"
ROTATED_INSTANCE = "i-22222222222222222"
ROTATED_ROOT = "vol-22222222222222222"


class RuntimeReleaseAmiDriftTests(unittest.TestCase):
    def collect(self, values, output: Path):
        return drift.collect_with_drift(
            candidate=values["candidate"],
            bootstrap=values["bootstrap"],
            public=values["public"],
            images=values["images"],
            instances=values["instances"],
            volumes=values["volumes"],
            snapshots=values["snapshots"],
            endpoints=values["endpoints"],
            private_validator_health=values["private_validator_health"],
            public_endpoint_outage=values["public_endpoint_outage"],
            migration_evidence=values["migration_evidence"],
            migration_evidence_sha256="0" * 64,
            expected_migration_run_id=canonical_test.MIGRATION_RUN_ID,
            expected_migration_head_sha=canonical_test.MIGRATION_HEAD,
            expected_migration_request_sha256=canonical_test.MIGRATION_REQUEST,
            expected_source_commit=canonical_test.COMMIT,
            output_dir=output,
        )

    @staticmethod
    def rotate_first_validator(values):
        current = values["instances"]["Reservations"][0]["Instances"][0]
        original_instance = current["InstanceId"]
        original_root = current["BlockDeviceMappings"][0]["Ebs"]["VolumeId"]
        values["public"]["validator_instance_ids"]["value"][0] = (
            ROTATED_INSTANCE
        )
        current["InstanceId"] = ROTATED_INSTANCE
        current["ImageId"] = DRIFT_AMI
        current["BlockDeviceMappings"][0]["Ebs"]["VolumeId"] = ROTATED_ROOT
        values["volumes"]["Volumes"][0]["Attachments"][0][
            "InstanceId"
        ] = ROTATED_INSTANCE
        return original_instance, original_root

    def test_records_exact_pre_rollout_ami_drift_without_hiding_it(self):
        values = canonical_test.fixture()
        first = values["instances"]["Reservations"][0]["Instances"][0]
        first["ImageId"] = DRIFT_AMI
        with tempfile.TemporaryDirectory() as directory:
            manifest_path, explorer_path, ebs_path = self.collect(
                values, Path(directory)
            )
            manifest = json.loads(manifest_path.read_text())
            explorer = json.loads(explorer_path.read_text())
            ebs = json.loads(ebs_path.read_text())
            explorer_digest = drift.collector.digest(explorer_path)
            ebs_digest = drift.collector.digest(ebs_path)

        self.assertTrue(manifest["runtime_ami_drift_detected"])
        self.assertFalse(manifest["candidate_ami_preexisting"])
        self.assertEqual(
            manifest["observed_runtime_ami_state"],
            "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE",
        )
        self.assertEqual(
            manifest["observed_runtime_ami_ids"],
            sorted([canonical_test.CURRENT_AMI, DRIFT_AMI]),
        )
        validators = manifest["observed_validator_runtimes"]
        self.assertEqual(len(validators), 3)
        self.assertEqual(validators[0]["image_id"], DRIFT_AMI)
        self.assertFalse(validators[0]["terraform_approved_ami"])
        self.assertTrue(validators[1]["terraform_approved_ami"])
        self.assertEqual(
            manifest["explorer_baseline_sha256"], explorer_digest
        )
        self.assertEqual(manifest["ebs_baseline_sha256"], ebs_digest)
        self.assertEqual(
            explorer["observed_validator_runtimes"], validators
        )
        self.assertEqual(ebs["observed_validator_runtimes"], validators)
        self.assertEqual(
            manifest["migration_lineage_state"],
            "RETAINED_STATE_LINEAGE_VERIFIED",
        )
        self.assertTrue(
            manifest["migration_retained_state_lineage_verified"]
        )

    def test_records_instance_and_root_rotation_with_retained_state(self):
        values = canonical_test.fixture()
        original_instance, original_root = self.rotate_first_validator(values)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path, explorer_path, ebs_path = self.collect(
                values, Path(directory)
            )
            manifest = json.loads(manifest_path.read_text())
            explorer = json.loads(explorer_path.read_text())
            ebs = json.loads(ebs_path.read_text())

        self.assertTrue(manifest["migration_instance_rotation_detected"])
        self.assertTrue(
            manifest["migration_root_volume_rotation_detected"]
        )
        original = manifest["migration_original_validator_mappings"][0]
        current = manifest["migration_current_validator_mappings"][0]
        self.assertEqual(original["instance_id"], original_instance)
        self.assertEqual(original["root_volume_id"], original_root)
        self.assertEqual(current["instance_id"], ROTATED_INSTANCE)
        self.assertEqual(current["root_volume_id"], ROTATED_ROOT)
        for field in (
            "validator_id",
            "signer_arn",
            "state_volume_id",
            "rollback_snapshot_id",
        ):
            self.assertEqual(original[field], current[field])
        self.assertEqual(
            explorer["migration_current_validator_mappings"],
            manifest["migration_current_validator_mappings"],
        )
        self.assertEqual(
            ebs["migration_original_validator_mappings"],
            manifest["migration_original_validator_mappings"],
        )

    def test_rejects_candidate_ami_already_present_before_rollout(self):
        values = canonical_test.fixture()
        first = values["instances"]["Reservations"][0]["Instances"][0]
        first["ImageId"] = canonical_test.CANDIDATE_AMI
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                drift.collector.EvidenceError, "candidate_preexisting"
            ):
                self.collect(values, Path(directory))

    def test_rejects_invalid_observed_ami_identifier(self):
        values = canonical_test.fixture()
        first = values["instances"]["Reservations"][0]["Instances"][0]
        first["ImageId"] = "invalid-image"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                drift.collector.EvidenceError, "invalid_current_ami"
            ):
                self.collect(values, Path(directory))

    def test_rejects_migration_signer_lineage_change(self):
        values = canonical_test.fixture()
        values["migration_evidence"]["validator_mappings"][0][
            "signer_arn"
        ] = "arn:aws:kms:us-east-1:595710543956:key/changed-signer"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                drift.collector.EvidenceError, "signer_arn:mismatch"
            ):
                self.collect(values, Path(directory))

    def test_rejects_migration_state_volume_lineage_change(self):
        values = canonical_test.fixture()
        values["migration_evidence"]["validator_mappings"][0][
            "state_volume_id"
        ] = "vol-33333333333333333"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                drift.collector.EvidenceError, "state_volume_id:mismatch"
            ):
                self.collect(values, Path(directory))

    def test_rejects_migration_snapshot_root_lineage_change(self):
        values = canonical_test.fixture()
        values["migration_evidence"]["validator_mappings"][0][
            "root_volume_id"
        ] = "vol-33333333333333333"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                drift.collector.EvidenceError, "snapshot_root:mismatch"
            ):
                self.collect(values, Path(directory))

    def test_canonical_collector_hooks_are_restored_after_collection(self):
        values = canonical_test.fixture()
        original_instances = drift.collector.verify_instances
        original_migration = drift.collector.verify_migration_evidence
        with tempfile.TemporaryDirectory() as directory:
            self.collect(values, Path(directory))
        self.assertIs(drift.collector.verify_instances, original_instances)
        self.assertIs(
            drift.collector.verify_migration_evidence, original_migration
        )

    def test_v2_workflow_uses_drift_wrapper_and_preserves_diagnostics(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python scripts/junca_runtime_release_evidence_collector_drift.py",
            workflow,
        )
        self.assertIn("environment: public-testnet", workflow)
        self.assertIn(
            "junca-runtime-release-evidence-${{ github.run_id }}", workflow
        )
        self.assertIn(
            'migration_lineage_state == "RETAINED_STATE_LINEAGE_VERIFIED"',
            workflow,
        )
        self.assertIn(
            ".migration_retained_state_lineage_verified == true", workflow
        )
        for path in (
            "evidence/readback/bootstrap-outputs.json",
            "evidence/readback/public-testnet-outputs.json",
            "evidence/readback/images.json",
            "evidence/readback/instances.json",
            "evidence/readback/volumes.json",
            "evidence/readback/snapshots.json",
            "evidence/readback/endpoint-acceptance.json",
        ):
            self.assertIn(path, workflow)


if __name__ == "__main__":
    unittest.main()
