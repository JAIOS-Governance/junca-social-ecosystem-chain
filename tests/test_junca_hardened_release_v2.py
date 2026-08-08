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

    def test_parent_stops_a_superseded_release_without_recursive_dispatch(self) -> None:
        for value in (
            'current_main="$(\n            gh api',
            'git merge-base --is-ancestor "$SOURCE_COMMIT" "$current_main"',
            'state: "SUPERSEDED_BY_NEW_MAIN"',
            "successor_runtime_run_id: null",
            "automatic_successor_dispatch: false",
            "candidate_accepted: false",
            'echo "superseded=true"',
            "if: steps.evidence.outputs.superseded != 'true'",
            "Automatic successor runtime dispatch is disabled",
        ):
            self.assertIn(value, self.parent)
        self.assertEqual(
            self.parent.count(
                "if: steps.evidence.outputs.superseded != 'true'"
            ),
            4,
        )
        self.assertNotIn(
            '--workflow-name "JUNCA Validator Runtime Artifacts"',
            self.parent,
        )
        self.assertNotIn('--expected-head "$current_main"', self.parent)
        self.assertIn('.event == "push" and', self.parent)
        self.assertIn(
            ".head_repository.full_name == $repository",
            self.parent,
        )

    def test_job_filter_and_api_readback_reject_manual_release_sources(self) -> None:
        job_filter = self.parent.split("    if: >-", 1)[1].split(
            "    runs-on:", 1
        )[0]
        self.assertIn("workflow_run.conclusion == 'success'", job_filter)
        self.assertIn("workflow_run.event == 'push'", job_filter)
        self.assertIn("workflow_run.head_branch == 'main'", job_filter)
        self.assertNotIn("head_repository", job_filter)
        for value in (
            '.name == "JUNCA Validator Runtime Artifacts"',
            '.path == ".github/workflows/junca-validator-runtime-artifacts.yml"',
            '.event == "push" and',
            ".head_repository.full_name == $repository",
        ):
            self.assertIn(value, self.parent)
        self.assertNotIn(
            '(.event == "push" or .event == "workflow_dispatch")',
            self.parent,
        )

    def test_release_acceptance_has_one_publication_owner(self) -> None:
        self.assertIn(
            "The release observer owns the single current-state record.",
            self.parent,
        )
        self.assertIn(
            "no multi-Issue comment or email fanout is emitted here.",
            self.parent,
        )
        self.assertIn(
            'printf \'%s\\n\' "$body" >> "$GITHUB_STEP_SUMMARY"',
            self.parent,
        )
        self.assertNotIn("for issue in 266 244 248 249; do", self.parent)
        self.assertNotIn("issues/${issue}/comments", self.parent)
        self.assertNotIn("issues: write", self.parent)

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

    def test_runtime_artifact_verifies_controls_without_auto_releasing_them(self) -> None:
        push_block = self.runtime.split("  pull_request:", 1)[0]
        pull_request_block = self.runtime.split("  pull_request:", 1)[1].split(
            "  workflow_dispatch:", 1
        )[0]
        for path in (
            '"scripts/junca_runtime_release_evidence_collector_drift.py"',
            '"tests/test_junca_runtime_release_ami_drift.py"',
            '"tests/test_junca_hardened_release_v2.py"',
            '"tests/test_junca_public_testnet_endpoint_test.py"',
            '".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"',
            '".github/workflows/junca-runtime-release-manifest-gate.yml"',
        ):
            self.assertEqual(self.runtime.count(path), 1)
            self.assertIn(path, pull_request_block)
            self.assertNotIn(path, push_block)
        self.assertIn("tests.test_junca_hardened_release_v2", self.runtime)
        self.assertIn(
            "tests.test_junca_public_testnet_endpoint_test",
            self.runtime,
        )
        self.assertIn("tests.test_junca_runtime_release_ami_drift", self.runtime)
        self.assertIn("cancel-in-progress: true", self.runtime)


if __name__ == "__main__":
    unittest.main()
