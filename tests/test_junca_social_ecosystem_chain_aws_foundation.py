import pathlib
import json
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AwsFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = (ROOT / "infra/aws/bootstrap/main.tf").read_text(
            encoding="utf-8"
        )
        cls.bootstrap_outputs = (
            ROOT / "infra/aws/bootstrap/outputs.tf"
        ).read_text(encoding="utf-8")
        cls.runtime = (ROOT / "infra/aws/public-testnet/main.tf").read_text(
            encoding="utf-8"
        )
        cls.runtime_variables = (
            ROOT / "infra/aws/public-testnet/variables.tf"
        ).read_text(encoding="utf-8")
        cls.workflow = (
            ROOT
            / ".github/workflows/junca-social-ecosystem-chain-aws-iac.yml"
        ).read_text(encoding="utf-8")
        cls.execution_workflow = (
            ROOT
            / ".github/workflows/"
            "junca-social-ecosystem-chain-aws-foundation-execution.yml"
        ).read_text(encoding="utf-8")
        cls.self_permission_recovery = (
            ROOT
            / ".github/workflows/"
            "junca-chain-runtime-self-permission-recovery.yml"
        ).read_text(encoding="utf-8")
        cls.gates = json.loads(
            (
                ROOT
                / "config/junca_social_ecosystem_chain_aws_foundation_gates.pending.json"
            ).read_text(encoding="utf-8")
        )

    def test_state_backend_is_private_retained_and_locked(self) -> None:
        for required in (
            'resource "aws_kms_key" "terraform_state"',
            'resource "aws_s3_bucket" "terraform_state"',
            'resource "aws_s3_bucket_public_access_block" "terraform_state"',
            'resource "aws_dynamodb_table" "terraform_lock"',
            "prevent_destroy = true",
            'billing_mode = "PAY_PER_REQUEST"',
        ):
            self.assertIn(required, self.bootstrap)

    def test_three_isolated_asymmetric_signers_are_bootstrapped(self) -> None:
        for required in (
            'resource "aws_kms_key" "validator_signer"',
            "count = 3",
            'key_usage                = "SIGN_VERIFY"',
            'customer_master_key_spec = "ECC_SECG_P256K1"',
            "prevent_destroy = true",
            'output "validator_signer_arns"',
        ):
            self.assertTrue(
                required in self.bootstrap or required in self.bootstrap_outputs
            )

    def test_runtime_is_three_az_private_and_has_no_public_validator_ip(self) -> None:
        for required in (
            'resource "aws_subnet" "private"',
            "count             = 3",
            "associate_public_ip_address = false",
            'PublicRPC     = "false"',
            "length(toset(var.availability_zones)) == 3",
        ):
            self.assertIn(required, self.runtime)

    def test_runtime_requires_canonical_role_and_immutable_artifacts(self) -> None:
        for required in (
            "JuncaChainPublicTestnetDeployment",
            "node_artifact_sha256",
            "genesis_sha256",
        ):
            self.assertTrue(
                required in self.runtime or required in self.runtime_variables
            )
        self.assertIn(
            'can(regex("^ami-[0-9a-f]{8,17}$", var.node_ami_id))',
            self.runtime_variables,
        )

    def test_ci_validates_bootstrap_runtime_and_legacy_modules(self) -> None:
        for module in (
            "infra/aws/bootstrap",
            "infra/aws/public-testnet",
            "infrastructure/aws",
        ):
            self.assertIn(f"module: {module}", self.workflow)

    def test_apply_authorization_is_separate_and_fail_closed(self) -> None:
        self.assertEqual(self.gates["aws_account_id"], "595710543956")
        self.assertEqual(self.gates["aws_region"], "us-east-1")
        self.assertEqual(
            self.gates["deployment_role_arn"],
            "arn:aws:iam::595710543956:role/"
            "JuncaChainPublicTestnetDeployment",
        )
        self.assertFalse(self.gates["apply_authorized"])
        self.assertEqual(self.gates["release_state"], "BLOCKED_FAIL_CLOSED")
        self.assertFalse(self.gates["mainnet_changed"])
        self.assertFalse(self.gates["assets_moved"])
        self.assertFalse(self.gates["bridge_activated"])
        self.assertEqual(
            [gate["gate"] for gate in self.gates["gates"]],
            [
                "state_backend",
                "three_az_network",
                "validator_signers",
                "immutable_runtime",
                "apply_authorization",
            ],
        )
        self.assertTrue(all(gate["state"] == "PENDING" for gate in self.gates["gates"]))
        self.assertNotIn("terraform apply", self.workflow)

    def test_execution_workflow_reads_permissions_before_plan_or_apply(self) -> None:
        for required in (
            "iam simulate-principal-policy",
            "permission_gate",
            "bootstrap-plan",
            "foundation-plan",
            "bootstrap-apply",
            "foundation-apply",
            "PUBLIC-TESTNET-FOUNDATION-APPLY",
        ):
            self.assertIn(required, self.execution_workflow)

    def test_execution_workflow_is_fail_closed_while_apply_is_unauthorized(self) -> None:
        self.assertIn(
            "config_authorized", self.execution_workflow
        )
        self.assertIn(
            'test "$config_authorized" = "true"', self.execution_workflow
        )
        self.assertIn(
            "Fail closed before any apply", self.execution_workflow
        )
        self.assertNotIn("terraform apply", self.execution_workflow)

    def test_execution_workflow_preserves_non_monetary_boundary(self) -> None:
        for required in (
            "Public Testnet / No Monetary Value",
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "595710543956",
            "us-east-1",
            "JuncaChainPublicTestnetDeployment",
        ):
            self.assertIn(required, self.execution_workflow)

    def test_runtime_role_can_simulate_only_its_own_policy(self) -> None:
        for required in (
            'resource "aws_iam_role_policy" "deployment_self_permission_readback"',
            'name = "SelfPermissionReadback"',
            'Action   = "iam:SimulatePrincipalPolicy"',
            "Resource = aws_iam_role.deployment.arn",
        ):
            self.assertIn(required, self.bootstrap)

    def test_self_permission_recovery_is_exact_and_fail_closed(self) -> None:
        for required in (
            "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment",
            "--role-name \"$TARGET_ROLE_NAME\"",
            "--policy-name SelfPermissionReadback",
            '"Resource": "$TARGET_ROLE_ARN"',
            "broad_iam_grant: false",
            "docs_runtime_role_used: false",
            "AWS foundation remains fail-closed",
        ):
            self.assertIn(required, self.self_permission_recovery)
        self.assertNotIn("JuncaChainDocsProductionDeployment", self.self_permission_recovery)
        self.assertNotIn('"Resource": "*"', self.self_permission_recovery)


if __name__ == "__main__":
    unittest.main()
