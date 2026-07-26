import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AwsOidcBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = (
            ROOT / "infrastructure/aws/bootstrap/github-oidc.yaml"
        ).read_text(encoding="utf-8")
        self.workflow = (
            ROOT
            / ".github/workflows/junca-social-ecosystem-chain-aws-readback.yml"
        ).read_text(encoding="utf-8")

    def test_trust_is_repository_and_environment_scoped(self) -> None:
        self.assertIn(
            "repo:JAIOS-Governance@${RepositoryOwnerId}/"
            "junca-social-ecosystem-chain@${RepositoryId}:"
            "environment:${EnvironmentName}",
            self.template,
        )
        self.assertIn('Default: "308604370"', self.template)
        self.assertIn('Default: "1310568313"', self.template)
        self.assertIn(
            "token.actions.githubusercontent.com:aud: sts.amazonaws.com",
            self.template,
        )
        self.assertNotIn("repo:*", self.template)

    def test_bootstrap_has_no_chain_runtime_resources(self) -> None:
        forbidden = (
            "AWS::EC2::Instance",
            "AWS::ECS::Service",
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "AWS::KMS::Key",
        )
        for resource_type in forbidden:
            self.assertNotIn(resource_type, self.template)

    def test_state_is_encrypted_versioned_private_and_retained(self) -> None:
        for required in (
            "DeletionPolicy: Retain",
            "SSEAlgorithm: AES256",
            "PublicAccessBlockConfiguration:",
            "BlockPublicAcls: true",
            "Status: Enabled",
            "PointInTimeRecoveryEnabled: true",
        ):
            self.assertIn(required, self.template)

    def test_workflow_is_manual_oidc_and_readback_only(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("id-token: write", self.workflow)
        self.assertIn("aws-actions/configure-aws-credentials@v6.1.2", self.workflow)
        self.assertIn("deployment_enabled: false", self.workflow)
        self.assertNotIn("terraform apply", self.workflow)
        self.assertNotIn("pull_request_target", self.workflow)

    def test_public_boundary_is_exact(self) -> None:
        for value in (
            "JUNCA Social Ecosystem Chain",
            "JAIOS Institutional Governance",
            "Public Testnet / No Monetary Value",
            "mainnet_changed: false",
        ):
            self.assertTrue(
                value in self.template or value in self.workflow,
                msg=f"missing boundary: {value}",
            )


if __name__ == "__main__":
    unittest.main()
