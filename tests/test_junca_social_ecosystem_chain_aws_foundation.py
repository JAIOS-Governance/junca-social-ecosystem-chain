import pathlib
import json
import hashlib
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def restored_snapshot_filter(script: str) -> str:
    marker = 'validator_state_snapshot_ids="$('
    remainder = script.split(marker, 1)[1]
    match = re.search(
        r"jq -c '\n(?P<filter>.*?)\n\s*' <<<",
        remainder,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("restored snapshot jq filter is missing")
    return textwrap.dedent(match.group("filter"))


def runtime_finality_readback_block(script: str) -> str:
    block = script.split("# BEGIN_RUNTIME_FINALITY_READBACK\n", 1)[1].split(
        "\n# END_RUNTIME_FINALITY_READBACK", 1
    )[0]
    return block.replace("'\"'\"'", "'")


def finality_readback_filter(script: str) -> str:
    definition = script.split("def finality_readback:\n", 1)[1].split(
        "\n\n(finality_readback) as $finality", 1
    )[0]
    return "def finality_readback:\n" + definition + "\nfinality_readback"


def set_runtime_finality_block(script: str) -> str:
    block = script.split("# BEGIN_FINALITY_REMOTE_MUTATION\n", 1)[1].split(
        "\nsystemctl restart junca-validator.service", 1
    )[0]
    return block.replace("\\$", "$")


def runtime_finality_preflight_block(script: str) -> str:
    block = script.split("# BEGIN_FINALITY_REMOTE_PREFLIGHT\n", 1)[1].split(
        "\n# END_FINALITY_REMOTE_PREFLIGHT", 1
    )[0]
    return block.replace("\\$", "$")


def runtime_finality_exact_readback_block(script: str) -> str:
    block = script.split("# BEGIN_FINALITY_EXACT_READBACK\n", 1)[1].split(
        "\n# END_FINALITY_EXACT_READBACK", 1
    )[0]
    return block.replace("\\$", "$")


def runtime_finality_binding_functions(script: str) -> str:
    return script.split("build_runtime_finality_bindings() {", 1)[1].split(
        "\nset_runtime_finality() {", 1
    )[0].join(("build_runtime_finality_bindings() {", ""))


def ssm_online_function(script: str) -> str:
    return script.split("wait_for_ssm_online() {", 1)[1].split(
        "\n}\n\nwrite_post_apply_checkpoint()", 1
    )[0].join(("wait_for_ssm_online() {", "\n}"))


def required_json_boolean_function(script: str) -> str:
    return script.split("read_required_json_boolean() {", 1)[1].split(
        "\n}\n\nwait_for_ssm_online()", 1
    )[0].join(("read_required_json_boolean() {", "\n}"))


def rollback_snapshot_function(script: str) -> str:
    return script.split("verify_rollback_snapshots() {", 1)[1].split(
        "\n}\n\nwait_for_ssm_command()", 1
    )[0].join(("verify_rollback_snapshots() {", "\n}"))


def instance_ami_binding_function(script: str) -> str:
    return script.split("read_instance_ami_binding() {", 1)[1].split(
        "\n}\n\ncapture_validator_observation()", 1
    )[0].join(("read_instance_ami_binding() {", "\n}"))


def validator_service_recovery_validation_function(script: str) -> str:
    return script.split(
        "validate_validator_service_recovery_evidence() {", 1
    )[1].split("\n}\n\nensure_validator_service_available()", 1)[0].join(
        ("validate_validator_service_recovery_evidence() {", "\n}")
    )


def canonical_validator_runtime_env_function(script: str) -> str:
    return script.split(
        "render_canonical_validator_runtime_env() {", 1
    )[1].split(
        "\n}\n\nvalidate_validator_service_recovery_evidence()", 1
    )[0].join(("render_canonical_validator_runtime_env() {", "\n}"))


def validator_service_recovery_remote_script(script: str) -> str:
    definition = script.split(
        "ensure_validator_service_available() {", 1
    )[1].split("\n}\n\nwrite_live_rollout_prefix_readback()", 1)[0]
    return definition.split("cat <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]


def runtime_env_schema_functions(script: str) -> str:
    remote = validator_service_recovery_remote_script(script)
    return (
        "runtime_env_has_exact_assignment() {"
        + remote.split("runtime_env_has_exact_assignment() {", 1)[1].split(
            "\n\nverify_durable_mount_persistence_contract() (", 1
        )[0]
    )


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
        cls.validator_runtime_recovery = (
            ROOT
            / ".github/workflows/"
            "junca-validator-runtime-recovery.yml"
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

    def test_bootstrap_epochs_are_separate_from_runtime_activation(self) -> None:
        self.assertIn(
            'variable "validator_bootstrap_slot_epoch_seconds"',
            self.runtime_variables,
        )
        self.assertIn(
            "local.validator_bootstrap_slot_epochs[count.index]",
            self.runtime,
        )
        self.assertIn(
            'output "validator_bootstrap_finality_readback"',
            self.runtime_outputs,
        )
        self.assertIn(
            "VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON",
            self.validator_foundation_release,
        )
        self.assertIn(
            "RENEW_EXPIRED_QUIESCED_EPOCH",
            self.validator_foundation_release,
        )
        self.assertIn(
            "validator_bootstrap_slot_epoch_seconds",
            self.foundation_script,
        )
        self.assertIn(
            "rolling_epoch_renewal_prefix_count",
            self.foundation_script,
        )
        self.assertIn("terraform_bootstrap:", self.foundation_script)
        self.assertIn("epoch_renewal:", self.foundation_script)
        self.assertIn("user_data_replace_on_change = true", self.runtime)

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
            '["public_services_acceptance_readback","value","enabled"]',
            "read_required_json_boolean",
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
            "Generate or renew the shared automatic finality epoch",
            "activation_delay=7200",
            "now + activation_delay + interval - 1",
            "VALIDATOR_BLOCK_INTERVAL_SECONDS=$interval",
            "VALIDATOR_SLOT_EPOCH_SECONDS=$slot_epoch",
            'FOUNDATION_ROLLING_RELEASE: "true"',
            "automatic_finality_readback.value",
            "foundation apply requires automatic finality to be enabled",
            "automatic_finality_enabled: $automatic_finality_enabled",
            "validator_slot_epoch_seconds: $validator_slot_epoch_seconds",
        ):
            self.assertTrue(
                required in self.validator_foundation_release
                or required in self.foundation_script
            )

    def test_foundation_renewal_env_expansions_are_single_line_bash(self) -> None:
        for required in (
            'validator_bootstrap_slot_epochs_json="${VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"',
            'rolling_resume_prior_slot_epoch_seconds="${ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"',
            'rolling_epoch_renewal_performed="${ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"',
            'rolling_epoch_renewal_prefix_count="${ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"',
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn('"${\n', self.foundation_script)

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
            "(map(.head_height) | unique | length) == 1",
            "(.[0].head_height > $previous_height)",
            "observed_height=",
            "(map(.head_timestamp) | unique | length) == 1",
            "(map(.consensus.last_certificate | tojson) | unique | length) == 1",
            ".automatic_finality_enabled == true",
            ".automatic_finality_loop_running == true",
            ".block_interval_seconds == 30",
            ".slot_epoch_seconds == $slot_epoch",
            "ready_at=\"$((slot_epoch + 5))\"",
            "timeout-minutes: 210",
            "consecutive_advances: 2",
            "canonical_timestamp_delta_seconds:",
            "head_advanced: true",
            "final_height: $second[0][0].head_height",
        ):
            self.assertIn(required, self.validator_foundation_release)
        self.assertNotIn(
            "slot_epoch + ((initial_height + 1) * interval) + 5",
            self.validator_foundation_release,
        )

    def test_foundation_rollout_requires_per_validator_compatibility_gate(self) -> None:
        for required in (
            "python scripts/junca_live_rollout_prefix_gate.py",
            "--mode rolling",
            "write_rolling_compatibility_evidence",
            "READY_FOR_NEXT_VALIDATOR",
            "READY_FOR_SLOT_EPOCH",
            "READY_FOR_FINALITY_ENABLE",
            "ACCEPTED",
            "describe-instance-information",
            "systemctl is-active --quiet junca-validator.service",
            "mountpoint -q /var/lib/junca",
            "PRAGMA quick_check",
            "certificate_hash:",
            "certificate_height:",
            "certificate_block_hash:",
            'range($prefix; 3) | "aws_instance.validator[\\(.)]"',
            '$ARGS.positional == $expected',
        ):
            self.assertIn(required, self.foundation_script)

    def test_validator_readback_uses_exact_legacy_env_only_when_health_omits_all(
        self,
    ) -> None:
        jq_filter = finality_readback_filter(self.foundation_script)

        def resolve(health: dict, env: tuple[str, str, str]) -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    "jq",
                    "-c",
                    "-n",
                    "--argjson",
                    "health",
                    json.dumps(health),
                    "--argjson",
                    "runtime_automatic_finality_enabled",
                    env[0],
                    "--argjson",
                    "runtime_block_interval_seconds",
                    env[1],
                    "--argjson",
                    "runtime_slot_epoch_seconds",
                    env[2],
                    jq_filter,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        legacy = resolve({}, ("false", "0", "0"))
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(
            json.loads(legacy.stdout),
            {
                "automatic_finality_enabled": False,
                "block_interval_seconds": 0,
                "slot_epoch_seconds": 0,
                "health_supported": False,
            },
        )

        matching = resolve(
            {
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": 2_000_000_010,
            },
            ("true", "30", "2000000010"),
        )
        self.assertEqual(matching.returncode, 0, matching.stderr)
        self.assertTrue(json.loads(matching.stdout)["health_supported"])

        rejected = (
            (
                {
                    "automatic_finality_enabled": False,
                    "block_interval_seconds": 0,
                },
                ("false", "0", "0"),
                "partially missing",
            ),
            (
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                    "slot_epoch_seconds": 2_000_000_010,
                },
                ("false", "0", "0"),
                "differ",
            ),
            (
                {
                    "automatic_finality_enabled": "false",
                    "block_interval_seconds": 0,
                    "slot_epoch_seconds": 0,
                },
                ("false", "0", "0"),
                "differ",
            ),
        )
        for health, env, message in rejected:
            with self.subTest(health=health):
                result = resolve(health, env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)

    def test_runtime_env_readback_rejects_missing_duplicate_and_invalid_values(
        self,
    ) -> None:
        block = runtime_finality_readback_block(self.foundation_script)
        accepted = (
            (
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=2000000010\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=true\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=30\n"
                "TESTNET_SLOT_EPOCH_SECONDS=2000000010\n"
            ),
        )
        rejected = (
            (
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=False\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=30\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            ),
            (
                "AUTOMATIC_FINALITY_ENABLED=true\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=30\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime_env = pathlib.Path(directory) / "runtime.env"
            executable = block.replace(
                "/etc/junca/runtime.env", str(runtime_env)
            )
            for content in accepted:
                with self.subTest(accepted=content):
                    runtime_env.write_text(content, encoding="utf-8")
                    result = subprocess.run(
                        ["bash", "-c", "set -euo pipefail\n" + executable],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
            for content in rejected:
                with self.subTest(rejected=content):
                    runtime_env.write_text(content, encoding="utf-8")
                    result = subprocess.run(
                        ["bash", "-c", "set -euo pipefail\n" + executable],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_finality_mutation_requires_exact_keys_before_and_after_sed(
        self,
    ) -> None:
        block = set_runtime_finality_block(self.foundation_script)
        expected_artifact = "a" * 64

        def execute(
            runtime_env: pathlib.Path,
            content: str,
            *,
            allow_missing: str,
            finality_enabled: str = "false",
            block_interval: str = "0",
            slot_epoch: str = "0",
            expected: str = expected_artifact,
        ) -> subprocess.CompletedProcess:
            runtime_env.write_text(content, encoding="utf-8")
            executable = block.replace(
                "/etc/junca/runtime.env", str(runtime_env)
            )
            executable = executable.replace(
                "/etc/junca/.runtime.env.XXXXXX",
                str(runtime_env.parent / ".runtime.env.XXXXXX"),
            )
            executable = (
                executable.replace(
                    "${expected_artifact_sha256}", expected
                )
                .replace(
                    "${allow_missing_finality_keys}", allow_missing
                )
                .replace("${finality_enabled}", finality_enabled)
                .replace("${block_interval}", block_interval)
                .replace("${slot_epoch}", slot_epoch)
            )
            return subprocess.run(
                ["bash", "-c", "set -euo pipefail\n" + executable],
                check=False,
                capture_output=True,
                text=True,
            )

        with tempfile.TemporaryDirectory() as directory:
            runtime_env = pathlib.Path(directory) / "runtime.env"
            result = execute(
                runtime_env,
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                "AUTOMATIC_FINALITY_ENABLED=true\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=30\n"
                "TESTNET_SLOT_EPOCH_SECONDS=2000000010\n",
                allow_missing="false",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                runtime_env.read_text(encoding="utf-8"),
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n",
            )

            result = execute(
                runtime_env,
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n",
                allow_missing="true",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                runtime_env.read_text(encoding="utf-8"),
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n",
            )

            rejected = (
                (
                    f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                    "AUTOMATIC_FINALITY_ENABLED=false\n",
                    {"allow_missing": "true"},
                ),
                (
                    f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                    "AUTOMATIC_FINALITY_ENABLED=false\n"
                    "AUTOMATIC_FINALITY_ENABLED=false\n"
                    "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                    "TESTNET_SLOT_EPOCH_SECONDS=0\n",
                    {"allow_missing": "true"},
                ),
                (
                    f"NODE_ARTIFACT_SHA256={expected_artifact}\n",
                    {"allow_missing": "false"},
                ),
                (
                    f"NODE_ARTIFACT_SHA256={'b' * 64}\n",
                    {"allow_missing": "true"},
                ),
                (
                    f"NODE_ARTIFACT_SHA256={expected_artifact}\n",
                    {
                        "allow_missing": "true",
                        "finality_enabled": "true",
                        "block_interval": "30",
                        "slot_epoch": "2000000010",
                    },
                ),
            )
            for content, arguments in rejected:
                with self.subTest(rejected=(content, arguments)):
                    before = hashlib.sha256(content.encode()).hexdigest()
                    result = execute(runtime_env, content, **arguments)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    after = hashlib.sha256(runtime_env.read_bytes()).hexdigest()
                    self.assertEqual(after, before)

    def test_finality_call_sites_bind_exact_runtime_and_legacy_mode(self) -> None:
        for required in (
            "resume_updated_count=0",
            'resume_updated_count="$(jq -er \'.updated_count\' "$resume_path")"',
            "build_pre_rollout_finality_bindings",
            'build_runtime_finality_bindings \\\n'
            '          "$NODE_ARTIFACT_SHA256" false "$new_instance"',
            'build_runtime_finality_bindings \\\n'
            '        "$NODE_ARTIFACT_SHA256" false '
            '"${activated_instances[@]}"',
            "NODE_ARTIFACT_SHA256=${expected_artifact_sha256}",
        ):
            self.assertIn(required, self.foundation_script)

    def test_finality_binding_builders_are_unambiguous_and_ordered(self) -> None:
        functions = runtime_finality_binding_functions(
            self.foundation_script
        )
        self.assertNotIn("--args", functions)
        self.assertIn("--argjson instances", functions)
        target = "a" * 64
        previous = "b" * 64
        instances = (
            "i-0709abcdef1234567",
            "i-0809abcdef1234567",
            "i-0909abcdef1234567",
        )

        def run(
            function: str, arguments: tuple[str, ...]
        ) -> subprocess.CompletedProcess:
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n"
                    + functions
                    + f'\n{function} "$@"\n',
                    "binding-test",
                    *arguments,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        for selected in (instances[:1], instances):
            with self.subTest(homogeneous=selected):
                result = run(
                    "build_runtime_finality_bindings",
                    (target, "false", *selected),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bindings = json.loads(result.stdout)
                self.assertEqual(
                    [item["instance_id"] for item in bindings],
                    list(selected),
                )
                self.assertTrue(
                    all(
                        item["expected_artifact_sha256"] == target
                        and item["allow_missing_finality_keys"] is False
                        for item in bindings
                    )
                )

        for updated_count in range(4):
            with self.subTest(updated_count=updated_count):
                baseline = [
                    {
                        "validator_id": f"validator-0{index + 1}",
                        "instance_id": instance_id,
                        "runtime_version": (
                            target if index < updated_count else previous
                        ),
                        "ami_id": "ami-11111111111111111",
                        "target_runtime": index < updated_count,
                    }
                    for index, instance_id in enumerate(instances)
                ]
                result = run(
                    "build_pre_rollout_finality_bindings",
                    (
                        str(updated_count),
                        target,
                        json.dumps(baseline),
                        *instances,
                    ),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bindings = json.loads(result.stdout)
                self.assertEqual(
                    [item["instance_id"] for item in bindings],
                    list(instances),
                )
                for index, item in enumerate(bindings):
                    is_target = index < updated_count
                    self.assertEqual(
                        item["expected_artifact_sha256"],
                        target if is_target else previous,
                    )
                    self.assertEqual(
                        item["allow_missing_finality_keys"],
                        not is_target,
                    )

        rejected = (
            (
                "build_runtime_finality_bindings",
                (target, "false"),
            ),
            (
                "build_runtime_finality_bindings",
                (target, "false", *instances, "i-0a09abcdef1234567"),
            ),
            (
                "build_runtime_finality_bindings",
                (target, "false", "invalid-instance"),
            ),
            (
                "build_pre_rollout_finality_bindings",
                ("-1", target, previous, *instances),
            ),
            (
                "build_pre_rollout_finality_bindings",
                ("4", target, previous, *instances),
            ),
            (
                "build_pre_rollout_finality_bindings",
                ("0", target, previous, *instances[:2]),
            ),
            (
                "build_pre_rollout_finality_bindings",
                ("0", target, previous, instances[0], instances[0], instances[2]),
            ),
        )
        for function, arguments in rejected:
            with self.subTest(rejected=(function, arguments)):
                result = run(function, arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_finality_preflight_is_read_only_and_precedes_all_mutation(self) -> None:
        block = runtime_finality_preflight_block(self.foundation_script)
        self.assertNotIn("sed ", block)
        self.assertNotIn("mv ", block)
        self.assertNotIn("printf ", block)
        preflight_loop = self.foundation_script.index(
            "# Complete every read-only preflight before any runtime.env mutation."
        )
        mutation_loop = self.foundation_script.index(
            "# Dispatch every mutation before collecting any result"
        )
        collect_loop = self.foundation_script.index(
            '! wait_for_ssm_command_result \\\n'
            '        "${mutation_command_ids[$index]}"'
        )
        compensation = self.foundation_script.index(
            "# Best-effort compensation always returns every reachable node"
        )
        self.assertLess(preflight_loop, mutation_loop)
        self.assertLess(mutation_loop, collect_loop)
        self.assertLess(collect_loop, compensation)
        for required in (
            "mutation_failed=true",
            "finality-compensation-${instance_id}.json",
            "finality-compensation-readback-${instance_id}.json",
            "render_runtime_finality_mutation \\\n"
            "          false 0 0",
            "render_runtime_finality_readback \\\n"
            "          false 0 0",
            "finality-compensation-summary.json",
            "exact_disabled_readback_status:",
            'runtime_env_tmp="\\$(mktemp /etc/junca/.runtime.env.XXXXXX)"',
            'mv -f "\\$runtime_env_tmp" "\\$runtime_env"',
        ):
            self.assertIn(required, self.foundation_script)

    def test_compensation_readback_requires_exact_disabled_values(self) -> None:
        block = runtime_finality_exact_readback_block(
            self.foundation_script
        )
        expected_artifact = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            runtime_env = pathlib.Path(directory) / "runtime.env"
            executable = (
                block.replace(
                    "/etc/junca/runtime.env", str(runtime_env)
                )
                .replace(
                    "${expected_artifact_sha256}", expected_artifact
                )
                .replace("${finality_enabled}", "false")
                .replace("${block_interval}", "0")
                .replace("${slot_epoch}", "0")
            )
            disabled = (
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                "AUTOMATIC_FINALITY_ENABLED=false\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=0\n"
                "TESTNET_SLOT_EPOCH_SECONDS=0\n"
            )
            runtime_env.write_text(disabled, encoding="utf-8")
            result = subprocess.run(
                ["bash", "-c", "set -euo pipefail\n" + executable],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            runtime_env.write_text(
                f"NODE_ARTIFACT_SHA256={expected_artifact}\n"
                "AUTOMATIC_FINALITY_ENABLED=true\n"
                "TESTNET_BLOCK_INTERVAL_SECONDS=30\n"
                "TESTNET_SLOT_EPOCH_SECONDS=2000000010\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "-c", "set -euo pipefail\n" + executable],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_finality_activation_is_separate_and_manual_vote_is_disabled(self) -> None:
        disable_index = self.foundation_script.index(
            '0 0 "$pre_rollout_finality_bindings"'
        )
        replacement_index = self.foundation_script.index(
            'for address in "${validator_replacements[@]}"'
        )
        epoch_index = self.foundation_script.index(
            '0 "$validator_slot_epoch_seconds" "$activated_finality_bindings"'
        )
        enable_index = self.foundation_script.index(
            '30 "$validator_slot_epoch_seconds" "$activated_finality_bindings"'
        )
        self.assertLess(disable_index, replacement_index)
        self.assertLess(replacement_index, epoch_index)
        self.assertLess(epoch_index, enable_index)
        for workflow in (
            self.validator_foundation_release,
            self.validator_runtime_recovery,
        ):
            self.assertNotIn("junca_broadcastVote", workflow)
            self.assertNotIn("ssm-broadcast", workflow)

    def test_rollback_rehearsal_is_bound_to_no_state_rewind(self) -> None:
        for required in (
            "rollback-rehearsal.json",
            "rollback-snapshot-readback.json",
            "snapshot_restore_performed: false",
            "no_state_rewind: true",
            "durable_volume_reused: true",
            "state_rewind_permitted: false",
            "rollback_snapshot_id:",
            "volume_id:",
            "certificate_hash:",
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn(
            "(map(.head_height) | unique) == [$expected_height]",
            self.validator_foundation_release,
        )

    def test_restored_snapshot_normalization_is_identical_and_fail_closed(
        self,
    ) -> None:
        foundation_filter = restored_snapshot_filter(
            self.foundation_script
        )
        release_filter = restored_snapshot_filter(
            self.public_release_script
        )
        self.assertEqual(foundation_filter, release_filter)

        accepted = (
            ([None, None, None], None),
            (["", "", ""], None),
            (
                [
                    "snap-00000001",
                    "snap-00000002",
                    "snap-00000003",
                ],
                [
                    "snap-00000001",
                    "snap-00000002",
                    "snap-00000003",
                ],
            ),
        )
        for values, expected in accepted:
            with self.subTest(accepted=values):
                payload = [
                    {"restored_snapshot": value} for value in values
                ]
                result = subprocess.run(
                    ["jq", "-c", foundation_filter],
                    input=json.dumps(payload),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

        rejected = (
            [None, None],
            [None, None, None, None],
            [None, "", None],
            ["", "", "snap-00000001"],
            [None, "snap-00000001", "snap-00000002"],
            ["snap-00000001"] * 3,
            ["snap-00000001", "snap-00000002", "snap-invalid"],
            ["snap-00000001", "snap-00000002", None],
        )
        for values in rejected:
            with self.subTest(rejected=values):
                payload = [
                    {"restored_snapshot": value} for value in values
                ]
                result = subprocess.run(
                    ["jq", "-c", foundation_filter],
                    input=json.dumps(payload),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("restored snapshots must", result.stderr)

    def test_resumable_rollout_is_run_request_and_evidence_bound(self) -> None:
        for required in (
            "resume_run_id:",
            "Resolve exact resumable rolling evidence",
            ".conclusion == \"failure\"",
            "junca-validator-foundation-release-${ROLLING_RESUME_RUN_ID}",
            "sha256sum -c rolling-resume-evidence.json.sha256",
            ".producer_run_id == $producer_run_id",
            ".ami_run_id == $ami_run_id",
            ".manifest_gate_run_id == $manifest_gate_run_id",
            ".candidate.request_sha256 == $request_sha256",
            ".candidate.manifest_decision_sha256 ==",
        ):
            self.assertIn(required, self.validator_foundation_release)
        for required in (
            "junca-validator-rolling-resume/v1",
            "ROLLING_RESUME_EVIDENCE_PATH",
            "ROLLING_RESUME_RUN_ID",
            "MANIFEST_DECISION_SHA256",
            "rolling-resume-evidence.json.sha256",
            "live_updated_count",
            "prior_updated_count",
            'test "$live_updated_count" -ge "$prior_updated_count"',
            'test "$live_updated_count" -le '
            '"$((prior_updated_count + 1))"',
            "$before.instance_id == $after.instance_id",
            "$after.head_height >= $before.head_height",
            "$after.head_hash == $before.head_hash",
            "$after.certificate_hash == $before.certificate_hash",
        ):
            self.assertIn(required, self.foundation_script)

    def test_resume_can_adopt_one_live_prefix_across_a_workflow_head_fix(self) -> None:
        resolve_head = self.validator_foundation_release.index(
            "Resolve immutable candidate provenance head"
        )
        verify_candidate = self.validator_foundation_release.index(
            "Verify immutable AMI and manifest workflow provenance"
        )
        self.assertLess(resolve_head, verify_candidate)
        for required in (
            'candidate_head="$GITHUB_SHA"',
            ".candidate.provenance_head_sha // .head_sha",
            ".head_sha == $producer_head",
            'compare/${candidate_head}...${GITHUB_SHA}',
            "--mode recovery-head",
            "recovery-head-decision.json",
            'echo "ROLLING_CANDIDATE_HEAD_SHA=$candidate_head"',
            '--arg head "$ROLLING_CANDIDATE_HEAD_SHA"',
            ".candidate.source_commit == $source_commit",
            ".candidate.node_artifact_sha256 == $node_sha256",
            ".candidate.genesis_sha256 == $genesis_sha256",
            ".candidate.ami_id == $ami_id",
            ".candidate.request_sha256 == $request_sha256",
            ".candidate.manifest_decision_sha256 ==",
        ):
            self.assertIn(required, self.validator_foundation_release)
        for required in (
            "ROLLING_CANDIDATE_HEAD_SHA",
            "candidate_provenance_head_sha",
            ".candidate.provenance_head_sha // .head_sha",
            "write_live_rollout_prefix_readback",
            "live-prefix-volume-$((index + 1)).json",
            "live-prefix-rollback-snapshots.json",
            "verify_rollback_snapshots",
            ".[0].VolumeId == $volume_id",
            "rollback: $rollback[0]",
            'jq -er \'.live_updated_count\' '
            "artifacts/live-prefix-decision.json",
            'build_pre_rollout_finality_bindings \\\n'
            '      "$live_updated_count"',
        ):
            self.assertIn(required, self.foundation_script)
        live_readback_definition = self.foundation_script.index(
            "write_live_rollout_prefix_readback() {"
        )
        live_readback_call = self.foundation_script.index(
            "write_live_rollout_prefix_readback \\"
        )
        first_mutation = self.foundation_script.index(
            "set_runtime_finality \\\n    0 0", live_readback_call
        )
        volume_readback = self.foundation_script.index(
            "artifacts/live-prefix-volume-$((index + 1)).json",
            live_readback_definition,
        )
        rollback_floor = self.foundation_script.index(
            "--slurpfile rollback", live_readback_definition
        )
        snapshot_readback = self.foundation_script.index(
            "verify_rollback_snapshots \\", live_readback_definition
        )
        self.assertLess(volume_readback, first_mutation)
        self.assertLess(snapshot_readback, first_mutation)
        self.assertLess(rollback_floor, first_mutation)

    def test_required_boolean_readback_accepts_false_and_rejects_invalid_types(
        self,
    ) -> None:
        helper = required_json_boolean_function(self.foundation_script)
        json_path = '["automatic_finality_readback","value","enabled"]'
        cases = (
            (
                {"automatic_finality_readback": {"value": {"enabled": False}}},
                0,
                "false",
            ),
            (
                {"automatic_finality_readback": {"value": {"enabled": True}}},
                0,
                "true",
            ),
            (
                {"automatic_finality_readback": {"value": {"enabled": "false"}}},
                5,
                "",
            ),
            (
                {"automatic_finality_readback": {"value": {"enabled": None}}},
                5,
                "",
            ),
            ({"automatic_finality_readback": {"value": {}}}, 5, ""),
        )
        for payload, expected_exit, expected_stdout in cases:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    source = pathlib.Path(directory) / "source.json"
                    source.write_text(json.dumps(payload), encoding="utf-8")
                    result = subprocess.run(
                        [
                            "bash",
                            "-c",
                            "set -euo pipefail\n"
                            + helper
                            + '\nread_required_json_boolean "$JSON_PATH" "$SOURCE_PATH"\n',
                        ],
                        env={
                            "PATH": "/usr/bin:/bin",
                            "JSON_PATH": json_path,
                            "SOURCE_PATH": str(source),
                        },
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(result.stdout.strip(), expected_stdout)

        self.assertIn(
            "read_required_json_boolean \\\n"
            "      '[\"automatic_finality_readback\",\"value\",\"enabled\"]'",
            self.foundation_script,
        )
        self.assertNotIn(
            "jq -er '.automatic_finality_readback.value.enabled'",
            self.foundation_script,
        )

    def test_live_prefix_repairs_only_a_safely_readable_stopped_service(self) -> None:
        for required in (
            "validate_validator_service_recovery_evidence() {",
            "ensure_validator_service_available() {",
            'before_status="$(systemctl is-active '
            'junca-validator.service 2>/dev/null || true)"',
            "mountpoint -q /var/lib/junca",
            "PRAGMA quick_check",
            "render_canonical_validator_runtime_env",
            "validator-runtime.tar.gz",
            "canonical_runtime_env_sha256",
            "! -e /etc/junca/runtime.env",
            "mktemp /etc/junca/.runtime.env.XXXXXX",
            "systemctl stop junca-validator.service",
            'sync -f "$runtime_env_tmp"',
            'ln "$runtime_env_tmp" /etc/junca/runtime.env',
            "runtime_env_created=true",
            "runtime_env_created_identity",
            "runtime_env_admission_identity",
            'runtime_env_owner="$(stat -c',
            'runtime_env_mode="$(stat -c',
            'runtime_env_link_count="$(stat -c',
            "runtime_env_schema_verified=true",
            "runtime_env_required_assignment_count=18",
            "runtime_env_persistence_verified=true",
            "runtime_env_post_restart_verified=true",
            "runtime_env_repaired=true",
            "repair_rollback_attempted=true",
            "repair_rollback_succeeded=true",
            "repair_rollback_persistence_verified=true",
            'systemctl stop junca-validator.service || true',
            "rm -f /etc/junca/runtime.env",
            "sync -f /etc/junca",
            'test("^[0-9a-f]{64}$")',
            '"$before_status" != "active"',
            '"$durable_mount_verified" == true',
            "verify_durable_mount_persistence_contract()",
            "verify_durable_state_mount()",
            "nvme-Amazon_Elastic_Block_Store_",
            'actual_serial="$(lsblk -ndo SERIAL',
            'findmnt -rn -S "$resolved_state_device" -o TARGET',
            "systemctl restart junca-validator-state.service",
            "durable_mount_repair_attempted=true",
            "durable_mount_repaired=true",
            "durable_mount_persistence_verified=true",
            "durable_mount_volume_id",
            '"$state_store_integrity" == true',
            '"$runtime_env_verified" == true',
            "systemctl restart junca-validator.service || restart_exit=$?",
            "for attempts in $(seq 1 60)",
            'health_status="$(jq -r ',
            ".status // empty",
            "junca-validator-service-recovery/v2",
            "wait_for_ssm_command_result",
            "mainnet_activation_authorized: false",
        ):
            self.assertIn(required, self.foundation_script)
        definition = self.foundation_script.index(
            "write_live_rollout_prefix_readback() {"
        )
        recovery = self.foundation_script.index(
            "ensure_validator_service_available \\", definition
        )
        strict_readback = self.foundation_script.index(
            "capture_validator_observation \\", recovery
        )
        first_mutation = self.foundation_script.index(
            "set_runtime_finality \\\n    0 0", strict_readback
        )
        self.assertLess(recovery, strict_readback)
        self.assertLess(strict_readback, first_mutation)

        rollback = self.foundation_script.index(
            'if [[ "$accepted" != true &&',
        )
        evidence = self.foundation_script.index(
            "jq -n \\\n  --arg schema_version "
            '"junca-validator-service-recovery/v2"',
            rollback,
        )
        self.assertLess(rollback, evidence)
        self.assertLess(evidence, definition)
        self.assertIn(
            '"$(sha256sum /etc/junca/runtime.env | awk '
            "'{print $1}')\" == \\\n"
            '          "$canonical_runtime_env_sha256"',
            self.foundation_script[rollback:evidence],
        )
        self.assertIn(
            ".repair_rollback_attempted == false",
            self.foundation_script,
        )
        self.assertNotIn(
            'mv -f "$runtime_env_tmp" /etc/junca/runtime.env',
            self.foundation_script[rollback:evidence],
        )
        remote_recovery = validator_service_recovery_remote_script(
            self.foundation_script
        )
        for destructive in (
            "mkfs",
            "wipefs",
            "fsck",
            "umount",
            "detach-volume",
            "delete-volume",
        ):
            self.assertNotIn(destructive, remote_recovery)

        live_prefix = self.foundation_script.split(
            "write_live_rollout_prefix_readback() {", 1
        )[1].split("\n}\n\nwrite_rolling_compatibility_evidence()", 1)[0]
        attachment = live_prefix.index(
            "aws ec2 describe-volumes --volume-ids"
        )
        attachment_acceptance = live_prefix.index(
            '.[0].Attachments[0].State == "attached"',
            attachment,
        )
        recovery_call = live_prefix.index(
            "ensure_validator_service_available \\",
            attachment_acceptance,
        )
        self.assertLess(attachment, attachment_acceptance)
        self.assertLess(attachment_acceptance, recovery_call)

    def test_validator_service_recovery_remote_script_is_valid_bash(self) -> None:
        result = subprocess.run(
            ["bash", "-n"],
            input=validator_service_recovery_remote_script(
                self.foundation_script
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_prefix_binds_each_current_instance_to_exact_ami_provenance(
        self,
    ) -> None:
        definition = self.foundation_script.split(
            "write_live_rollout_prefix_readback() {", 1
        )[1].split("\n}\n\nwrite_rolling_readback()", 1)[0]
        for required in (
            "read_instance_ami_binding() {",
            "aws ec2 describe-instances",
            '--owners self',
            '"NodeArtifactSHA256"',
            '"GenesisSHA256"',
            '"SourceCommit"',
            '"Network"',
            '"Governance"',
            'ami_binding_path="artifacts/live-prefix-ami-binding-',
            'expected_ami_id="$binding_ami_id"',
            'expected_runtime_version="$binding_runtime_version"',
            'expected_ami_id="$evidence_ami_id"',
            'expected_runtime_version="$evidence_runtime_version"',
            'test "$evidence_instance_id" = "${current_instances[$index]}"',
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn(
            'expected_ami_id="$previous_ami_id"',
            definition,
        )
        self.assertNotIn(
            'expected_runtime_version="$previous_artifact_sha256"',
            definition,
        )

        account_id = "595710543956"
        region = "us-east-1"
        instance_id = "i-00000000000000001"
        ami_id = "ami-00000000000000001"
        runtime_version = "a" * 64
        genesis_sha256 = "b" * 64
        source_commit = "c" * 40
        instance = {
            "Reservations": [
                {
                    "OwnerId": account_id,
                    "Instances": [
                        {
                            "InstanceId": instance_id,
                            "ImageId": ami_id,
                            "State": {"Name": "running"},
                            "Placement": {
                                "AvailabilityZone": "us-east-1a"
                            },
                        }
                    ],
                }
            ]
        }
        image = {
            "Images": [
                {
                    "ImageId": ami_id,
                    "OwnerId": account_id,
                    "State": "available",
                    "ImageType": "machine",
                    "Architecture": "x86_64",
                    "VirtualizationType": "hvm",
                    "RootDeviceType": "ebs",
                    "Public": False,
                    "Tags": [
                        {
                            "Key": "NodeArtifactSHA256",
                            "Value": runtime_version,
                        },
                        {"Key": "GenesisSHA256", "Value": genesis_sha256},
                        {"Key": "SourceCommit", "Value": source_commit},
                        {"Key": "Network", "Value": "Public Testnet"},
                        {
                            "Key": "Governance",
                            "Value": "JAIOS Institutional Governance",
                        },
                    ],
                }
            ]
        }

        def execute(
            instance_payload: dict, image_payload: dict
        ) -> tuple[subprocess.CompletedProcess, dict | None]:
            with tempfile.TemporaryDirectory() as directory:
                temp = pathlib.Path(directory)
                fake_aws = temp / "aws"
                fake_aws.write_text(
                    textwrap.dedent(
                        """\
                        #!/usr/bin/env bash
                        set -euo pipefail
                        if [[ "$1 $2" == "ec2 describe-instances" ]]; then
                          printf '%s\\n' "$INSTANCE_RESPONSE"
                        elif [[ "$1 $2" == "ec2 describe-images" ]]; then
                          printf '%s\\n' "$IMAGE_RESPONSE"
                        else
                          exit 64
                        fi
                        """
                    ),
                    encoding="utf-8",
                )
                fake_aws.chmod(0o755)
                output = temp / "binding.json"
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        "set -euo pipefail\n"
                        + instance_ami_binding_function(
                            self.foundation_script
                        )
                        + '\nread_instance_ami_binding "$1" "$2"',
                        "instance-ami-binding-test",
                        instance_id,
                        str(output),
                    ],
                    env={
                        "PATH": f"{temp}:/usr/bin:/bin",
                        "AWS_ACCOUNT_ID": account_id,
                        "AWS_REGION": region,
                        "GENESIS_SHA256": genesis_sha256,
                        "INSTANCE_RESPONSE": json.dumps(instance_payload),
                        "IMAGE_RESPONSE": json.dumps(image_payload),
                    },
                    check=False,
                    capture_output=True,
                    text=True,
                )
                evidence = (
                    json.loads(output.read_text(encoding="utf-8"))
                    if output.exists()
                    else None
                )
                return result, evidence

        accepted, evidence = execute(instance, image)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["instance_id"], instance_id)
        self.assertEqual(evidence["ami_id"], ami_id)
        self.assertEqual(evidence["runtime_version"], runtime_version)
        self.assertEqual(evidence["source_commit"], source_commit)
        self.assertTrue(evidence["accepted"])

        invalid_payloads: list[tuple[dict, dict]] = []
        for field, value in (
            ("OwnerId", "000000000000"),
            ("State", "pending"),
            ("Architecture", "arm64"),
            ("VirtualizationType", "paravirtual"),
            ("RootDeviceType", "instance-store"),
            ("Public", True),
        ):
            changed_image = json.loads(json.dumps(image))
            changed_image["Images"][0][field] = value
            invalid_payloads.append((instance, changed_image))
        for key, value in (
            ("NodeArtifactSHA256", "not-a-digest"),
            ("GenesisSHA256", "d" * 64),
            ("SourceCommit", "not-a-commit"),
            ("Network", "Mainnet"),
            ("Governance", "untrusted"),
        ):
            changed_image = json.loads(json.dumps(image))
            for tag in changed_image["Images"][0]["Tags"]:
                if tag["Key"] == key:
                    tag["Value"] = value
            invalid_payloads.append((instance, changed_image))
        changed_instance = json.loads(json.dumps(instance))
        changed_instance["Reservations"][0]["Instances"][0]["State"][
            "Name"
        ] = "stopped"
        invalid_payloads.append((changed_instance, image))
        changed_instance = json.loads(json.dumps(instance))
        changed_instance["Reservations"][0]["OwnerId"] = "000000000000"
        invalid_payloads.append((changed_instance, image))

        for instance_payload, image_payload in invalid_payloads:
            with self.subTest(
                instance=instance_payload, image=image_payload
            ):
                rejected, rejected_evidence = execute(
                    instance_payload, image_payload
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIsNone(rejected_evidence)

    def test_service_recovery_remote_command_is_valid_bash(self) -> None:
        remote_script = validator_service_recovery_remote_script(
            self.foundation_script
        )
        self.assertNotIn("'\"'\"'", remote_script)
        result = subprocess.run(
            ["bash", "-n"],
            input=remote_script,
            env={"PATH": "/usr/bin:/bin"},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_env_schema_rejects_ambiguous_security_assignments(
        self,
    ) -> None:
        runtime_version = "a" * 64
        genesis_sha256 = "b" * 64
        signer = (
            "arn:aws:kms:us-east-1:595710543956:key/"
            "72960fd3-1860-41b7-bd2f-4f5b682805d1"
        )
        signer_bindings = (
            f"validator-01={signer},"
            "validator-02=arn:aws:kms:us-east-1:595710543956:key/"
            "f7c2e12c-43d0-45dc-a3ff-487253939a21,"
            "validator-03=arn:aws:kms:us-east-1:595710543956:key/"
            "96dfadf9-21ca-4169-9f2d-61120d173b13"
        )
        peers = (
            "validator-01=10.67.16.10:30303,"
            "validator-02=10.67.32.10:30303,"
            "validator-03=10.67.48.10:30303"
        )
        canonical = "\n".join(
            (
                "CHAIN_NAME=JUNCA Social Ecosystem Chain",
                "GOVERNANCE=JAIOS Institutional Governance",
                "NETWORK_NOTICE=Public Testnet / No Monetary Value",
                "VALIDATOR_ID=validator-01",
                "CHAIN_ID=20260723",
                f"GENESIS_SHA256={genesis_sha256}",
                f"NODE_ARTIFACT_SHA256={runtime_version}",
                f"SIGNER_RESOURCE_ARN={signer}",
                "AWS_REGION=us-east-1",
                "AWS_DEFAULT_REGION=us-east-1",
                "PUBLIC_RPC=false",
                "P2P_PORT=30303",
                f"VALIDATOR_SIGNER_BINDINGS={signer_bindings}",
                f"VALIDATOR_PEER_ENDPOINTS={peers}",
                "AUTOMATIC_FINALITY_ENABLED=false",
                "TESTNET_BLOCK_INTERVAL_SECONDS=0",
                "TESTNET_SLOT_EPOCH_SECONDS=0",
                "BRIDGE_ACTIVATED=false",
                "",
            )
        )
        variables = "\n".join(
            (
                "expected_validator_id=validator-01",
                f"expected_genesis_sha256={genesis_sha256}",
                f"expected_runtime_version={runtime_version}",
                f"expected_signer_arn={signer}",
                f"expected_signer_bindings={signer_bindings}",
                f"expected_peer_endpoints={peers}",
                "expected_automatic_finality_enabled=false",
                "expected_block_interval_seconds=0",
                "expected_slot_epoch_seconds=0",
            )
        )
        command = (
            "set -euo pipefail\n"
            + variables
            + "\n"
            + runtime_env_schema_functions(self.foundation_script)
            + '\nverify_runtime_env_schema "$1"'
        )
        invalid_contents = (
            canonical + "VALIDATOR_ID=validator-02\n",
            canonical + "  CHAIN_ID =20260723\n",
            canonical.replace("PUBLIC_RPC=false", "PUBLIC_RPC=true"),
            canonical.replace("BRIDGE_ACTIVATED=false\n", ""),
            canonical + "AUTOMATIC_FINALITY_ENABLED=true\n",
            canonical + "JUNCA_DEBUG=true\n",
            canonical + "export CHAIN_ID=20260723\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "runtime.env"
            path.write_text(canonical, encoding="utf-8")
            accepted = subprocess.run(
                ["bash", "-c", command, "runtime-schema-positive", str(path)],
                env={"PATH": "/usr/bin:/bin"},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            for content in invalid_contents:
                with self.subTest(content=content[-80:]):
                    path.write_text(content, encoding="utf-8")
                    rejected = subprocess.run(
                        [
                            "bash",
                            "-c",
                            command,
                            "runtime-schema-negative",
                            str(path),
                        ],
                        env={"PATH": "/usr/bin:/bin"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(rejected.returncode, 0)

    def test_canonical_runtime_env_renderer_is_exact_and_fail_closed(
        self,
    ) -> None:
        runtime_version = "a" * 64
        genesis_sha256 = "b" * 64
        signers = [
            "arn:aws:kms:us-east-1:595710543956:key/"
            "72960fd3-1860-41b7-bd2f-4f5b682805d1",
            "arn:aws:kms:us-east-1:595710543956:key/"
            "f7c2e12c-43d0-45dc-a3ff-487253939a21",
            "arn:aws:kms:us-east-1:595710543956:key/"
            "96dfadf9-21ca-4169-9f2d-61120d173b13",
        ]
        signer_bindings = ",".join(
            f"validator-0{index}={arn}"
            for index, arn in enumerate(signers, start=1)
        )
        peers = (
            "validator-01=10.67.16.10:30303,"
            "validator-02=10.67.32.10:30303,"
            "validator-03=10.67.48.10:30303"
        )
        function = canonical_validator_runtime_env_function(
            self.foundation_script
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail\n"
                + function
                + '\nrender_canonical_validator_runtime_env "$@"',
                "canonical-runtime-positive",
                "validator-01",
                runtime_version,
                genesis_sha256,
                signers[0],
                signer_bindings,
                peers,
                "false",
                "0",
                "0",
            ],
            env={"PATH": "/usr/bin:/bin"},
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VALIDATOR_ID=validator-01\n", result.stdout)
        self.assertIn(
            f"NODE_ARTIFACT_SHA256={runtime_version}\n", result.stdout
        )
        self.assertIn(
            f"VALIDATOR_SIGNER_BINDINGS={signer_bindings}\n", result.stdout
        )
        self.assertIn(f"VALIDATOR_PEER_ENDPOINTS={peers}\n", result.stdout)
        self.assertTrue(result.stdout.endswith("BRIDGE_ACTIVATED=false\n"))
        for invalid in (
            (
                "validator-04",
                "false",
                "0",
                "0",
                signer_bindings,
                peers,
            ),
            (
                "validator-01",
                "false",
                "30",
                "0",
                signer_bindings,
                peers,
            ),
            (
                "validator-01",
                "false",
                "0",
                "0",
                signer_bindings,
                peers.replace("10.67.48.10", "10.67.48.11"),
            ),
            (
                "validator-01",
                "false",
                "0",
                "0",
                signer_bindings.replace(signers[0], signers[1], 1),
                peers,
            ),
        ):
            with self.subTest(invalid=invalid):
                (
                    validator_id,
                    enabled,
                    interval,
                    epoch,
                    invalid_bindings,
                    invalid_peers,
                ) = invalid
                rejected = subprocess.run(
                    [
                        "bash",
                        "-c",
                        "set -euo pipefail\n"
                        + function
                        + '\nrender_canonical_validator_runtime_env "$@"',
                        "canonical-runtime-negative",
                        validator_id,
                        runtime_version,
                        genesis_sha256,
                        signers[0],
                        invalid_bindings,
                        invalid_peers,
                        enabled,
                        interval,
                        epoch,
                    ],
                    env={"PATH": "/usr/bin:/bin"},
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(rejected.returncode, 0)

    def test_service_recovery_evidence_rejects_unsafe_or_false_acceptance(
        self,
    ) -> None:
        expected_runtime_version = "a" * 64
        expected_runtime_env_sha256 = "c" * 64
        expected_state_volume_id = "vol-00000000000000001"
        valid = {
            "schema_version": "junca-validator-service-recovery/v2",
            "validator_id": "validator-01",
            "instance_id": "i-00000000000000001",
            "ami_id": "ami-00000000000000001",
            "before_status": "inactive",
            "restart_attempted": True,
            "restart_exit": 0,
            "durable_mount_verified": True,
            "durable_mount_volume_id": expected_state_volume_id,
            "durable_mount_device": "/dev/nvme1n1",
            "durable_mount_source": "/dev/nvme1n1",
            "durable_mount_filesystem": "ext4",
            "durable_mount_persistence_verified": True,
            "durable_mount_repair_attempted": True,
            "durable_mount_repaired": True,
            "durable_mount_repair_exit": 0,
            "state_store_integrity": True,
            "binary_artifact_verified": True,
            "genesis_verified": True,
            "runtime_directory_verified": True,
            "runtime_env_verified": True,
            "runtime_version": expected_runtime_version,
            "runtime_env_repair_attempted": True,
            "runtime_env_created": True,
            "runtime_env_created_identity": "2049:3100",
            "runtime_env_admission_identity": "2049:3100",
            "runtime_env_owner": "root:junca",
            "runtime_env_mode": "640",
            "runtime_env_link_count": 1,
            "runtime_env_schema_verified": True,
            "runtime_env_required_assignment_count": 18,
            "runtime_env_repaired": True,
            "runtime_env_persistence_verified": True,
            "runtime_env_post_restart_verified": True,
            "repair_rollback_attempted": False,
            "repair_rollback_succeeded": False,
            "repair_rollback_persistence_verified": False,
            "runtime_env_source": "canonical",
            "runtime_env_sha256": expected_runtime_env_sha256,
            "service_stop_exit": 0,
            "after_status": "active",
            "health_status": "healthy",
            "attempts": 2,
            "accepted": True,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        }
        invalid_cases = (
            {"restart_attempted": False},
            {"restart_exit": 1},
            {"durable_mount_verified": False},
            {"durable_mount_volume_id": "vol-00000000000000002"},
            {"durable_mount_device": "/dev/sdf"},
            {"durable_mount_source": "/dev/nvme2n1"},
            {"durable_mount_filesystem": "btrfs"},
            {"durable_mount_persistence_verified": False},
            {"durable_mount_repair_attempted": False},
            {"durable_mount_repaired": False},
            {"durable_mount_repair_exit": 1},
            {"state_store_integrity": False},
            {"binary_artifact_verified": False},
            {"genesis_verified": False},
            {"runtime_directory_verified": False},
            {"runtime_env_repair_attempted": False},
            {"runtime_env_created": False},
            {"runtime_env_created_identity": ""},
            {"runtime_env_created_identity": "not-an-inode"},
            {"runtime_env_admission_identity": ""},
            {"runtime_env_admission_identity": "2049:3101"},
            {"runtime_env_owner": "root:root"},
            {"runtime_env_mode": "644"},
            {"runtime_env_link_count": 2},
            {"runtime_env_schema_verified": False},
            {"runtime_env_required_assignment_count": 17},
            {"runtime_env_required_assignment_count": 19},
            {"runtime_env_persistence_verified": False},
            {"runtime_env_post_restart_verified": False},
            {"runtime_env_source": "operator"},
            {"runtime_env_sha256": "d" * 64},
            {"service_stop_exit": 1},
            {"runtime_version": "local-only"},
            {"after_status": "failed"},
            {"health_status": "degraded"},
            {"accepted": False},
            {"mainnet_changed": True},
            {"assets_moved": True},
            {"bridge_activated": True},
            {"mainnet_activation_authorized": True},
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence = pathlib.Path(directory) / "service-recovery.json"
            for update in invalid_cases:
                with self.subTest(update=update):
                    evidence.write_text(
                        json.dumps(valid | update),
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [
                            "bash",
                            "-c",
                            "set -euo pipefail\n"
                            + validator_service_recovery_validation_function(
                                self.foundation_script
                            )
                            + "\nvalidate_validator_service_recovery_evidence "
                            + '"$1" validator-01 i-00000000000000001 '
                            + "ami-00000000000000001 "
                            + f"{expected_runtime_version} "
                            + expected_runtime_env_sha256
                            + " "
                            + expected_state_volume_id,
                            "service-recovery-negative-test",
                            str(evidence),
                        ],
                        env={"PATH": "/usr/bin:/bin"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)

    def test_service_recovery_evidence_accepts_active_without_restart(self) -> None:
        expected_runtime_version = "b" * 64
        expected_runtime_env_sha256 = "e" * 64
        expected_state_volume_id = "vol-00000000000000001"
        evidence = {
            "schema_version": "junca-validator-service-recovery/v2",
            "validator_id": "validator-01",
            "instance_id": "i-00000000000000001",
            "ami_id": "ami-00000000000000001",
            "before_status": "active",
            "restart_attempted": False,
            "restart_exit": 0,
            "durable_mount_verified": True,
            "durable_mount_volume_id": expected_state_volume_id,
            "durable_mount_device": "/dev/nvme1n1",
            "durable_mount_source": "/dev/nvme1n1",
            "durable_mount_filesystem": "xfs",
            "durable_mount_persistence_verified": True,
            "durable_mount_repair_attempted": False,
            "durable_mount_repaired": False,
            "durable_mount_repair_exit": 0,
            "state_store_integrity": True,
            "binary_artifact_verified": True,
            "genesis_verified": True,
            "runtime_directory_verified": True,
            "runtime_env_verified": True,
            "runtime_version": expected_runtime_version,
            "runtime_env_repair_attempted": False,
            "runtime_env_created": False,
            "runtime_env_created_identity": "",
            "runtime_env_admission_identity": "2049:3100",
            "runtime_env_owner": "root:junca",
            "runtime_env_mode": "640",
            "runtime_env_link_count": 1,
            "runtime_env_schema_verified": True,
            "runtime_env_required_assignment_count": 18,
            "runtime_env_repaired": False,
            "runtime_env_persistence_verified": False,
            "runtime_env_post_restart_verified": True,
            "repair_rollback_attempted": False,
            "repair_rollback_succeeded": False,
            "repair_rollback_persistence_verified": False,
            "runtime_env_source": "existing",
            "runtime_env_sha256": "d" * 64,
            "service_stop_exit": 0,
            "after_status": "active",
            "health_status": "healthy",
            "attempts": 1,
            "accepted": True,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "service-recovery.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n"
                    + validator_service_recovery_validation_function(
                        self.foundation_script
                    )
                    + "\nvalidate_validator_service_recovery_evidence "
                    + '"$1" validator-01 i-00000000000000001 '
                    + "ami-00000000000000001 "
                    + f"{expected_runtime_version} "
                    + expected_runtime_env_sha256
                    + " "
                    + expected_state_volume_id,
                    "service-recovery-positive-test",
                    str(path),
                ],
                env={"PATH": "/usr/bin:/bin"},
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_post_apply_failures_are_checkpointed_and_ssm_errors_retry(self) -> None:
        for required in (
            "wait_for_ssm_online()",
            "junca-validator-ssm-online-readback/v1",
            "attempts: .",
            "accepted: false",
            "post-apply-validator-${index}-checkpoint.json",
            "terraform-apply started",
            "instance-output started",
            "ssm-online started",
            "state-volume started",
            "finality-quiesce started",
            "post-apply-validator-${index}-instances.json",
            "post-apply-validator-${index}-volume.json",
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn(
            'ping_status="$(aws ssm describe-instance-information',
            self.foundation_script,
        )
        capture = self.foundation_script.split(
            "capture_validator_observation() {", 1
        )[1].split("\n}\n\nwrite_live_rollout_prefix_readback()", 1)[0]
        self.assertIn("wait_for_ssm_online", capture)
        self.assertNotIn("describe-instance-information", capture)
        helper = self.foundation_script.split("wait_for_ssm_online() {", 1)[
            1
        ].split("\n}\n\nwrite_post_apply_checkpoint()", 1)[0]
        self.assertIn("if ping_status=", helper)
        self.assertIn("cli_exit=$?", helper)
        self.assertIn('if [[ "$attempt" -lt 60 ]]', helper)
        self.assertIn("sleep 10", helper)

    def test_ssm_online_retry_records_transient_cli_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            counter = temp / "counter"
            output = temp / "ssm-online.json"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n"
                    + ssm_online_function(self.foundation_script)
                    + textwrap.dedent(
                        """
                        aws() {
                          count=0
                          if [[ -f "$COUNTER_PATH" ]]; then
                            count="$(cat "$COUNTER_PATH")"
                          fi
                          count="$((count + 1))"
                          printf '%s' "$count" >"$COUNTER_PATH"
                          if [[ "$count" == 1 ]]; then
                            echo "transient describe error" >&2
                            return 42
                          fi
                          printf 'Online\\n'
                        }
                        sleep() { :; }
                        wait_for_ssm_online "$1" "$2"
                        """
                    ),
                    "ssm-retry-test",
                    "i-00000000000000001",
                    str(output),
                ],
                env={"PATH": "/usr/bin:/bin", "COUNTER_PATH": str(counter)},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(evidence["accepted"])
            self.assertEqual(evidence["observed_status"], "Online")
            self.assertEqual(len(evidence["attempts"]), 2)
            self.assertEqual(evidence["attempts"][0]["cli_exit"], 42)
            self.assertEqual(
                evidence["attempts"][0]["ping_status"], "AwsCliError"
            )
            self.assertIn(
                "transient describe error",
                evidence["attempts"][0]["stderr"],
            )
            self.assertEqual(evidence["attempts"][1]["cli_exit"], 0)

    def test_pre_mutation_snapshot_readback_rejects_aws_drift(self) -> None:
        state = [
            {"rollback_snapshot_id": f"snap-{index:017x}"}
            for index in range(1, 4)
        ]
        snapshots = [
            {
                "SnapshotId": item["rollback_snapshot_id"],
                "State": "completed",
                "Encrypted": True,
                "OwnerId": "595710543956",
            }
            for item in state
        ]

        def execute(response: dict) -> subprocess.CompletedProcess:
            with tempfile.TemporaryDirectory() as directory:
                return subprocess.run(
                    [
                        "bash",
                        "-c",
                        "set -euo pipefail\n"
                        + rollback_snapshot_function(self.foundation_script)
                        + textwrap.dedent(
                            """
                            aws() { printf '%s\\n' "$SNAPSHOT_RESPONSE"; }
                            verify_rollback_snapshots "$1" "$2"
                            """
                        ),
                        "snapshot-readback-test",
                        json.dumps(state),
                        str(pathlib.Path(directory) / "snapshots.json"),
                    ],
                    env={
                        "PATH": "/usr/bin:/bin",
                        "AWS_ACCOUNT_ID": "595710543956",
                        "SNAPSHOT_RESPONSE": json.dumps(response),
                    },
                    check=False,
                    capture_output=True,
                    text=True,
                )

        accepted = execute({"Snapshots": snapshots})
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        invalid = []
        for field, value in (
            ("State", "pending"),
            ("Encrypted", False),
            ("OwnerId", "000000000000"),
        ):
            changed = json.loads(json.dumps(snapshots))
            changed[0][field] = value
            invalid.append({"Snapshots": changed})
        invalid.extend(
            (
                {"Snapshots": snapshots[:2]},
                {
                    "Snapshots": snapshots[:2]
                    + [
                        {
                            **snapshots[2],
                            "SnapshotId": "snap-0000000000000000f",
                        }
                    ]
                },
            )
        )
        for response in invalid:
            with self.subTest(response=response):
                rejected = execute(response)
                self.assertNotEqual(rejected.returncode, 0, rejected.stdout)

    def test_resume_reuses_one_bound_unexpired_slot_epoch(self) -> None:
        for required in (
            'if [[ -n "${ROLLING_RESUME_EVIDENCE_PATH:-}" ]]',
            ".automatic_finality.block_interval_seconds",
            ".automatic_finality.slot_epoch_seconds",
            'test "$ROLLING_RESUME_RUN_ID" != "0"',
            'test "$remaining" -ge "$minimum_remaining"',
            'test "$remaining" -le "$maximum_remaining"',
            "minimum_remaining=900",
            "maximum_remaining=7230",
            "RENEW_EXPIRED_QUIESCED_EPOCH",
            "prior_bootstrap_epochs=",
            "ROLLING_EPOCH_RENEWAL_PERFORMED",
        ):
            self.assertIn(required, self.validator_foundation_release)
        for required in (
            "automatic_finality: {",
            "block_interval_seconds: 30",
            "slot_epoch_seconds: $validator_slot_epoch_seconds",
            "minimum_remaining_seconds: 900",
            "maximum_remaining_seconds: 7230",
            'epoch_remaining="$((validator_slot_epoch_seconds - '
            '$(date +%s)))"',
            'test "$epoch_remaining" -ge 900',
            'test "$epoch_remaining" -le 7230',
            ".automatic_finality.slot_epoch_seconds ==",
            "terraform_bootstrap.slot_epoch_seconds",
            "epoch_renewal:",
        ):
            self.assertIn(required, self.foundation_script)
        resume_index = self.validator_foundation_release.index(
            "Resolve exact resumable rolling evidence"
        )
        epoch_index = self.validator_foundation_release.index(
            "Generate or renew the shared automatic finality epoch"
        )
        apply_index = self.validator_foundation_release.index(
            "scripts/junca_public_testnet_foundation.sh foundation-apply"
        )
        self.assertLess(resume_index, epoch_index)
        self.assertLess(epoch_index, apply_index)

    def test_resumable_rollout_rejects_gap_and_unknown_ami(self) -> None:
        for required in (
            "target_ami_id: $target_ami_id",
            "ami_id: $ami_id",
            "expected_replacements=",
            "READY_FOR_NEXT_VALIDATOR",
            "READY_FOR_SLOT_EPOCH",
        ):
            self.assertIn(required, self.foundation_script)

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
            '.path == ".github/workflows/junca-validator-foundation-release.yml"',
            '.event == "workflow_dispatch"',
            '.head_branch == "main"',
            ".repository.full_name == $repository",
            ".head_repository.full_name == $repository",
            "ref: ${{ steps.foundation.outputs.head_sha }}",
            "junca-validator-foundation-release-"
            "${{ steps.foundation.outputs.run_id }}",
            "run-id: ${{ steps.foundation.outputs.run_id }}",
            "REQUEST_SHA256=$(jq -er .request_sha256",
            "request_sha256: $request_sha256",
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
