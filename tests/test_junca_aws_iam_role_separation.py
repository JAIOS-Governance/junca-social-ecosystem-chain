from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "infra/aws/bootstrap"
RUNTIME = ROOT / "infra/aws/public-testnet"


class JuncaAwsIamRoleSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (BOOTSTRAP / "main.tf").read_text(encoding="utf-8")
        cls.separation = (BOOTSTRAP / "iam-separation.tf").read_text(
            encoding="utf-8"
        )
        cls.variables = (BOOTSTRAP / "variables.tf").read_text(
            encoding="utf-8"
        )
        cls.outputs = (BOOTSTRAP / "outputs.tf").read_text(encoding="utf-8")
        cls.runtime = (RUNTIME / "main.tf").read_text(encoding="utf-8")
        cls.runbook = (
            ROOT
            / "docs/runbooks/junca-public-testnet-iam-role-separation.md"
        ).read_text(encoding="utf-8")
        cls.core_policy_path = (
            BOOTSTRAP / "policies/security-bootstrap-core.json"
        )
        cls.state_policy_path = (
            BOOTSTRAP / "policies/security-bootstrap-state.json"
        )
        cls.core_policy = json.loads(
            cls.core_policy_path.read_text(encoding="utf-8")
        )
        cls.state_policy = json.loads(
            cls.state_policy_path.read_text(encoding="utf-8")
        )

    def test_oidc_subject_is_immutable_workflow_and_runner_bound(self) -> None:
        for claim in (
            '"repo"',
            '"context"',
            '"workflow_ref"',
            '"runner_environment"',
        ):
            self.assertIn(claim, self.separation)
        self.assertIn(
            "repo:JAIOS-Governance@308604370/",
            self.separation,
        )
        self.assertIn(
            "junca-social-ecosystem-chain@1310568313:",
            self.separation,
        )
        self.assertIn(
            ':runner_environment:github-hosted"',
            self.separation,
        )
        self.assertNotIn(
            '"repository_owner_id",\n      "repository_id"',
            self.separation,
        )
        for role_resource in (
            '"deployment"',
            '"ami_builder_controller"',
            '"observer"',
        ):
            trust_block = self.separation.split(
                f'resource "aws_iam_role" {role_resource}',
                1,
            )[1].split("\nresource ", 1)[0]
            self.assertNotIn("StringLike", trust_block)

    def test_stage_is_available_and_finalize_is_origin_blocked(self) -> None:
        self.assertIn('contains(["stage", "finalize"]', self.variables)
        self.assertIn("local.iam_migration_is_stage ||", self.main)
        self.assertIn(
            "BLOCKED_PENDING_INDEPENDENT_GITHUB_API_READBACK",
            self.variables,
        )
        self.assertIn(
            "VERIFIED_BY_INDEPENDENT_GITHUB_API_ARTIFACT_READBACK",
            self.main,
        )
        self.assertIn(
            "locally supplied attestation objects/digests do not prove "
            "GitHub artifact origin",
            self.main,
        )
        self.assertNotIn(
            "VERIFIED_BY_INDEPENDENT_GITHUB_API_ARTIFACT_READBACK",
            self.variables,
        )
        self.assertIn(
            "var.repo_global_oidc_stage_matrix_readback_sha256",
            self.main,
        )
        self.assertIn(
            "var.repo_global_oidc_activation_readback_sha256",
            self.main,
        )
        self.assertIn(
            "external_preparation_evidence.covered_baseline_call_count",
            self.main,
        )
        self.assertIn(
            "external_activation_evidence.sts_readback_sha256",
            self.main,
        )
        self.assertIn("-out=iam-stage.tfplan", self.runbook)
        self.assertLess(
            self.runbook.index("apply -input=false iam-stage.tfplan"),
            self.runbook.index("oidc-template-expected.json"),
        )

    def test_security_bootstrap_policy_split_is_below_iam_limit(self) -> None:
        for path, policy in (
            (self.core_policy_path, self.core_policy),
            (self.state_policy_path, self.state_policy),
        ):
            canonical = json.dumps(
                policy,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            self.assertLessEqual(len(canonical), 6144, path.name)
            self.assertEqual(len(hashlib.sha256(canonical).hexdigest()), 64)
        self.assertIn(
            "JuncaChainSecurityBootstrapCore",
            self.separation,
        )
        self.assertIn(
            "JuncaChainSecurityBootstrapState",
            self.separation,
        )

    def test_security_bootstrap_cannot_self_escalate(self) -> None:
        core = json.dumps(self.core_policy, sort_keys=True)
        state = json.dumps(self.state_policy, sort_keys=True)
        for document in (core, state):
            self.assertIn("DenySecurityBootstrapPolicySelfMutation", document)
        self.assertIn("DenyProtectedRoleBoundaryMutation", state)
        self.assertNotIn('"iam:CreateRole"', core)
        allow_statements = [
            statement
            for statement in self.core_policy["Statement"]
            if statement["Effect"] == "Allow"
        ]
        allowed_actions = {
            action
            for statement in allow_statements
            for action in (
                statement["Action"]
                if isinstance(statement["Action"], list)
                else [statement["Action"]]
            )
        }
        self.assertNotIn("iam:PutRolePermissionsBoundary", allowed_actions)
        attach = next(
            statement
            for statement in allow_statements
            if statement["Sid"] == "AttachOnlyCanonicalBootstrapPolicies"
        )
        self.assertEqual(attach["Action"], "iam:AttachRolePolicy")
        self.assertIn("iam:PolicyARN", attach["Condition"]["StringEquals"])
        self.assertIn("DenyBoundaryPolicyMutation", core)
        mutable = next(
            statement
            for statement in allow_statements
            if statement["Sid"] == "ManageCanonicalBootstrapPolicies"
        )
        self.assertEqual(len(mutable["Resource"]), 5)
        self.assertTrue(
            all(not arn.endswith("Boundary") for arn in mutable["Resource"])
        )

    def test_bootstrap_cannot_rewrite_workload_trust_or_hide_prefix_residue(
        self,
    ) -> None:
        allow_statements = [
            statement
            for statement in self.core_policy["Statement"]
            if statement["Effect"] == "Allow"
        ]
        role_management = next(
            statement
            for statement in allow_statements
            if statement["Sid"] == "ManageCanonicalBootstrapRoles"
        )
        self.assertNotIn(
            "iam:UpdateAssumeRolePolicy",
            role_management["Action"],
        )
        for action in (
            "iam:AddRoleToInstanceProfile",
            "iam:CreateInstanceProfile",
            "iam:RemoveRoleFromInstanceProfile",
        ):
            self.assertNotIn(action, role_management["Action"])
        managed_resources = role_management["Resource"]
        self.assertEqual(len(managed_resources), 11)
        self.assertFalse(
            any(
                resource.endswith("*")
                for resource in managed_resources
                if ":role/" in resource or ":instance-profile/" in resource
            )
        )
        for policy in (self.core_policy, self.state_policy):
            identity_resources = [
                resource
                for statement in policy["Statement"]
                for resource in (
                    statement["Resource"]
                    if isinstance(statement["Resource"], list)
                    else [statement["Resource"]]
                )
                if ":role/" in resource or ":instance-profile/" in resource
            ]
            self.assertFalse(
                any(
                    resource.endswith("validator-*")
                    for resource in identity_resources
                )
            )

        controller_trust = next(
            statement
            for statement in allow_statements
            if statement["Sid"] == "UpdateExactOidcControllerTrust"
        )
        self.assertEqual(
            controller_trust,
            {
                "Sid": "UpdateExactOidcControllerTrust",
                "Effect": "Allow",
                "Action": "iam:UpdateAssumeRolePolicy",
                "Resource": [
                    "arn:aws:iam::595710543956:role/"
                    "JuncaChainPublicTestnetDeployment",
                    "arn:aws:iam::595710543956:role/"
                    "JuncaChainPublicTestnetAmiBuilder",
                    "arn:aws:iam::595710543956:role/"
                    "JuncaChainPublicTestnetObserver",
                ],
            },
        )
        workload_deny = next(
            statement
            for statement in self.state_policy["Statement"]
            if statement["Sid"] == "DenyWorkloadTrustMutation"
        )
        self.assertEqual(
            workload_deny["Action"],
            "iam:UpdateAssumeRolePolicy",
        )
        self.assertEqual(len(workload_deny["Resource"]), 4)
        self.assertIn(
            "JuncaChainPublicTestnetImageBuilder",
            json.dumps(workload_deny),
        )
        for index in range(1, 4):
            self.assertIn(
                f"junca-social-ecosystem-chain-testnet-validator-{index}",
                json.dumps(workload_deny),
            )
        profile_deny = next(
            statement
            for statement in self.state_policy["Statement"]
            if statement["Sid"] == "DenyWorkloadInstanceProfileMutation"
        )
        self.assertEqual(
            set(profile_deny["Action"]),
            {
                "iam:AddRoleToInstanceProfile",
                "iam:CreateInstanceProfile",
                "iam:RemoveRoleFromInstanceProfile",
            },
        )
        self.assertEqual(len(profile_deny["Resource"]), 8)

        self.assertIn(
            "protected_iam_prefix_inventory_readback_sha256",
            self.variables,
        )
        self.assertIn(
            "sha256(local.protected_iam_prefix_inventory_contract_json)",
            self.main,
        )
        self.assertIn(
            "instance_profile_roles = merge(",
            self.separation,
        )
        self.assertIn(
            "value: (.Roles | map(.RoleName) | sort)",
            self.runbook,
        )
        self.assertIn(
            "aws iam list-instance-profiles --path-prefix /",
            self.runbook,
        )
        self.assertIn(
            "exactly seven roles and four profiles",
            self.runbook,
        )
        self.assertIn(
            "profile.role_name == data.aws_iam_role.validator[index].name",
            self.runtime,
        )
        self.assertIn(
            "profile.role_arn == data.aws_iam_role.validator[index].arn",
            self.runtime,
        )

    def test_external_boundary_documents_are_live_digest_gated(self) -> None:
        for name in (
            "foundation",
            "ami_builder",
            "observer",
            "remediation",
            "image_builder_worker",
            "validator01",
            "validator02",
            "validator03",
        ):
            self.assertIn(f"{name}", self.variables)
        self.assertIn(
            "local.boundary_policy_document_json",
            self.main,
        )
        self.assertIn(
            "var.external_boundary_policy_readback_sha256[boundary_name]",
            self.main,
        )
        self.assertIn(
            "external_boundary_policy_readback_sha256",
            self.variables,
        )

    def test_security_bootstrap_is_hardware_mfa_user_contract(self) -> None:
        self.assertIn(
            "^arn:aws:iam::595710543956:user/",
            self.variables,
        )
        self.assertNotIn(
            "^arn:aws:iam::595710543956:(role|user)",
            self.variables,
        )
        self.assertIn("aws:MultiFactorAuthPresent", self.main)
        self.assertIn("hardware MFA", self.runbook)

    def test_remediation_role_is_external_disabled_and_non_oidc(self) -> None:
        for token in (
            'data "aws_iam_role" "security_remediation"',
            "JuncaChainSecurityBootstrapRemediationBoundary",
            'tags["RemediationMode"]',
            '== "Disabled"',
            "token.actions.githubusercontent.com",
            "security_remediation_readback_sha256",
        ):
            self.assertTrue(
                token in self.main
                or token in self.separation
                or token in self.variables
            )
        self.assertIn(
            "IndependentRemediationSignerAdministration",
            self.main,
        )
        self.assertIn(
            "DenyStateDataPlaneForRemediationRole",
            self.main,
        )

    def test_kms_signer_admin_cannot_sign_or_create_grants(self) -> None:
        self.assertNotIn('Action    = "kms:*"', self.main)
        self.assertIn(
            "DenySecurityBootstrapSignerDataPlaneAndGrantCreation",
            self.main,
        )
        self.assertIn('"kms:Sign"', self.main)
        self.assertIn("SecurityBootstrapReadSignerEvidence", self.main)
        self.assertIn(
            "validator_signer_key_policy_readback_sha256",
            self.main,
        )
        state = json.dumps(self.state_policy, sort_keys=True)
        self.assertIn("DenySigning", state)
        self.assertIn("DenySignerGrantCreation", state)
        self.assertNotIn('"kms:*"', state)

    def test_state_kms_grant_and_encryption_context_are_exact(self) -> None:
        for token in (
            "SecurityBootstrapCreateOnlyDynamoDbStateGrant",
            "kms:GrantIsForAWSResource",
            "kms:CallerAccount",
            "dynamodb.${var.aws_region}.amazonaws.com",
            "kms:EncryptionContext:aws:s3:arn",
            "state_kms_encryption_context_arns",
            "depends_on = [aws_kms_alias.terraform_state]",
        ):
            self.assertTrue(token in self.main or token in self.separation)

    def test_state_bucket_has_explicit_deny_boundary(self) -> None:
        for sid in (
            "DenyInsecureTransport",
            "DenyUnapprovedStatePrincipal",
            "DenyUnexpectedStateObjectKey",
            "DenyStateDataPlaneForRemediationRole",
            "DenyStateWriteWithoutKms",
            "DenyStateWriteWithoutExactKmsKey",
            "DenyUnexpectedStateListPrefix",
            "DenyBootstrapStateReadOutsideSecurityBootstrap",
        ):
            self.assertIn(sid, self.main)
        self.assertIn("bucket_key_enabled = false", self.main)
        self.assertNotIn(
            '"${aws_s3_bucket.terraform_state.arn}/public-testnet/bootstrap.tfstate",',
            self.separation.split(
                'resource "aws_iam_role_policy" "deployment_state"',
                1,
            )[1].split("\nresource ", 1)[0],
        )
        self.assertNotIn(
            '"${aws_s3_bucket.terraform_state.arn}/public-testnet/bootstrap.tfstate",',
            self.separation.split(
                'resource "aws_iam_role_policy" "observer"',
                1,
            )[1].split("\n# Exclusive relationship resources", 1)[0],
        )

    def test_validator_ssm_and_foundation_host_mutation_stay_blocked(self) -> None:
        self.assertNotIn(
            'resource "aws_iam_role_policy_attachment" "validator_ssm"',
            self.separation,
        )
        self.assertIn(
            'resource "aws_iam_role_policy_attachments_exclusive" "validator"',
            self.separation,
        )
        self.assertIn("policy_arns = []", self.separation)
        for sid in (
            "DenyCanonicalValidatorInstanceMutation",
            "DenyUnattestedValidatorLaunch",
            "DenyArbitraryValidatorRootCommand",
        ):
            self.assertIn(sid, self.separation)

    def test_unbound_snapshot_and_child_creation_are_denied(self) -> None:
        self.assertIn("DenyUnboundSnapshotCreation", self.separation)
        self.assertIn(
            "DenyUnboundEc2ChildResourceCreation",
            self.separation,
        )
        create_allow = self.separation.split(
            'Sid    = "CreateOnlyTaggedPublicTestnetResources"',
            1,
        )[1].split("]", 1)[0]
        for action in (
            "ec2:CreateSnapshot",
            "ec2:CreateVolume",
            "ec2:CreateSubnet",
            "ec2:CreateRouteTable",
            "ec2:CreateSecurityGroup",
            "ec2:CreateVpcEndpoint",
        ):
            self.assertNotIn(action, create_allow)

    def test_exclusive_policy_purge_runs_in_stage(self) -> None:
        exclusive = self.separation.split(
            "# Exclusive relationship resources",
            1,
        )[1]
        self.assertNotIn("iam_migration_is_finalize ?", exclusive)
        self.assertEqual(
            exclusive.count('resource "aws_iam_role_policies_exclusive"'),
            5,
        )

    def test_oidc_provider_audience_extras_are_purged_and_gated(self) -> None:
        core = json.dumps(self.core_policy, sort_keys=True)
        self.assertIn("iam:RemoveClientIDFromOpenIDConnectProvider", core)
        self.assertIn("github_oidc_provider_readback_sha256", self.main)
        self.assertIn('client_id_list  = ["sts.amazonaws.com"]', self.separation)

    def test_lock_table_is_exact_and_extra_tags_are_reconcilable(self) -> None:
        self.assertIn(
            'var.lock_table_name ==\n      "junca-social-ecosystem-chain-testnet-lock"',
            self.variables,
        )
        self.assertIn(
            "dynamodb:UntagResource",
            json.dumps(self.state_policy),
        )
        exclusive = self.separation.split(
            "# Exclusive relationship resources",
            1,
        )[1]
        self.assertEqual(
            exclusive.count(
                'resource "aws_iam_role_policy_attachments_exclusive"'
            ),
            5,
        )

    def test_rollout_block_string_matches_machine_contract(self) -> None:
        blocked = "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT"
        policy = json.loads(
            (
                ROOT / "config/junca_public_testnet_cloud_role_policy.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(policy["runtime_recovery_execution_state"], blocked)
        self.assertIn(f'"{blocked}"', self.outputs)
        self.assertIn(f"`{blocked}`", self.runbook)

    def test_runbook_bash_blocks_are_not_mixed_language_syntax(self) -> None:
        blocks = [
            section.split("```", 1)[0]
            for section in self.runbook.split("```bash")[1:]
        ]
        self.assertGreater(len(blocks), 0)
        for index, block in enumerate(blocks, start=1):
            result = subprocess.run(
                ["bash", "-n"],
                input=block,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"bash block {index}: {result.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
