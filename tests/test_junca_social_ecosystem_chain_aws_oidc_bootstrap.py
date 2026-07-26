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
        self.inventory_role = (
            ROOT
            / "infrastructure/aws/bootstrap/public-testnet-inventory-role.yaml"
        ).read_text(encoding="utf-8")
        self.binding_workflow = (
            ROOT
            / ".github/workflows/"
            "junca-social-ecosystem-chain-aws-binding-readback.yml"
        ).read_text(encoding="utf-8")
        self.bootstrap_variables = (
            ROOT / "infra/aws/bootstrap/variables.tf"
        ).read_text(encoding="utf-8")
        self.runtime_variables = (
            ROOT / "infra/aws/public-testnet/variables.tf"
        ).read_text(encoding="utf-8")
        self.bootstrap_main = (
            ROOT / "infra/aws/bootstrap/main.tf"
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

    def test_readback_runs_automatically_on_canonical_main_change(self) -> None:
        self.assertIn("push:", self.workflow)
        self.assertIn("branches: [main]", self.workflow)
        self.assertIn(
            "CANONICAL_ROLE_ARN: "
            "arn:aws:iam::595710543956:role/"
            "JuncaChainPublicTestnetDeployment",
            self.workflow,
        )
        self.assertIn(
            "inputs.expected_account_id || '595710543956'",
            self.workflow,
        )
        self.assertIn("inputs.aws_region || 'us-east-1'", self.workflow)

    def test_readback_is_bound_to_canonical_account_region_and_role(self) -> None:
        self.assertIn("default: us-east-1", self.workflow)
        self.assertNotIn("default: ap-northeast-1", self.workflow)
        self.assertIn('CANONICAL_ACCOUNT_ID: "595710543956"', self.workflow)
        self.assertIn("CANONICAL_REGION: us-east-1", self.workflow)
        self.assertIn(
            "CANONICAL_ROLE_ARN: "
            "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment",
            self.workflow,
        )
        self.assertNotIn("JuncaChainDocsProductionDeployment", self.workflow)
        self.assertIn("unexpected Public Testnet role identity", self.workflow)

    def test_all_aws_foundation_paths_use_canonical_region_and_role(self) -> None:
        for source in (
            self.binding_workflow,
            self.bootstrap_variables,
            self.runtime_variables,
        ):
            self.assertIn("us-east-1", source)
            self.assertNotIn("ap-northeast-1", source)
        self.assertIn(
            "JuncaChainPublicTestnetDeployment",
            self.binding_workflow,
        )
        self.assertIn(
            'name                 = "JuncaChainPublicTestnetDeployment"',
            self.bootstrap_main,
        )
        self.assertNotIn(
            "JUNCA-Social-Ecosystem-Chain-Testnet-Deployment",
            self.bootstrap_main,
        )

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

    def test_missing_role_recovery_is_iam_only_and_read_only(self) -> None:
        self.assertIn("RoleName: JuncaChainPublicTestnetDeployment", self.inventory_role)
        self.assertIn(
            "Sid: GitHubActionsPublicTestnetOIDC", self.inventory_role
        )
        self.assertIn(
            "repo:JAIOS-Governance@${RepositoryOwnerId}/"
            "junca-social-ecosystem-chain@${RepositoryId}:"
            "environment:${EnvironmentName}",
            self.inventory_role,
        )
        for required_action in (
            "ec2:DescribeVpcs",
            "ec2:DescribeSubnets",
            "route53:ListHostedZonesByName",
            "kms:ListAliases",
            "ecr:DescribeRepositories",
            "s3:ListAllMyBuckets",
            "dynamodb:ListTables",
        ):
            self.assertIn(required_action, self.inventory_role)
        for forbidden in (
            "AWS::EC2::",
            "AWS::S3::",
            "AWS::DynamoDB::",
            "AWS::KMS::",
            "AWS::ECS::",
            "AWS::Route53::",
            "CreateRole",
            "RunInstances",
            "ChangeResourceRecordSets",
            "terraform apply",
        ):
            self.assertNotIn(forbidden, self.inventory_role)


if __name__ == "__main__":
    unittest.main()
