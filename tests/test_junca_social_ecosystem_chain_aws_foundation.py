import pathlib
import json
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


# Public services remain disabled until validator quorum evidence is accepted.
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
        cls.runtime_outputs = (
            ROOT / "infra/aws/public-testnet/outputs.tf"
        ).read_text(encoding="utf-8")
        cls.image_builder = cls.bootstrap
        cls.validator_user_data = (
            ROOT
            / "infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"
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
        cls.foundation_script = (
            ROOT / "scripts/junca_public_testnet_foundation.sh"
        ).read_text(encoding="utf-8")
        cls.public_release_script = (
            ROOT / "scripts/junca_public_testnet_release.sh"
        ).read_text(encoding="utf-8")
        cls.validator_foundation_release = (
            ROOT
            / ".github/workflows/junca-validator-foundation-release.yml"
        ).read_text(encoding="utf-8")
        cls.public_testnet_release = (
            ROOT
            / ".github/workflows/junca-public-testnet-release.yml"
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
        cls.iam_authorization = json.loads(
            (ROOT / "config/junca_public_testnet_aws_iam_authorization.json").read_text(
                encoding="utf-8"
            )
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

    def test_public_services_are_disabled_until_validator_acceptance(self) -> None:
        self.assertIn('variable "enable_public_services"', self.runtime_variables)
        self.assertIn("default     = false", self.runtime_variables)
        for required in (
            "count = var.enable_public_services ? 1 : 0",
            "count            = var.enable_public_services ? 3 : 0",
            "var.enable_public_services ? toset([",
        ):
            self.assertIn(required, self.runtime)
        self.assertIn(
            'value = var.enable_public_services ? "public-services" : "validators-only"',
            self.runtime_outputs,
        )
        self.assertIn(
            'value = try(aws_lb.public[0].arn, null)', self.runtime_outputs
        )

    def test_runtime_manages_alert_topic_and_dns_validated_certificate(self) -> None:
        for required in (
            'resource "aws_sns_topic" "validator_alerts"',
            'kms_master_key_id = "alias/aws/sns"',
            'resource "aws_acm_certificate" "public_services"',
            'resource "aws_route53_record" "certificate_validation"',
            'resource "aws_acm_certificate_validation" "public_services"',
            "prevent_destroy       = true",
            "aws_acm_certificate_validation.public_services.certificate_arn",
            "aws_sns_topic.validator_alerts.arn",
        ):
            self.assertIn(required, self.runtime)
        self.assertNotIn('variable "certificate_arn"', self.runtime_variables)
        self.assertNotIn('variable "alert_topic_arn"', self.runtime_variables)
        self.assertIn(
            'output "public_services_certificate"', self.runtime_outputs
        )
        self.assertIn('scan_hostname         = "scan.${var.domain_name}"', self.runtime)
        self.assertIn("local.scan_hostname", self.runtime)
        self.assertIn('output "scan_url"', self.runtime_outputs)
        self.assertIn('resource "aws_acm_certificate" "scan"', self.runtime)
        self.assertIn(
            'resource "aws_lb_listener_certificate" "scan"', self.runtime
        )
        self.assertIn(
            'resource "aws_lb_listener_rule" "scan_redirect"', self.runtime
        )
        self.assertIn('output "scan_certificate"', self.runtime_outputs)
        self.assertIn(
            'output "validator_alert_topic_arn"', self.runtime_outputs
        )

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

    def test_validator_roles_sign_only_with_their_assigned_key_but_verify_quorum(self) -> None:
        signer_boundary = self.runtime.split(
            'resource "aws_iam_role_policy" "validator_signer_boundary"', 1
        )[1].split(
            'resource "aws_iam_role_policy_attachment" "validator_ssm"', 1
        )[0]
        self.assertIn('Sid      = "UseOnlyAssignedSigner"', signer_boundary)
        self.assertIn('Action   = ["kms:Sign"]', signer_boundary)
        self.assertIn(
            "Resource = var.validator_signer_arns[count.index]", signer_boundary
        )
        self.assertIn('Sid      = "VerifyValidatorQuorum"', signer_boundary)
        self.assertIn(
            'Action   = ["kms:GetPublicKey", "kms:Verify", "kms:DescribeKey"]',
            signer_boundary,
        )
        self.assertIn("Resource = var.validator_signer_arns", signer_boundary)
        self.assertEqual(signer_boundary.count('"kms:Sign"'), 1)

    def test_runtime_reads_back_ami_and_signer_properties(self) -> None:
        for required in (
            'data "aws_ami" "approved_node"',
            'owners = ["self"]',
            'data "aws_kms_key" "validator_signer"',
            'signer.key_usage == "SIGN_VERIFY"',
            'signer.customer_master_key_spec == "ECC_SECG_P256K1"',
            "signer.enabled",
        ):
            self.assertIn(required, self.runtime)
        for required in (
            'output "private_subnet_ids"',
            'output "validator_signer_readback"',
            'output "approved_node_ami_readback"',
        ):
            self.assertIn(required, self.runtime_outputs)

    def test_image_builder_profile_is_terraform_managed_and_least_privilege(self) -> None:
        for required in (
            'resource "aws_iam_role" "validator_image_builder"',
            'resource "aws_iam_instance_profile" "validator_image_builder"',
            "JuncaChainPublicTestnetImageBuilder",
            "EC2InstanceProfileForImageBuilder",
            "AmazonSSMManagedInstanceCore",
            'resource "aws_iam_role_policy_attachment" "validator_image_builder_ssm_managed"',
            "JuncaValidatorImmutableInputRead",
            "junca-validator-ami-build-${var.aws_account_id}-*",
            'Action   = "iam:PassRole"',
            '"imagebuilder.amazonaws.com"',
            '"ec2.amazonaws.com"',
            'resource "aws_iam_role_policy" "deployment_ami_build"',
            "prevent_destroy = true",
        ):
            self.assertIn(required, self.image_builder)
        self.assertNotIn("Action = \"*\"", self.image_builder)
        self.assertIn(
            'output "validator_image_builder_profile"', self.bootstrap_outputs
        )

    def test_validator_binary_path_matches_runtime_contract(self) -> None:
        self.assertIn(
            "/usr/local/bin/junca-chain-node", self.validator_user_data
        )
        self.assertNotIn("/usr/local/bin/junca\n", self.validator_user_data)

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
        self.assertTrue(self.gates["apply_authorized"])
        self.assertEqual(
            self.gates["release_state"],
            "AUTHORIZED_FAIL_CLOSED_PENDING_PERMISSION_READBACK",
        )
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

    def test_execution_workflow_applies_only_after_exact_authorization(self) -> None:
        for required in (
            "config_authorized",
            'test "$config_authorized" = "true"',
            "PUBLIC-TESTNET-FOUNDATION-APPLY",
            "approved_change_reference",
            "steps.permissions.outputs.permission_gate",
            "steps.authorization.outputs.authorized == 'true'",
            "terraform -chdir=infra/aws/bootstrap apply",
            "bootstrap-outputs.json",
            "-migrate-state -force-copy",
            "scripts/junca_public_testnet_foundation.sh foundation-apply",
        ):
            self.assertIn(required, self.execution_workflow)

    def test_foundation_plan_and_apply_are_durable_and_fail_closed(self) -> None:
        for required in (
            "public-testnet/bootstrap.tfstate",
            "public-testnet/terraform.tfstate",
            "foundation.tfplan",
            'select(index("delete"))',
            "enable_public_services: $enable_public_services",
            "public_services_acceptance_readback.value.enabled",
            "public-services stage while rotating validator",
            "quorum_verified: false",
            "public_services_enabled: $public_services_enabled",
            "terraform -chdir=infra/aws/public-testnet apply",
            "validator_state_volume_readback.value // []",
            "enable_validator_state_volumes: $enable_validator_state_volumes",
            "aws_volume_attachment.validator_state",
            'test("^aws_instance\\\\.validator\\\\[[0-2]\\\\]$")',
            "describe-volumes --volume-ids",
        ):
            self.assertIn(required, self.foundation_script)
        for required in (
            "JUNCA_PUBLIC_TESTNET_NODE_AMI_ID",
            "JUNCA_PUBLIC_TESTNET_GENESIS_SHA256",
            "JUNCA_PUBLIC_TESTNET_SOURCE_COMMIT",
            "Produce guarded validator foundation plan",
            "Apply guarded validator foundation",
        ):
            self.assertIn(required, self.execution_workflow)
        self.assertNotIn("Reject unimplemented foundation apply", self.execution_workflow)

    def test_validator_release_pins_terraform_before_foundation_apply(self) -> None:
        setup_index = self.validator_foundation_release.index(
            "hashicorp/setup-terraform@v3"
        )
        version_index = self.validator_foundation_release.index(
            "terraform_version: 1.9.8"
        )
        apply_index = self.validator_foundation_release.index(
            "scripts/junca_public_testnet_foundation.sh foundation-apply"
        )
        self.assertLess(setup_index, version_index)
        self.assertLess(version_index, apply_index)
        self.assertIn(
            "terraform_wrapper: false", self.validator_foundation_release
        )
        self.assertIn(
            "group: junca-public-testnet-aws-foundation",
            self.validator_foundation_release,
        )
        self.assertIn(
            "cancel-in-progress: false", self.validator_foundation_release
        )
        self.assertNotIn("workflow_run:", self.validator_foundation_release)
        self.assertIn(
            "inputs.authorize_rollout == 'PUBLIC_TESTNET_ROLLOUT'",
            self.validator_foundation_release,
        )
        self.assertIn(
            "github.ref == 'refs/heads/main'",
            self.validator_foundation_release,
        )
        self.assertIn(
            "required: true",
            self.validator_foundation_release.split("ami_run_id:", 1)[1].split(
                "manifest_gate_run_id:", 1
            )[0],
        )
        self.assertIn(
            "required: true",
            self.validator_foundation_release.split(
                "manifest_gate_run_id:", 1
            )[1].split("authorize_rollout:", 1)[0],
        )
        self.assertNotIn("30233435029", self.validator_foundation_release)

    def test_foundation_requires_matching_manifest_gate_and_ami_chain(self) -> None:
        for required in (
            "Verify immutable AMI and manifest workflow provenance",
            '"JUNCA Validator Immutable AMI Build"',
            '"JUNCA Runtime Release Manifest Gate"',
            "junca-runtime-release-manifest-gate-"
            "${{ env.MANIFEST_GATE_RUN_ID }}",
            "run-id: ${{ env.MANIFEST_GATE_RUN_ID }}",
            '.candidate.source_commit == $source_commit',
            ".candidate.node_artifact_sha256 == $node_sha256",
            ".candidate.genesis_sha256 == $genesis_sha256",
            ".candidate.ami_id == $ami_id",
            '.decision == "PROMOTION_GATE_PASS"',
        ):
            self.assertIn(required, self.validator_foundation_release)
        provenance_index = self.validator_foundation_release.index(
            "Verify immutable AMI and manifest workflow provenance"
        )
        manifest_decision_index = self.validator_foundation_release.index(
            '.decision == "PROMOTION_GATE_PASS"'
        )
        oidc_index = self.validator_foundation_release.index(
            "aws-actions/configure-aws-credentials@v6.1.2"
        )
        apply_index = self.validator_foundation_release.index(
            "scripts/junca_public_testnet_foundation.sh foundation-apply"
        )
        self.assertLess(provenance_index, manifest_decision_index)
        self.assertLess(manifest_decision_index, oidc_index)
        self.assertLess(oidc_index, apply_index)

    def test_automatic_finality_is_terraform_canonical_and_shared(self) -> None:
        for required in (
            'variable "automatic_finality_enabled"',
            'variable "validator_block_interval_seconds"',
            'variable "validator_slot_epoch_seconds"',
            "var.validator_block_interval_seconds == 30",
            "var.validator_slot_epoch_seconds % 30 == 0",
        ):
            self.assertIn(required, self.runtime_variables)
        for required in (
            "automatic_finality_enabled = var.automatic_finality_enabled",
            "block_interval_seconds",
            "slot_epoch_seconds",
            "Automatic finality requires a shared positive 30-second-boundary",
        ):
            self.assertIn(required, self.runtime)
        for required in (
            "AUTOMATIC_FINALITY_ENABLED=${automatic_finality_enabled}",
            "TESTNET_BLOCK_INTERVAL_SECONDS=${block_interval_seconds}",
            "TESTNET_SLOT_EPOCH_SECONDS=${slot_epoch_seconds}",
        ):
            self.assertIn(required, self.validator_user_data)
        self.assertIn(
            'output "automatic_finality_readback"', self.runtime_outputs
        )

    def test_foundation_generates_once_then_preserves_shared_slot_epoch(self) -> None:
        for required in (
            "Generate one-time shared automatic finality epoch",
            "activation_delay=3600",
            "now + activation_delay + interval - 1",
            "VALIDATOR_BLOCK_INTERVAL_SECONDS=$interval",
            "VALIDATOR_SLOT_EPOCH_SECONDS=$slot_epoch",
            "automatic_finality_readback.value",
            "foundation apply requires automatic finality to be enabled",
            "automatic_finality_enabled: $automatic_finality_enabled",
            "validator_slot_epoch_seconds: $validator_slot_epoch_seconds",
        ):
            self.assertTrue(
                required in self.validator_foundation_release
                or required in self.foundation_script
            )

    def test_durable_state_mount_is_exact_existing_and_fail_closed(self) -> None:
        for required in (
            "user_data_replace_on_change = true",
            "validator_state_volume_id",
            "aws_ebs_volume.validator_state[count.index].id",
        ):
            self.assertIn(required, self.runtime)
        for required in (
            "nvme-Amazon_Elastic_Block_Store_",
            'case "\\$filesystem" in',
            "ext4|xfs",
            "RequiresMountsFor=/var/lib/junca",
            "ConditionPathIsMountPoint=/var/lib/junca",
            "ConditionPathExists=/var/lib/junca/state.sqlite",
            "ExecStartPre=/usr/bin/test -f /var/lib/junca/state.sqlite",
            "test ! -L /var/lib/junca/state.sqlite",
        ):
            self.assertIn(required, self.validator_user_data)
        self.assertNotIn("mkfs", self.validator_user_data)
        self.assertNotIn("wipefs", self.validator_user_data)

    def test_public_release_preserves_finality_without_validator_change(self) -> None:
        for required in (
            "pre-public-release-outputs.json",
            "validator_state_volume_readback.value",
            "enable_validator_state_volumes: $enable_validator_state_volumes",
            "validator_state_volume_size_gib: $validator_state_volume_size_gib",
            "validator_state_volume_iops: $validator_state_volume_iops",
            "validator_state_volume_throughput_mibps:",
            "validator_state_snapshot_ids: $validator_state_snapshot_ids",
            "automatic_finality_readback.value",
            "automatic_finality_enabled: $automatic_finality_enabled",
            "validator_block_interval_seconds: $validator_block_interval_seconds",
            "validator_slot_epoch_seconds: $validator_slot_epoch_seconds",
            '^aws_instance\\\\.validator\\\\[[0-2]\\\\]$',
        ):
            self.assertIn(required, self.public_release_script)

    def test_foundation_acceptance_requires_automatic_head_advancement(self) -> None:
        for required in (
            "Require two consecutive canonical finality slots",
            "(map(.head_height) | unique) == [$expected_height]",
            "(map(.head_timestamp) | unique | length) == 1",
            "(map(.consensus.last_certificate | tojson) | unique | length) == 1",
            ".automatic_finality_enabled == true",
            ".automatic_finality_loop_running == true",
            ".block_interval_seconds == 30",
            ".slot_epoch_seconds == $slot_epoch",
            "slot_epoch + ((initial_height + 1) * interval) + 5",
            "timeout-minutes: 150",
            "consecutive_advances: 2",
            "canonical_timestamp_delta_seconds:",
            "head_advanced: true",
            "final_height: $second[0][0].head_height",
        ):
            self.assertIn(required, self.validator_foundation_release)

    def test_public_release_requires_consecutive_endpoint_parity(self) -> None:
        for required in (
            "junca_public_testnet_endpoint_test.py --compact",
            "observation-1.json",
            "observation-2.json",
            "observation-3.json",
            "consecutive_canonical_advances: 2",
            "canonical_timestamp_delta_seconds: 30",
            "finalized_head.height == (.[0].finalized_head.height + 1)",
        ):
            self.assertIn(required, self.public_testnet_release)

    def test_public_release_auto_source_is_only_successful_main_foundation(self) -> None:
        trigger = self.public_testnet_release.split(
            "permissions:", 1
        )[0]
        self.assertIn(
            '- "JUNCA Validator Foundation Release"',
            trigger,
        )
        self.assertNotIn("JUNCA Public Testnet IAM Recovery", trigger)
        for required in (
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.name == "
            "'JUNCA Validator Foundation Release'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.full_name == "
            "github.repository",
        ):
            self.assertIn(required, self.public_testnet_release)
        self.assertNotIn("30237527940", self.public_testnet_release)

    def test_public_release_resolves_foundation_run_id_fail_closed(self) -> None:
        for required in (
            "Resolve exact Validator Foundation Release run",
            'test "$WORKFLOW_RUN_NAME" = "JUNCA Validator Foundation Release"',
            'run_id="$WORKFLOW_RUN_ID"',
            'run_id="$MANUAL_FOUNDATION_RUN_ID"',
            '[[ "$run_id" =~ ^[1-9][0-9]*$ ]]',
            'echo "run_id=$run_id" >> "$GITHUB_OUTPUT"',
            'echo "head_sha=$head_sha" >> "$GITHUB_OUTPUT"',
            '.status == "completed"',
            '.conclusion == "success"',
            '.name == "JUNCA Validator Foundation Release"',
            '.head_branch == "main"',
            ".repository.full_name == $repository",
            ".head_repository.full_name == $repository",
            "ref: ${{ steps.foundation.outputs.head_sha }}",
            "junca-validator-foundation-release-"
            "${{ steps.foundation.outputs.run_id }}",
            "run-id: ${{ steps.foundation.outputs.run_id }}",
        ):
            self.assertIn(required, self.public_testnet_release)
        self.assertNotIn(
            "github.event.workflow_run.id || inputs.foundation_run_id",
            self.public_testnet_release,
        )

    def test_deployment_role_can_refresh_and_update_validator_iam_roles(self) -> None:
        for action in (
            "iam:GetRole",
            "iam:ListAttachedRolePolicies",
            "iam:ListInstanceProfilesForRole",
            "iam:ListRolePolicies",
            "iam:UpdateAssumeRolePolicy",
        ):
            self.assertIn(action, self.bootstrap)

    def test_managed_acm_and_sns_are_not_external_foundation_inputs(self) -> None:
        for deprecated_input in (
            "CERTIFICATE_ARN",
            "ALERT_TOPIC_ARN",
            "JUNCA_PUBLIC_TESTNET_CERTIFICATE_ARN",
            "JUNCA_PUBLIC_TESTNET_ALERT_TOPIC_ARN",
        ):
            self.assertNotIn(deprecated_input, self.foundation_script)
            self.assertNotIn(deprecated_input, self.execution_workflow)
        for required_input in (
            "NODE_AMI_ID",
            "NODE_ARTIFACT_SHA256",
            "GENESIS_SHA256",
            "SOURCE_COMMIT",
            "AVAILABILITY_ZONES_JSON",
        ):
            self.assertIn(required_input, self.foundation_script)
            self.assertIn(required_input, self.execution_workflow)

    def test_auto_release_preserves_completed_bootstrap_when_runtime_inputs_are_pending(self) -> None:
        for required in (
            "Resolve validator foundation input readiness",
            "foundation-input-readiness.json",
            'foundation_state: $state',
            'steps.foundation_inputs.outputs.ready == \'true\'',
            'REQUESTED_PHASE" != "auto-release"',
            "foundation_apply_executed: false",
            "public_services_enabled: false",
        ):
            self.assertIn(required, self.execution_workflow)

    def test_bootstrap_plan_rejects_delete_or_replace_actions(self) -> None:
        self.assertIn(
            'select(index("delete"))', self.execution_workflow
        )
        self.assertIn(
            "aws_iam_role.deployment JuncaChainPublicTestnetDeployment",
            self.execution_workflow,
        )
        self.assertIn(
            "aws_iam_openid_connect_provider.github",
            self.execution_workflow,
        )
        self.assertIn('backend "s3" {}', self.bootstrap)

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

    def test_foundation_execution_requires_manual_dispatch(self) -> None:
        for required in (
            "workflow_dispatch:",
            "apply_confirmation:",
            "approved_change_reference:",
        ):
            self.assertIn(required, self.execution_workflow)
        self.assertNotIn("\n  workflow_run:", self.execution_workflow)
        self.assertNotIn("\n  push:", self.execution_workflow)

    def test_recovery_accepts_exact_existing_permission_without_mutation(self) -> None:
        for required in (
            "Fast path for an administrator-attached exact grant",
            'result="PRESENT"',
            'verification="PASS"',
            'if [[ "$verification" != "PASS" ]]',
            "iam:SimulatePrincipalPolicy",
        ):
            self.assertIn(required, self.self_permission_recovery)

    def test_manual_apply_requires_permission_pass_before_bootstrap_plan(self) -> None:
        for required in (
            "bootstrap-apply|foundation-apply|auto-release",
            "Require permission PASS before any plan",
            'test "${{ steps.permissions.outputs.permission_gate }}" = "PASS"',
            "JUNCA_TERRAFORM_STATE_BUCKET",
            "JUNCA_GITHUB_OIDC_THUMBPRINT",
        ):
            self.assertIn(required, self.execution_workflow)
        self.assertNotIn("terraform apply", self.execution_workflow)

    def test_runtime_role_can_simulate_only_its_own_policy(self) -> None:
        for required in (
            'resource "aws_iam_role_policy" "deployment_self_permission_readback"',
            'name = "SelfPermissionReadback"',
            'Action   = "iam:SimulatePrincipalPolicy"',
            "Resource = aws_iam_role.deployment.arn",
        ):
            self.assertIn(required, self.bootstrap)

    def test_ceo_iam_authorization_is_exact_and_triggers_recovery(self) -> None:
        authorization = self.iam_authorization
        self.assertEqual(
            authorization["authorization_state"], "CEO_APPROVED_FOR_EXECUTION"
        )
        self.assertEqual(
            authorization["grant"],
            {
                "effect": "Allow",
                "action": "iam:SimulatePrincipalPolicy",
                "resource": (
                    "arn:aws:iam::595710543956:role/"
                    "JuncaChainPublicTestnetDeployment"
                ),
            },
        )
        self.assertFalse(authorization["broad_iam_grant"])
        self.assertFalse(authorization["docs_runtime_role_use_authorized"])
        self.assertIn(
            "config/junca_public_testnet_aws_iam_authorization.json",
            self.self_permission_recovery,
        )
        self.assertIn("CEO_APPROVED_FOR_EXECUTION", self.self_permission_recovery)

    def test_self_permission_recovery_is_exact_and_fail_closed(self) -> None:
        for required in (
            "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment",
            "--role-name \"$TARGET_ROLE_NAME\"",
            "--policy-name SelfPermissionReadback",
            '"Resource": "$TARGET_ROLE_ARN"',
            "broad_iam_grant: false",
            "docs_runtime_role_used: false",
            "AWS foundation remains fail-closed",
            'echo "::error::Exact self-readback policy was not verified',
            "exit 1",
        ):
            self.assertIn(required, self.self_permission_recovery)
        self.assertNotIn("JuncaChainDocsProductionDeployment", self.self_permission_recovery)
        self.assertNotIn('"Resource": "*"', self.self_permission_recovery)


if __name__ == "__main__":
    unittest.main()
