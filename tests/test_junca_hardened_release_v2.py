from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / ".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"
BASELINE = ROOT / ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"
MANIFEST = ROOT / ".github/workflows/junca-runtime-release-manifest-gate.yml"
RUNTIME = ROOT / ".github/workflows/junca-validator-runtime-artifacts.yml"


class HardenedReleaseV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parent = PARENT.read_text(encoding="utf-8")
        cls.baseline = BASELINE.read_text(encoding="utf-8")
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_parent_is_exact_source_and_candidate_ready(self) -> None:
        for value in (
            "JUNCA Validator Runtime Artifacts",
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'push'",
            "workflow_run.head_branch == 'main'",
            "head_repository.full_name == github.repository",
            "release-candidate/$SOURCE_COMMIT",
            "junca_dispatch_workflow_and_wait.py",
            ".github/workflows/junca-validator-ami-build.yml",
            ".github/workflows/junca-runtime-release-evidence-collector-v2.yml",
            ".github/workflows/junca-runtime-release-manifest-gate.yml",
            "PUBLIC_TESTNET_CANDIDATE_READY_FOR_SERIAL_ROLLOUT",
            "serial_rollout_dispatched: false",
            "continuity_dispatched: false",
        ):
            self.assertIn(value, self.parent)
        self.assertNotIn("resume_run_id=0", self.parent)
        self.assertNotIn("JUNCA Validator Foundation Release", self.parent)

    def test_parent_preserves_activation_boundaries(self) -> None:
        for value in (
            "transaction_submission_enabled: false",
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "mainnet_activation_authorized: false",
        ):
            self.assertIn(value, self.parent)
        self.assertNotIn("terraform apply", self.parent)
        self.assertNotIn("eth_send", self.parent)
        self.assertNotIn("junca_broadcast", self.parent)

    def test_v2_baseline_is_read_only_and_drift_explicit(self) -> None:
        for value in (
            "environment: public-testnet",
            "junca_runtime_release_evidence_collector_drift.py",
            "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE",
            "candidate_ami_preexisting == false",
            "terraform -chdir=infra/aws/bootstrap output -json",
            "terraform -chdir=infra/aws/public-testnet output -json",
            "junca-runtime-release-evidence-${{ github.run_id }}",
        ):
            self.assertIn(value, self.baseline)
        for forbidden in (
            "terraform apply",
            "terraform plan",
            "terraform import",
            "terraform state ",
            "aws ec2 create-",
            "aws ec2 modify-",
            "aws ec2 attach-",
            "aws ec2 detach-",
            "aws route53 change-",
            "eth_send",
        ):
            self.assertNotIn(forbidden, self.baseline)

    def test_manifest_accepts_only_exact_v2_collector(self) -> None:
        self.assertIn(
            '.path == ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            self.manifest,
        )
        self.assertIn('.name == "JUNCA Runtime Release Evidence Collector"', self.manifest)
        self.assertIn('.conclusion == "success"', self.manifest)
        self.assertIn(".head_sha == $source_commit", self.manifest)
        self.assertIn(".head_branch == $candidate_ref", self.manifest)
        self.assertNotIn(
            ".github/workflows/junca-runtime-release-evidence-collector.yml",
            self.manifest,
        )

    def test_runtime_artifact_rebinds_v2_release_changes(self) -> None:
        for path in (
            '"scripts/junca_runtime_release_evidence_collector_drift.py"',
            '"scripts/junca_dispatch_workflow_and_wait.py"',
            '"scripts/junca_release_child_provenance.py"',
            '"tests/test_junca_runtime_release_ami_drift.py"',
            '"tests/test_junca_release_orchestration.py"',
            '"tests/test_junca_hardened_release_v2.py"',
            '".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"',
            '".github/workflows/junca-runtime-release-manifest-gate.yml"',
        ):
            self.assertGreaterEqual(self.runtime.count(path), 2)
        self.assertIn("tests.test_junca_hardened_release_v2", self.runtime)
        self.assertIn("tests.test_junca_runtime_release_ami_drift", self.runtime)


if __name__ == "__main__":
    unittest.main()
