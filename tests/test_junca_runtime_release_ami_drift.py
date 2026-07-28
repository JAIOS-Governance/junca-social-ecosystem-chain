from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import junca_runtime_release_evidence_collector_drift as drift
from tests import test_junca_runtime_release_evidence_collector as canonical_test


DRIFT_AMI = "ami-22222222222222222"


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
            manifest["explorer_baseline_sha256"],
            drift.collector.digest(explorer_path),
        )
        self.assertEqual(
            manifest["ebs_baseline_sha256"],
            drift.collector.digest(ebs_path),
        )
        self.assertEqual(
            explorer["observed_validator_runtimes"], validators
        )
        self.assertEqual(ebs["observed_validator_runtimes"], validators)

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

    def test_canonical_collector_hook_is_restored_after_collection(self):
        values = canonical_test.fixture()
        original = drift.collector.verify_instances
        with tempfile.TemporaryDirectory() as directory:
            self.collect(values, Path(directory))
        self.assertIs(drift.collector.verify_instances, original)

    def test_workflow_uses_drift_wrapper_and_preserves_exact_diagnostics(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/junca-runtime-release-evidence-collector.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python scripts/junca_runtime_release_evidence_collector_drift.py",
            workflow,
        )
        for path in (
            "evidence/readback/bootstrap-outputs.json",
            "evidence/readback/public-testnet-outputs.json",
            "evidence/readback/images.json",
            "evidence/readback/instances.json",
            "evidence/readback/volumes.json",
            "evidence/readback/snapshots.json",
        ):
            self.assertIn(path, workflow)


if __name__ == "__main__":
    unittest.main()
