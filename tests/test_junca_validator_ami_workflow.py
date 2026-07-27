from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-validator-ami-build.yml"
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
RUNTIME_RECOVERY = ROOT / ".github/workflows/junca-validator-runtime-recovery.yml"


class ValidatorAmiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.component = COMPONENT.read_text(encoding="utf-8")
        cls.runtime_recovery = RUNTIME_RECOVERY.read_text(encoding="utf-8")

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

    def test_ami_build_is_manual_and_cannot_chain_from_runtime_artifacts(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("workflow_run:", self.workflow)
        self.assertNotIn("github.event.workflow_run", self.workflow)

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

    def test_component_verifies_installed_runtime(self):
        self.assertIn("__NODE_SHA256__", self.component)
        self.assertIn("__GENESIS_SHA256__", self.component)
        self.assertIn("/opt/junca/validator-runtime.tar.gz", self.component)
        self.assertIn("tar -xzf", self.component)
        self.assertIn('"public-testnet"', self.component)


if __name__ == "__main__":
    unittest.main()
