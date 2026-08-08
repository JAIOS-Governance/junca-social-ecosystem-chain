from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".github/workflows/junca-validator-runtime-artifacts.yml"
RELEASE_V2 = ROOT / ".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"
CONTINUITY = ROOT / ".github/workflows/junca-public-testnet-continuity.yml"
SAMPLER = ROOT / ".github/workflows/junca-public-testnet-health-sampler.yml"


class GitHubActionsCreditGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.release_v2 = RELEASE_V2.read_text(encoding="utf-8")
        cls.continuity = CONTINUITY.read_text(encoding="utf-8")
        cls.sampler = SAMPLER.read_text(encoding="utf-8")

    def test_main_runtime_build_is_scoped_to_immutable_inputs(self) -> None:
        push_block = self.runtime.split("  pull_request:", 1)[0]
        for required in (
            '"jaios/social_ecosystem_chain/**"',
            '"packaging/systemd/**"',
            '"scripts/build_validator_runtime.sh"',
            '".github/image-builder/validator-component.yml"',
            '"infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"',
            "cancel-in-progress: true",
        ):
            self.assertIn(required, self.runtime)
        for forbidden in (
            "tests/",
            "junca-public-testnet-release-observer.yml",
            "junca-hardened-immutable-candidate-release-v2.yml",
            "junca_public_testnet_foundation.sh",
        ):
            self.assertNotIn(forbidden, push_block)

    def test_runtime_intermediate_artifacts_have_bounded_retention(self) -> None:
        self.assertEqual(self.runtime.count("retention-days: 14"), 2)
        self.assertEqual(self.runtime.count("retention-days: 30"), 1)
        self.assertNotIn("retention-days: 90", self.runtime)

    def test_release_v2_has_no_recursive_or_manual_automatic_start(self) -> None:
        for required in (
            "cancel-in-progress: true",
            "github.event.workflow_run.event == 'push'",
            '.event == "push" and',
            "automatic_successor_dispatch: false",
            "successor_runtime_run_id: null",
        ):
            self.assertIn(required, self.release_v2)
        for forbidden in (
            '(.event == "push" or .event == "workflow_dispatch")',
            '--workflow-name "JUNCA Validator Runtime Artifacts"',
            "for issue in 266 244 248 249",
        ):
            self.assertNotIn(forbidden, self.release_v2)

    def test_release_acceptance_has_single_publication_owner(self) -> None:
        self.assertIn(
            "The release observer owns the single current-state record.",
            self.release_v2,
        )
        self.assertIn('printf \'%s\\n\' "$body" >> "$GITHUB_STEP_SUMMARY"', self.release_v2)
        self.assertNotIn("issues: write", self.release_v2)

    def test_continuity_acceptance_is_not_a_periodic_failure_source(self) -> None:
        self.assertNotIn("  schedule:", self.continuity)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", self.continuity)
        self.assertIn("cancel-in-progress: true", self.continuity)
        self.assertIn("retention-days: 14", self.continuity)

    def test_periodic_sampler_is_bounded_non_blocking_and_silent(self) -> None:
        for required in (
            'cron: "17 */2 * * *"',
            "cancel-in-progress: true",
            "continue-on-error: true",
            "Automatic retry: false",
            "Incident email: false",
            "exit 0",
            "retention-days: 7",
        ):
            self.assertIn(required, self.sampler)
        for forbidden in (
            "issues: write",
            "actions: write",
            "gh api --method POST",
        ):
            self.assertNotIn(forbidden, self.sampler)


if __name__ == "__main__":
    unittest.main()
