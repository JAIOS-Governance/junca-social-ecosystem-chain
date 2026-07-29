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
            "workflow_dispatch:",
            "source_run_id:",
            "parent_ami_id:",
            "python3_boto3_nevra:",
            "PUBLIC_TESTNET_IMMUTABLE_CANDIDATE",
            '.event == "push"',
            '.head_branch == "main"',
            ".head_repository.full_name == $repository",
            "ref: ${{ inputs.source_commit }}",
            '"junca-validator-ami-build-request/v2"',
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
        self.assertNotIn("workflow_run:", self.parent)
        self.assertNotIn("ami-amazon-linux-latest", self.parent)
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
        push_block = self.runtime.split("push:", 1)[1].split(
            "pull_request:", 1
        )[0]
        self.assertIn("branches: [main]", push_block)
        self.assertNotIn("paths:", push_block)
        pull_request_block = self.runtime.split("pull_request:", 1)[1].split(
            "workflow_dispatch:", 1
        )[0]
        for path in (
            '"scripts/junca_runtime_release_evidence_collector_drift.py"',
            '"scripts/junca_dispatch_workflow_and_wait.py"',
            '"scripts/junca_release_child_provenance.py"',
            '"scripts/junca_release_dispatch_attestation.py"',
            '"scripts/junca_validator_ami_build_request.py"',
            '"tests/test_junca_runtime_release_ami_drift.py"',
            '"tests/test_junca_release_orchestration.py"',
            '"tests/test_junca_hardened_release_v2.py"',
            '"tests/test_junca_validator_ami_build_request.py"',
            '"config/junca_validator_ami_supply_chain_lock.json"',
            '".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"',
            '".github/workflows/junca-runtime-release-manifest-gate.yml"',
        ):
            self.assertEqual(pull_request_block.count(path), 1)
        self.assertIn(
            "scripts/junca_release_dispatch_attestation.py",
            self.runtime.split("python3 -m py_compile", 1)[1],
        )
        self.assertIn("tests.test_junca_hardened_release_v2", self.runtime)
        self.assertIn("tests.test_junca_runtime_release_ami_drift", self.runtime)
        self.assertIn(
            "tests.test_junca_validator_ami_build_request",
            self.runtime,
        )


if __name__ == "__main__":
    unittest.main()
