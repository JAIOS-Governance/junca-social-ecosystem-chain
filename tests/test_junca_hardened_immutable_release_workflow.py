from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-hardened-immutable-candidate-release.yml"
RUNTIME_WORKFLOW = ROOT / ".github/workflows/junca-validator-runtime-artifacts.yml"
OBSERVER_WORKFLOW = ROOT / ".github/workflows/junca-public-testnet-release-observer.yml"
DISPATCH = ROOT / "scripts/junca_dispatch_workflow_and_wait.sh"
IMAGE_COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
USER_DATA = ROOT / "infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"


class HardenedImmutableReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runtime_workflow = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
        cls.observer_workflow = OBSERVER_WORKFLOW.read_text(encoding="utf-8")
        cls.dispatch = DISPATCH.read_text(encoding="utf-8")
        cls.image_component = IMAGE_COMPONENT.read_text(encoding="utf-8")
        cls.user_data = USER_DATA.read_text(encoding="utf-8")

    def test_release_starts_only_from_successful_main_push_runtime(self) -> None:
        for value in (
            "JUNCA Validator Runtime Artifacts",
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'push'",
            "workflow_run.head_branch == 'main'",
            "head_repository.full_name == github.repository",
        ):
            self.assertIn(value, self.workflow)

    def test_old_pr145_candidate_is_not_reused_or_resumed(self) -> None:
        self.assertNotIn(
            "a64b7762bc561ce1ab3fe24bff95a4f1dc756f9e27d8270f4126e54e496815ec",
            self.workflow,
        )
        self.assertNotIn("30311265807", self.workflow)
        self.assertIn(".reused_existing_ami == false", self.workflow)
        self.assertIn('--input "resume_run_id=0"', self.workflow)
        self.assertIn(
            "junca_hardened_immutable_candidate_policy.py",
            self.workflow,
        )

    def test_exact_head_and_workflow_identity_are_fail_closed(self) -> None:
        self.assertIn("git/ref/heads/main", self.dispatch)
        self.assertIn('test "$main_head" = "$expected_head"', self.dispatch)
        self.assertIn('.conclusion == "success"', self.dispatch)
        self.assertIn('.head_sha == $head', self.dispatch)
        self.assertIn('.repository.full_name == $repository', self.dispatch)
        self.assertIn('test "$count" -le 1', self.dispatch)

    def test_runtime_artifact_contract_triggers_new_release_chain(self) -> None:
        for workflow_path in (
            ".github/workflows/junca-hardened-immutable-candidate-release.yml",
            ".github/workflows/junca-public-testnet-release-observer.yml",
        ):
            self.assertIn(workflow_path, self.runtime_workflow)
        self.assertIn(
            "tests.test_junca_hardened_immutable_candidate_policy",
            self.runtime_workflow,
        )
        self.assertIn("hardened_candidate_policy_sha256", self.runtime_workflow)

    def test_runtime_evidence_checksum_is_artifact_portable(self) -> None:
        self.assertIn("cd artifacts/evidence", self.runtime_workflow)
        self.assertIn(
            "sha256sum runtime-build.json > SHA256SUMS",
            self.runtime_workflow,
        )
        self.assertIn("sha256sum -c SHA256SUMS", self.runtime_workflow)
        self.assertNotIn(
            "sha256sum artifacts/evidence/runtime-build.json",
            self.runtime_workflow,
        )

    def test_release_observer_records_governed_workflow_evidence(self) -> None:
        for workflow_name in (
            "JUNCA Validator Runtime Artifacts",
            "JUNCA Hardened Immutable Candidate Release",
            "JUNCA Validator Immutable AMI Build",
            "JUNCA Runtime Release Evidence Collector",
            "JUNCA Runtime Release Manifest Gate",
            "JUNCA Validator Foundation Release",
            "JUNCA Public Testnet Continuity Evidence",
        ):
            self.assertIn(workflow_name, self.observer_workflow)
        for value in (
            "issues: write",
            "head_repository.full_name == github.repository",
            "head_branch == 'main'",
            'issues="244 248"',
            'issues="244 249"',
            'issues="266 ${issues}"',
            "issues/${issue}/comments",
            "EXACT_CURRENT_MAIN",
            "Mainnet Changed: false",
            "Assets Moved: false",
            "Bridge Activated: false",
        ):
            self.assertIn(value, self.observer_workflow)

    def test_ami_and_boot_contract_cover_all_three_services(self) -> None:
        for service in (
            "junca-validator.service",
            "junca-public-rpc.service",
            "junca-public-explorer.service",
        ):
            self.assertIn(
                f"systemctl enable {service}"
                if service == "junca-validator.service"
                else service,
                self.image_component,
            )
            self.assertIn(f"systemctl is-enabled {service}", self.image_component)
            self.assertIn(service, self.user_data)
        for port in ("8545", "8546", "3000"):
            self.assertIn(port, self.image_component)
            self.assertIn(port, self.user_data)
        self.assertIn("junca-validator-state.service", self.user_data)
        self.assertIn("ConditionPathIsMountPoint=/var/lib/junca", self.user_data)
        self.assertIn("curl -fsS http://127.0.0.1:8545/health", self.user_data)
        self.assertIn("curl -fsS http://127.0.0.1:3000/health", self.user_data)

    def test_release_chain_preserves_activation_boundaries(self) -> None:
        for value in (
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
        ):
            self.assertIn(value, self.workflow)
        self.assertIn(
            "JUNCA Validator Foundation Release",
            self.workflow,
        )
        self.assertIn(
            "PUBLIC_TESTNET_ROLLOUT",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
