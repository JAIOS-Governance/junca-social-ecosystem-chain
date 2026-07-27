from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-validator-ami-build.yml"
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
RUNTIME_RECOVERY = ROOT / ".github/workflows/junca-validator-runtime-recovery.yml"
ORCHESTRATOR = (
    ROOT / ".github/workflows/junca-validator-public-testnet-orchestrator.yml"
)
FOUNDATION = ROOT / ".github/workflows/junca-validator-foundation-release.yml"
REQUEST = ROOT / "tests/fixtures/junca_validator_ami_build_request.json"


class ValidatorAmiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.component = COMPONENT.read_text(encoding="utf-8")
        cls.runtime_recovery = RUNTIME_RECOVERY.read_text(encoding="utf-8")
        cls.orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
        cls.foundation = FOUNDATION.read_text(encoding="utf-8")
        cls.request = REQUEST.read_text(encoding="utf-8")

    def test_workflow_binds_all_immutable_inputs(self):
        for field in (
            "source_commit",
            "node_sha256",
            "genesis_sha256",
            "source_run_id",
        ):
            self.assertIn(field, self.workflow)
        self.assertIn("gh api", self.workflow)
        self.assertIn("sha256sum --check", self.workflow)

    def test_uses_oidc_image_builder_and_never_terraform_or_cloudformation(self):
        self.assertIn("id-token: write", self.workflow)
        self.assertIn("aws imagebuilder create-image", self.workflow)
        self.assertNotIn("terraform apply", self.workflow)
        self.assertNotIn("cloudformation", self.workflow.lower())

    def test_ami_build_is_explicitly_requested_and_cannot_chain_from_runtime(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("\n  push:", self.workflow)
        self.assertIn("push:", self.orchestrator)
        self.assertIn(
            "config/junca_validator_ami_build_request.json",
            self.orchestrator,
        )
        self.assertNotIn("workflow_run:", self.workflow)
        self.assertNotIn("github.event.workflow_run", self.workflow)
        self.assertIn("junca_validator_ami_build_request.py", self.orchestrator)

    def test_push_request_is_signed_main_only_and_fail_closed(self):
        self.assertIn("refs/heads/main", self.orchestrator)
        self.assertIn(".commit.verification.verified == true", self.orchestrator)
        self.assertIn('.commit.verification.reason == "valid"', self.orchestrator)
        self.assertIn("(.files | length) == 1", self.orchestrator)
        self.assertIn(".files[0].filename == $path", self.orchestrator)
        self.assertIn("junca_validator_ami_build_request.py", self.orchestrator)

    def test_build_is_one_shot_idempotent_by_request_digest(self):
        self.assertIn("Name=tag:RequestDigest,Values=", self.workflow)
        self.assertIn("multiple AMIs exist for immutable request", self.workflow)
        self.assertIn("reused_existing_ami", self.workflow)
        self.assertIn("RequestDigest:", self.workflow)

    def test_orchestrator_dispatches_only_provenance_bound_release_chain(self):
        self.assertIn("actions: write", self.orchestrator)
        self.assertIn("environment: public-testnet", self.orchestrator)
        for workflow_name in (
            "JUNCA Validator Immutable AMI Build",
            "JUNCA Runtime Release Evidence Collector",
            "JUNCA Runtime Release Manifest Gate",
            "JUNCA Validator Foundation Release",
        ):
            self.assertIn(workflow_name, self.orchestrator)
        for workflow_path in (
            ".github/workflows/junca-validator-ami-build.yml",
            ".github/workflows/junca-runtime-release-evidence-collector.yml",
            ".github/workflows/junca-runtime-release-manifest-gate.yml",
            ".github/workflows/junca-validator-foundation-release.yml",
        ):
            self.assertIn(workflow_path, self.orchestrator)
        self.assertIn("PUBLIC_TESTNET_ROLLOUT", self.orchestrator)
        self.assertNotIn("terraform apply", self.orchestrator)
        self.assertNotIn("cloudformation", self.orchestrator.lower())

    def test_source_artifact_and_downstream_run_paths_are_hard_bound(self):
        for value in (
            '"JUNCA Validator Runtime Artifacts"',
            '".github/workflows/junca-validator-runtime-artifacts.yml"',
            '.event == "push"',
        ):
            self.assertIn(value, self.workflow)
        self.assertIn(
            '.path == ".github/workflows/junca-validator-ami-build.yml"',
            self.foundation,
        )
        self.assertIn(
            '.path == ".github/workflows/junca-runtime-release-manifest-gate.yml"',
            self.foundation,
        )
        self.assertGreaterEqual(self.foundation.count(".head_sha == $head"), 2)
        self.assertIn(".candidate.request_sha256 == $request_sha256", self.foundation)

    def test_canonical_request_binds_exact_six_runtime_inputs(self):
        for value in (
            "30273062161",
            "598152b38364e1cc85ec5e6e737f3e5830945d8a",
            "junca-validator-runtime-30273062161",
            "junca-validator-genesis-30273062161",
            "6441304649985de9a12c8758584785e0e0cc980b793fb735a1c5f0cffba70f14",
            "285f1aa2610ec98fba598aa3c8e721b54daeeddf2047b7f809f57c63db98dc95",
        ):
            self.assertIn(value, self.request)

    def test_runtime_recovery_cannot_apply_from_push(self):
        self.assertIn("workflow_dispatch:", self.runtime_recovery)
        self.assertNotIn("\n  push:", self.runtime_recovery)
        self.assertIn(
            "inputs.authorize_rollout == 'PUBLIC_TESTNET_RUNTIME_RECOVERY'",
            self.runtime_recovery,
        )

    def test_uses_fixed_terraform_managed_instance_profile(self):
        self.assertIn(
            "IMAGE_BUILDER_INSTANCE_PROFILE: JuncaChainPublicTestnetImageBuilder",
            self.workflow,
        )
        self.assertNotIn("VALIDATOR_IMAGE_BUILDER_INSTANCE_PROFILE", self.workflow)

    def test_safety_boundaries_are_recorded_false(self):
        for boundary in (
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "terraform_state_changed: false",
        ):
            self.assertIn(boundary, self.workflow)

    def test_failure_evidence_is_initialized_and_always_uploaded(self):
        self.assertIn("Initialize failure-safe build evidence", self.workflow)
        self.assertIn('state: "AMI_BUILD_STARTED"', self.workflow)
        self.assertIn("Finalize failure evidence", self.workflow)
        self.assertIn('state: "AMI_BUILD_FAILED"', self.workflow)
        self.assertIn("if: failure()", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("if-no-files-found: error", self.workflow)

    def test_checksum_manifest_is_portable_after_artifact_download(self):
        self.assertEqual(
            self.workflow.count(
                "sha256sum junca-validator-ami-build.json > SHA256SUMS"
            ),
            2,
        )
        self.assertNotIn(
            "sha256sum artifacts/junca-validator-ami-build.json "
            "> artifacts/SHA256SUMS",
            self.workflow,
        )

    def test_component_verifies_installed_runtime(self):
        self.assertIn("__NODE_SHA256__", self.component)
        self.assertIn("__GENESIS_SHA256__", self.component)
        self.assertIn("/opt/junca/validator-runtime.tar.gz", self.component)
        self.assertIn("tar -xzf", self.component)
        self.assertIn('"public-testnet"', self.component)


if __name__ == "__main__":
    unittest.main()
