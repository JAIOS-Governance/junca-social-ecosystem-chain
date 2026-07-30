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

    def test_parent_is_exact_main_and_end_to_end(self) -> None:
        for value in (
            "JUNCA Validator Runtime Artifacts",
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'push'",
            "workflow_run.head_branch == 'main'",
            "head_repository.full_name == github.repository",
            'test "$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)" = "$SOURCE_COMMIT"',
            ".github/workflows/junca-validator-ami-build.yml",
            ".github/workflows/junca-runtime-release-evidence-collector-v2.yml",
            ".github/workflows/junca-runtime-release-manifest-gate.yml",
            ".github/workflows/junca-validator-foundation-release.yml",
            ".github/workflows/junca-public-testnet-continuity.yml",
            "PUBLIC_TESTNET_ROLLOUT",
            "ACTIVE_ADVANCING",
            "PUBLIC_TESTNET_ACTIVE_ADVANCING",
        ):
            self.assertIn(value, self.parent)

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

    def test_parent_accepts_only_boolean_exact_request_ami_reuse(self) -> None:
        self.assertIn(
            '(.reused_existing_ami | type == "boolean")',
            self.parent,
        )
        self.assertNotIn(".reused_existing_ami == false", self.parent)
        self.assertIn(
            'echo "reused_existing_ami=$(jq -er .reused_existing_ami',
            self.parent,
        )

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

    def test_manifest_accepts_only_canonical_or_v2_collector(self) -> None:
        self.assertIn(
            '.path == ".github/workflows/junca-runtime-release-evidence-collector.yml" or',
            self.manifest,
        )
        self.assertIn(
            '.path == ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            self.manifest,
        )
        self.assertIn('.name == "JUNCA Runtime Release Evidence Collector"', self.manifest)
        self.assertIn('.conclusion == "success"', self.manifest)

    def test_runtime_artifact_rebinds_v2_release_changes(self) -> None:
        for path in (
            '"scripts/junca_runtime_release_evidence_collector_drift.py"',
            '"tests/test_junca_runtime_release_ami_drift.py"',
            '"tests/test_junca_hardened_release_v2.py"',
            '"tests/test_junca_public_testnet_endpoint_test.py"',
            '".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"',
            '".github/workflows/junca-runtime-release-manifest-gate.yml"',
        ):
            self.assertGreaterEqual(self.runtime.count(path), 2)
        self.assertIn("tests.test_junca_hardened_release_v2", self.runtime)
        self.assertIn(
            "tests.test_junca_public_testnet_endpoint_test",
            self.runtime,
        )
        self.assertIn("tests.test_junca_runtime_release_ami_drift", self.runtime)


if __name__ == "__main__":
    unittest.main()
