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


def rollback_snapshot_function(script: str) -> str:
    return script.split("verify_rollback_snapshots() {", 1)[1].split(
        "\n}\n\nwait_for_ssm_command()", 1
    )[0].join(("verify_rollback_snapshots() {", "\n}"))


def ssm_command_functions(script: str) -> str:
    return script.split("wait_for_ssm_command() {", 1)[1].split(
        "\nbuild_runtime_finality_bindings()", 1
    )[0].join(("wait_for_ssm_command() {", ""))


def set_runtime_finality_function(script: str) -> str:
    return script.split("set_runtime_finality() {", 1)[1].split(
        "\n}\n\nverify_validator_bootstrap_readiness()", 1
    )[0].join(("set_runtime_finality() {", "\n}"))


def marked_jq_filter(script: str, marker: str) -> str:
    return script.split(f"# BEGIN_{marker}", 1)[1].split(
        f"# END_{marker}", 1
    )[0]


# Public services remain disabled until validator quorum evidence is accepted.
class AwsFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = (ROOT / "infra/aws/bootstrap/main.tf").read_text(
            encoding="utf-8"
        )
        cls.iam_separation = (
            ROOT / "infra/aws/bootstrap/iam-separation.tf"
        ).read_text(encoding="utf-8")
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
        cls.image_builder = cls.iam_separation
        cls.validator_user_data = (
            ROOT
            / "infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"
        ).read_text(encoding="utf-8")
        cls.workflow = (
            ROOT
            / ".github/workflows/junca-social-ecosystem-chain-aws-iac.yml"
        ).read_text(encoding="utf-8")
        cls.execution_workflow_path = (
            ROOT
            / ".github/workflows/"
            "junca-social-ecosystem-chain-aws-foundation-execution.yml"
        )
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
        cls.self_permission_recovery_path = (
            ROOT
            / ".github/workflows/"
            "junca-chain-runtime-self-permission-recovery.yml"
        )
        cls.gates = json.loads(
            (
                ROOT
                / "config/junca_social_ecosystem_chain_aws_foundation_gates.pending.json"
            ).read_text(encoding="utf-8")
        )
        cls.cloud_role_policy = json.loads(
            (
                ROOT / "config/junca_public_testnet_cloud_role_policy.json"
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
            "local.validator_bootstrap_slot_epochs[index]",
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
        signer_boundary = self.iam_separation.split(
            'resource "aws_iam_role_policy" "validator_signer_boundary"', 1
        )[1].split(
            'resource "aws_iam_instance_profile" "validator"', 1
        )[0]
        self.assertIn('Sid      = "UseOnlyAssignedSigner"', signer_boundary)
        self.assertIn('Action   = "kms:Sign"', signer_boundary)
        self.assertIn(
            "Resource = aws_kms_key.validator_signer[count.index].arn",
            signer_boundary,
        )
        self.assertIn('Sid    = "VerifyValidatorQuorum"', signer_boundary)
        for action in ("kms:DescribeKey", "kms:GetPublicKey", "kms:Verify"):
            self.assertIn(f'"{action}"', signer_boundary)
        self.assertIn(
            "Resource = aws_kms_key.validator_signer[*].arn",
            signer_boundary,
        )
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
            'resource "aws_iam_role_policy" "ami_builder_controller"',
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

    def test_legacy_foundation_execution_workflow_is_retired(self) -> None:
        self.assertFalse(self.execution_workflow_path.exists())
        retired = {
            (item["workflow"], item["job"], item["call_index"]): item
            for item in self.cloud_role_policy[
                "repo_global_oidc_cutover_gate"
            ]["retired_credential_calls"]
        }
        entry = retired[
            (
                self.execution_workflow_path.name,
                "permission-readback",
                0,
            )
        ]
        self.assertEqual(
            entry["disposition"],
            "RETIRED_WORKFLOW_FILE_REMOVED",
        )
        self.assertIn("Legacy Foundation", entry["retirement_reason"])

    def test_foundation_plan_and_apply_are_durable_and_fail_closed(self) -> None:
        for required in (
            "public-testnet/bootstrap.tfstate",
            "public-testnet/terraform.tfstate",
            "foundation.tfplan",
            "BEGIN_ROLLING_FULL_PLAN_GATE",
            "BEGIN_ROLLING_TARGET_PLAN_GATE",
            "BEGIN_ROLLING_RECONCILE_PLAN_GATE",
            '.change.actions != ["no-op"]',
            '.change.replace_paths == [["ami"], ["user_data"]]',
            "enable_public_services: $enable_public_services",
            "public_services_acceptance_readback.value.enabled",
            "public-services stage while rotating validator",
            "quorum_verified: false",
            "public_services_enabled: $public_services_enabled",
            "terraform -chdir=infra/aws/public-testnet apply",
            "validator_state_volume_readback.value // []",
            "enable_validator_state_volumes: $enable_validator_state_volumes",
            "aws_volume_attachment.validator_state",
            "--slurpfile full_plan artifacts/foundation-plan.json",
            "$plan.complete == false",
            "$plan.configuration == $full_plan[0].configuration",
            "$plan.variables == $full_plan[0].variables",
            "expected_user_data_sha1",
            "validator_state_kms_key_arns",
            "candidate-root-snapshot-readback.json",
            "get-ebs-encryption-by-default",
            'test("^aws_instance\\\\.validator\\\\[[0-2]\\\\]$")',
            "describe-volumes --volume-ids",
        ):
            self.assertIn(required, self.foundation_script)
        for required in (
            "NODE_AMI_ID",
            "NODE_ARTIFACT_SHA256",
            "GENESIS_SHA256",
            "SOURCE_COMMIT",
            "scripts/junca_public_testnet_foundation.sh foundation-apply",
        ):
            self.assertIn(required, self.validator_foundation_release)

    def test_validator_release_pins_terraform_before_foundation_apply(self) -> None:
        setup_index = self.validator_foundation_release.index(
            "hashicorp/setup-terraform@"
            "b9cd54a3c349d3f38e8881555d616ced269862dd"
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
            'test "$AUTHORIZE_ROLLOUT" = "PUBLIC_TESTNET_ROLLOUT"',
            self.validator_foundation_release,
        )
        self.assertIn(
            'test "$GITHUB_REF" = "refs/heads/main"',
            self.validator_foundation_release,
        )
        self.assertIn(
            "git/ref/heads/release-candidate/${GITHUB_SHA}",
            self.validator_foundation_release,
        )
        job_header = self.validator_foundation_release.split(
            "deploy-and-accept:",
            1,
        )[1].split("steps:", 1)[0]
        self.assertNotIn("\n    if:", job_header)
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
            "sha256sum --strict --check SHA256SUMS",
            "find artifacts/ami -mindepth 1 -maxdepth 1",
            'test ! -L "$evidence"',
            'test ! -L "$checksum"',
            "(keys | sort) == ([",
            ".source_commit == $candidate_head",
            '.schema_version == "junca-validator-ami-build/v2"',
            ".candidate.ami_supply_chain.request_schema ==",
            ".candidate.ami_supply_chain.image_builder_arn ==",
            ".candidate.ami_supply_chain.parent_ami_id ==",
            ".candidate.ami_supply_chain.component_source_sha256 ==",
            ".candidate.ami_supply_chain.dependency_lock_sha256 ==",
            ".candidate.ami_supply_chain.supply_chain_policy_sha256 ==",
            ".candidate.ami_supply_chain.dnf_releasever ==",
            ".candidate.ami_supply_chain.python3_boto3_nevra ==",
            ".candidate.ami_supply_chain.python3_botocore_nevra ==",
            "Cross-bind live AMI supply-chain tags",
        ):
            self.assertIn(required, self.validator_foundation_release)
        artifact_exists = self.validator_foundation_release.index(
            'test -f "$evidence"'
        )
        artifact_verified = self.validator_foundation_release.index(
            '.state == "AMI_VERIFIED"'
        )
        manifest_exists = self.validator_foundation_release.index(
            'test -f "$decision"'
        )
        manifest_verified = self.validator_foundation_release.index(
            '.decision == "PROMOTION_GATE_PASS"'
        )
        apply_index = self.validator_foundation_release.index(
            "scripts/junca_public_testnet_foundation.sh foundation-apply"
        )
        self.assertLess(artifact_exists, artifact_verified)
        self.assertLess(artifact_verified, manifest_exists)
        self.assertLess(manifest_exists, manifest_verified)
        self.assertLess(manifest_verified, apply_index)
        self.assertEqual(
            self.validator_foundation_release.count(
                "sha256sum --strict --check SHA256SUMS"
            ),
            2,
        )
        provenance_index = self.validator_foundation_release.index(
            "Verify immutable AMI and manifest workflow provenance"
        )
        manifest_decision_index = self.validator_foundation_release.index(
            '.decision == "PROMOTION_GATE_PASS"'
        )
        oidc_index = self.validator_foundation_release.index(
            "aws-actions/configure-aws-credentials@"
            "acca2b1b2070338fb9fd1ca27ecee81d687e58e5"
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

    def test_rolling_plan_gates_reject_every_unallowlisted_non_noop(self) -> None:
        node_ami_id = "ami-0123456789abcdef0"
        root_kms_key_arn = (
            "arn:aws:kms:us-east-1:595710543956:key/"
            "00000000-0000-0000-0000-000000000000"
        )
        current_ids = [
            "i-00000000000000001",
            "i-00000000000000002",
            "i-00000000000000003",
        ]
        expected_user_data = [
            "0" * 40,
            "1" * 40,
            "2" * 40,
        ]
        volume_ids = [f"vol-{index + 1:017x}" for index in range(3)]
        rollback_snapshot_ids = [
            f"snap-{index + 1:017x}" for index in range(3)
        ]
        availability_zones = ["us-east-1a", "us-east-1b", "us-east-1c"]

        def plan(changes, drift=None, complete=True):
            return {
                "format_version": "1.2",
                "terraform_version": "1.9.8",
                "complete": complete,
                "applyable": bool(changes),
                "errored": False,
                "deferred_changes": [],
                "variables": {"release_binding": "canonical"},
                "configuration": {
                    "root_module": {"release_binding": "canonical"}
                },
                "resource_changes": changes,
                "resource_drift": drift or [],
            }

        def instance(index=0):
            profile = (
                "junca-social-ecosystem-chain-testnet-validator-"
                f"{index + 1}"
            )
            tags = {
                "Project": "JUNCA Social Ecosystem Chain",
                "Governance": "JAIOS Institutional Governance",
                "Network": "Public Testnet",
                "MonetaryUse": "None",
                "ManagedBy": "Terraform",
            }
            subnet_id = f"subnet-{index + 1:017x}"
            security_groups = [f"sg-{index + 1:017x}"]
            return {
                "address": f"aws_instance.validator[{index}]",
                "mode": "managed",
                "change": {
                    "actions": ["delete", "create"],
                    "replace_paths": [["ami"], ["user_data"]],
                    "before": {
                        "iam_instance_profile": profile,
                        "subnet_id": subnet_id,
                        "vpc_security_group_ids": security_groups,
                        "tags_all": tags,
                        "user_data": f"{index + 3}" * 40,
                        "root_block_device": [
                            {"kms_key_id": root_kms_key_arn}
                        ],
                    },
                    "after": {
                        "ami": node_ami_id,
                        "private_ip": [
                            "10.67.16.10",
                            "10.67.32.10",
                            "10.67.48.10",
                        ][index],
                        "associate_public_ip_address": False,
                        "instance_type": "m7i.large",
                        "iam_instance_profile": profile,
                        "subnet_id": subnet_id,
                        "vpc_security_group_ids": security_groups,
                        "tags_all": tags,
                        "monitoring": True,
                        "user_data": expected_user_data[index],
                        "user_data_replace_on_change": True,
                        "source_dest_check": True,
                        "metadata_options": [
                            {
                                "http_endpoint": "enabled",
                                "http_tokens": "required",
                            }
                        ],
                        "root_block_device": [
                            {
                                "encrypted": True,
                                "delete_on_termination": True,
                                "kms_key_id": None,
                                "volume_type": "gp3",
                                "volume_size": 200,
                                "iops": 6000,
                                "throughput": 250,
                            }
                        ],
                    },
                    "after_unknown": {
                        "root_block_device": [{"kms_key_id": True}]
                    },
                },
            }

        def target_attachment(kind, index=0):
            port = 8546 if kind == "rpc" else 3000
            return {
                "address":
                    f"aws_lb_target_group_attachment.{kind}[{index}]",
                "mode": "managed",
                "change": {
                    "actions": ["delete", "create"],
                    "replace_paths": [["target_id"]],
                    "before": {"target_group_arn": f"arn:target:{kind}"},
                    "after": {
                        "target_group_arn": f"arn:target:{kind}",
                        "port": port,
                    },
                    "after_unknown": {"target_id": True},
                },
            }

        def state_attachment(index=0):
            return {
                "address": f"aws_volume_attachment.validator_state[{index}]",
                "mode": "managed",
                "change": {
                    "actions": ["delete", "create"],
                    "replace_paths": [["instance_id"]],
                    "before": {"volume_id": f"vol-{index + 1:017x}"},
                    "after": {
                        "device_name": "/dev/sdf",
                        "volume_id": f"vol-{index + 1:017x}",
                        "force_detach": False,
                        "stop_instance_before_detaching": True,
                    },
                    "after_unknown": {"instance_id": True},
                },
            }

        def retained_state_drift(index):
            validator_number = f"{index + 1:02d}"
            tags = {
                "AssetsMoved": "false",
                "BridgeActivated": "false",
                "FailureDomain": availability_zones[index],
                "Governance": "JAIOS Institutional Governance",
                "JuncaFilesystemVerified": "true",
                "JuncaFinalityCertificateBackfilled": "true",
                "JuncaMigrationState": "VERIFIED_PASS",
                "JuncaRollbackSnapshotId": rollback_snapshot_ids[index],
                "JuncaStateStoreIntegrity": "true",
                "MainnetChanged": "false",
                "ManagedBy": "Terraform",
                "MigrationRequired": "false",
                "MonetaryUse": "None",
                "Name": (
                    "junca-social-ecosystem-chain-testnet-validator-"
                    f"{validator_number}-state"
                ),
                "Network": "Public Testnet",
                "Project": "JUNCA Social Ecosystem Chain",
                "PublicTestnetOnly": "true",
                "StatePath": "/var/lib/junca",
                "Validator": validator_number,
            }
            stable = {
                "id": current_ids[index],
                "root_block_device": [
                    {
                        "kms_key_id": root_kms_key_arn,
                        "tags": None,
                    }
                ],
            }
            after = json.loads(json.dumps(stable))
            after["root_block_device"][0]["tags"] = {}
            after["ebs_block_device"] = [
                {
                    "delete_on_termination": False,
                    "device_name": "/dev/sdf",
                    "encrypted": True,
                    "iops": 6000,
                    "kms_key_id": root_kms_key_arn,
                    "snapshot_id": "",
                    "tags": tags,
                    "tags_all": tags,
                    "throughput": 250,
                    "volume_id": volume_ids[index],
                    "volume_size": 200,
                    "volume_type": "gp3",
                }
            ]
            before = json.loads(json.dumps(stable))
            before["ebs_block_device"] = []
            return {
                "address": f"aws_instance.validator[{index}]",
                "mode": "managed",
                "type": "aws_instance",
                "name": "validator",
                "index": index,
                "change": {
                    "actions": ["update"],
                    "before": before,
                    "after": after,
                    "after_unknown": {},
                },
            }

        def alarm(index, replacement):
            stable = {"threshold": 1}
            return {
                "address":
                    f"aws_cloudwatch_metric_alarm.validator_status[{index}]",
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "replace_paths": [],
                    "before": stable | {
                        "dimensions": {"InstanceId": current_ids[index]}
                    },
                    "after": stable | {
                        "dimensions": (
                            None
                            if replacement
                            else {"InstanceId": current_ids[index]}
                        )
                    },
                    "after_unknown": (
                        {"dimensions": True} if replacement else {}
                    ),
                },
            }

        def evaluate(marker, value, arguments):
            command = ["jq", "-e"]
            for flag, key, item in arguments:
                command.extend((flag, key, item))
            command.append(marked_jq_filter(self.foundation_script, marker))
            return subprocess.run(
                command,
                input=json.dumps(value),
                text=True,
                capture_output=True,
                check=False,
            )

        target_changes = [
            instance(),
            target_attachment("rpc"),
            target_attachment("explorer"),
            state_attachment(),
        ]
        target_arguments = [
            ("--arg", "address", "aws_instance.validator[0]"),
            ("--arg", "node_ami_id", node_ami_id),
            ("--arg", "root_ebs_kms_key_arn", root_kms_key_arn),
            (
                "--argjson",
                "full_plan",
                json.dumps(
                    [
                        {
                            "variables": {
                                "release_binding": "canonical"
                            },
                            "configuration": {
                                "root_module": {
                                    "release_binding": "canonical"
                                }
                            },
                        }
                    ]
                ),
            ),
            (
                "--argjson",
                "expected_addresses",
                json.dumps([item["address"] for item in target_changes]),
            ),
            ("--argjson", "validator_state_enabled", "true"),
            (
                "--argjson",
                "validator_state_volume_ids",
                json.dumps(volume_ids),
            ),
            (
                "--argjson",
                "validator_state_kms_key_arns",
                json.dumps([root_kms_key_arn] * 3),
            ),
            (
                "--argjson",
                "validator_state_rollback_snapshot_ids",
                json.dumps(rollback_snapshot_ids),
            ),
            (
                "--argjson",
                "availability_zones",
                json.dumps(availability_zones),
            ),
            (
                "--argjson",
                "expected_user_data_sha1",
                json.dumps(expected_user_data),
            ),
        ]
        result = evaluate(
            "ROLLING_TARGET_PLAN_GATE",
            plan(
                target_changes,
                drift=[retained_state_drift(0)],
                complete=False,
            ),
            target_arguments,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        malicious = json.loads(json.dumps(target_changes))
        malicious.append(
            {
                "address": "aws_security_group.unapproved",
                "mode": "managed",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {},
                    "after_unknown": {},
                },
            }
        )
        self.assertNotEqual(
            evaluate(
                "ROLLING_TARGET_PLAN_GATE",
                plan(
                    malicious,
                    drift=[retained_state_drift(0)],
                    complete=False,
                ),
                target_arguments,
            ).returncode,
            0,
        )
        mismatched_target = plan(
            target_changes,
            drift=[retained_state_drift(0)],
            complete=False,
        )
        mismatched_target["configuration"] = {"root_module": {"evil": True}}
        self.assertNotEqual(
            evaluate(
                "ROLLING_TARGET_PLAN_GATE",
                mismatched_target,
                target_arguments,
            ).returncode,
            0,
        )
        bad_user_data = json.loads(json.dumps(target_changes))
        bad_user_data[0]["change"]["after"]["user_data"] = "d" * 40
        self.assertNotEqual(
            evaluate(
                "ROLLING_TARGET_PLAN_GATE",
                plan(
                    bad_user_data,
                    drift=[retained_state_drift(0)],
                    complete=False,
                ),
                target_arguments,
            ).returncode,
            0,
        )
        bad_drift = retained_state_drift(0)
        bad_drift["change"]["after"]["ebs_block_device"][0][
            "volume_id"
        ] = "vol-fffffffffffffffff"
        self.assertNotEqual(
            evaluate(
                "ROLLING_TARGET_PLAN_GATE",
                plan(target_changes, drift=[bad_drift], complete=False),
                target_arguments,
            ).returncode,
            0,
        )
        self.assertNotEqual(
            evaluate(
                "ROLLING_TARGET_PLAN_GATE",
                plan(
                    target_changes,
                    drift=[retained_state_drift(0)],
                    complete=True,
                ),
                target_arguments,
            ).returncode,
            0,
        )

        full_arguments = [
            ("--arg", "phase", "foundation-apply"),
            ("--arg", "node_ami_id", node_ami_id),
            ("--arg", "root_ebs_kms_key_arn", root_kms_key_arn),
            ("--argjson", "rolling_release", "true"),
            ("--argjson", "public_services_enabled", "true"),
            ("--argjson", "validator_state_enabled", "true"),
            (
                "--argjson",
                "validator_state_volume_ids",
                json.dumps(volume_ids),
            ),
            (
                "--argjson",
                "validator_state_kms_key_arns",
                json.dumps([root_kms_key_arn] * 3),
            ),
            (
                "--argjson",
                "validator_state_rollback_snapshot_ids",
                json.dumps(rollback_snapshot_ids),
            ),
            (
                "--argjson",
                "availability_zones",
                json.dumps(availability_zones),
            ),
            (
                "--argjson",
                "expected_user_data_sha1",
                json.dumps(expected_user_data),
            ),
            ("--argjson", "current_validator_ids", json.dumps(current_ids)),
        ]
        def replacement_suffix(prefix_count):
            changes = []
            for index in range(prefix_count, 3):
                changes.extend(
                    (
                        instance(index),
                        target_attachment("rpc", index),
                        target_attachment("explorer", index),
                        state_attachment(index),
                        alarm(index, True),
                    )
                )
            return changes

        for prefix_count in range(4):
            with self.subTest(resume_prefix_count=prefix_count):
                result = evaluate(
                    "ROLLING_FULL_PLAN_GATE",
                    plan(
                        replacement_suffix(prefix_count),
                        drift=[
                            retained_state_drift(index)
                            for index in range(3)
                        ],
                    ),
                    full_arguments,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        full_changes = replacement_suffix(0)
        self.assertNotEqual(
            evaluate(
                "ROLLING_FULL_PLAN_GATE",
                plan(
                    full_changes + malicious[-1:],
                    drift=[
                        retained_state_drift(index) for index in range(3)
                    ],
                ),
                full_arguments,
            ).returncode,
            0,
        )
        resume_suffix_with_extra_alarm = (
            replacement_suffix(2) + [alarm(0, False)]
        )
        self.assertNotEqual(
            evaluate(
                "ROLLING_FULL_PLAN_GATE",
                plan(
                    resume_suffix_with_extra_alarm,
                    drift=[
                        retained_state_drift(index) for index in range(3)
                    ],
                ),
                full_arguments,
            ).returncode,
            0,
        )

        reconcile_arguments = [
            ("--arg", "root_ebs_kms_key_arn", root_kms_key_arn),
            ("--argjson", "validator_ids", json.dumps(current_ids)),
            ("--argjson", "validator_state_enabled", "true"),
            (
                "--argjson",
                "validator_state_volume_ids",
                json.dumps(volume_ids),
            ),
            (
                "--argjson",
                "validator_state_kms_key_arns",
                json.dumps([root_kms_key_arn] * 3),
            ),
            (
                "--argjson",
                "validator_state_rollback_snapshot_ids",
                json.dumps(rollback_snapshot_ids),
            ),
            (
                "--argjson",
                "availability_zones",
                json.dumps(availability_zones),
            ),
        ]
        reconcile = plan(
            [alarm(1, False)],
            drift=[retained_state_drift(index) for index in range(3)],
        )
        result = evaluate(
            "ROLLING_RECONCILE_PLAN_GATE",
            reconcile,
            reconcile_arguments,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        reconcile["resource_changes"][0]["change"]["after"]["threshold"] = 2
        self.assertNotEqual(
            evaluate(
                "ROLLING_RECONCILE_PLAN_GATE",
                reconcile,
                reconcile_arguments,
            ).returncode,
            0,
        )
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
            "aws_ebs_volume.validator_state[index].id",
            "user_data = local.validator_user_data[count.index]",
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
            "JuncaPTRuntimeObservation",
            "junca_fixed_ssm_send_command",
            "certificate_hash:",
            "certificate_height:",
            "certificate_block_hash:",
            'range($prefix; 3) | "aws_instance.validator[\\(.)]"',
            '$ARGS.positional == $expected',
        ):
            self.assertIn(required, self.foundation_script)

    def test_runtime_observation_is_fixed_document_only(self) -> None:
        block = self.foundation_script.split(
            "capture_validator_observation() {", 1
        )[1].split("\nwrite_live_rollout_prefix_readback() {", 1)[0]
        self.assertIn("JuncaPTRuntimeObservation", block)
        self.assertIn("ValidatorId: $validator_id", block)
        self.assertIn("junca_fixed_ssm_send_command", block)
        self.assertNotIn("python3 -c", block)
        self.assertNotIn("readback_command", block)
        self.assertNotIn("AWS-RunShellScript", block)

    def test_fixed_runtime_observation_owns_exact_env_readback(self) -> None:
        document = (
            ROOT
            / "infrastructure/aws/ssm-documents/JuncaPTRuntimeObservation.yaml"
        ).read_text(encoding="utf-8")
        for required in (
            'fixed_env_count "$RUNTIME_ENV" "$runtime_key"',
            "AUTOMATIC_FINALITY_ENABLED TESTNET_BLOCK_INTERVAL_SECONDS",
            "TESTNET_SLOT_EPOCH_SECONDS BRIDGE_ACTIVATED",
            ".peer_count == 2",
            'health_supported: true',
            'access_class: "read-only"',
        ):
            self.assertIn(required, document)

    def test_fixed_finality_set_owns_atomic_mutation(self) -> None:
        document = (
            ROOT / "infrastructure/aws/ssm-documents/JuncaPTFinalitySet.yaml"
        ).read_text(encoding="utf-8")
        for required in (
            "readonly MUTATION_LOCK_DIRECTORY=/run/lock/junca-validator-mutation",
            "write_transaction_marker PREPARED",
            "write_transaction_marker ACCEPTED",
            "before_non_finality_sha256=",
            'transaction_state: "ACCEPTED"',
            ".peer_count == 2",
        ):
            self.assertIn(required, document)
        self.assertNotIn("AWS-RunShellScript", self.foundation_script)

    def test_finality_call_sites_bind_exact_runtime_and_legacy_mode(self) -> None:
        for required in (
            "resume_updated_count=0",
            'resume_updated_count="$(jq -er \'.updated_count\' "$resume_path")"',
            "build_pre_rollout_finality_bindings",
            'build_runtime_finality_bindings \\\n'
            '          "$NODE_ARTIFACT_SHA256" false \\\n'
            '          "[\\"validator-0$((index + 1))\\"]" "$new_instance"',
            'build_runtime_finality_bindings \\\n'
            '        "$NODE_ARTIFACT_SHA256" false \\\n'
            "        '[\"validator-01\",\"validator-02\",\"validator-03\"]'",
            "JuncaPTFinalityInspect",
            "JuncaPTFinalitySet",
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
                validator_ids = [
                    f"validator-0{index + 1}"
                    for index in range(len(selected))
                ]
                result = run(
                    "build_runtime_finality_bindings",
                    (
                        target,
                        "false",
                        json.dumps(validator_ids),
                        *selected,
                    ),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bindings = json.loads(result.stdout)
                self.assertEqual(
                    [item["instance_id"] for item in bindings],
                    list(selected),
                )
                self.assertEqual(
                    [item["validator_id"] for item in bindings],
                    validator_ids,
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
                (
                    target,
                    "false",
                    '["validator-01","validator-02","validator-03"]',
                    *instances,
                    "i-0a09abcdef1234567",
                ),
            ),
            (
                "build_runtime_finality_bindings",
                (target, "false", '["validator-01"]', "invalid-instance"),
            ),
            (
                "build_runtime_finality_bindings",
                (
                    target,
                    "false",
                    '["validator-01","validator-01","validator-03"]',
                    *instances,
                ),
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
            "JuncaPTFinalityInspect",
            "JuncaPTFinalitySet",
            "Mode: \"preflight\"",
            "Mode: \"exact\"",
            "AllowMissingFinalityKeys: \"false\"",
            "finality-compensation-summary.json",
            "exact_disabled_readback_status:",
            "junca_fixed_ssm_send_command",
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn("AWS-RunShellScript", self.foundation_script)

    def test_replacement_readiness_precedes_finality_mutation(self) -> None:
        script = self.foundation_script
        definition = script.index("verify_validator_bootstrap_readiness() {")
        call = script.index(
            "if ! verify_validator_bootstrap_readiness \\\n",
            definition,
        )
        quiesce = script.index(
            '"$index" finality-quiesce started',
            call,
        )
        root_volume = script.index(
            '"$index" root-volume started',
            definition,
        )
        ssm_online = script.index(
            '"$index" ssm-online started',
            root_volume,
        )
        self.assertLess(root_volume, ssm_online)
        self.assertLess(root_volume, call)
        self.assertLess(call, quiesce)
        for required in (
            "JuncaPTBootstrapReadiness",
            "ExpectedArtifactSha256:",
            "ExpectedGenesisSha256:",
            "junca_fixed_ssm_send_command",
            '"$index" runtime-readiness started',
            '"$index" runtime-readiness succeeded',
            "post-apply-validator-${index}-root-volume.json",
            ".KmsKeyId == $kms_key_arn",
        ):
            self.assertIn(required, script)
        self.assertNotIn("aws kms describe-key", script)
        readiness = script.split(
            "verify_validator_bootstrap_readiness() {", 1
        )[1].split("\ncapture_validator_observation() {", 1)[0]
        self.assertNotIn("python3 -c", readiness)
        self.assertNotIn("AWS-RunShellScript", readiness)

    def test_finality_preflight_failure_returns_before_mutation(self) -> None:
        block = self.foundation_script.split(
            "set_runtime_finality() {", 1
        )[1].split(
            "\nverify_validator_bootstrap_readiness() {", 1
        )[0]
        preflight_wait = block.index("if ! wait_for_ssm_command \\")
        preflight_return = block.index("return 1", preflight_wait)
        mutation = block.index(
            "# Dispatch every mutation",
            preflight_return,
        )
        self.assertLess(preflight_wait, preflight_return)
        self.assertLess(preflight_return, mutation)
        self.assertTrue(block.rstrip().endswith("return 0\n}"))

    def test_finality_preflight_failure_executes_zero_mutations(self) -> None:
        bindings = [
            {
                "validator_id": "validator-01",
                "instance_id": "i-00000000000000001",
                "expected_artifact_sha256": "1" * 64,
                "allow_missing_finality_keys": False,
            },
            {
                "validator_id": "validator-02",
                "instance_id": "i-00000000000000002",
                "expected_artifact_sha256": "2" * 64,
                "allow_missing_finality_keys": False,
            },
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            script = (
                "set -euo pipefail\n"
                + set_runtime_finality_function(self.foundation_script)
                + textwrap.dedent(
                    f"""
                    junca_fixed_ssm_document_version() {{
                      printf '1\\n'
                    }}
                    junca_fixed_ssm_validate_document() {{
                      return 0
                    }}
                    junca_fixed_ssm_send_command() {{
                      if [[ "$1" == JuncaPTFinalityInspect ]]; then
                        printf '%s\\n' preflight >> preflight-submissions
                        printf 'preflight-command-id\\n'
                        return 0
                      fi
                      if [[ "$1" == JuncaPTFinalitySet ]]; then
                        printf '%s\\n' mutation >> mutation-submissions
                        printf 'mutation-command-id\\n'
                        return 0
                      fi
                      return 1
                    }}
                    wait_for_ssm_command() {{
                      return 1
                    }}
                    wait_for_ssm_command_result() {{
                      return 0
                    }}
                    mkdir artifacts
                    bindings='{json.dumps(bindings, separators=(",", ":"))}'
                    if set_runtime_finality 0 0 "$bindings"; then
                      exit 91
                    fi
                    test "$(wc -l < preflight-submissions)" = 1
                    test ! -e mutation-submissions
                    """
                )
            )
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_compensation_uses_fixed_exact_false_zero_zero(self) -> None:
        block = self.foundation_script.split(
            "# Best-effort compensation always returns every reachable node", 1
        )[1].split("\n    compensation_summary='[]'", 1)[0]
        for required in (
            "JuncaPTFinalitySet",
            "JuncaPTFinalityInspect",
            'Enabled: "false"',
            'BlockIntervalSeconds: "0"',
            'SlotEpochSeconds: "0"',
            'Mode: "exact"',
            'AllowMissingFinalityKeys: "false"',
        ):
            self.assertIn(required, block)

    def test_finality_activation_is_separate_and_manual_vote_is_disabled(self) -> None:
        disable_index = self.foundation_script.index(
            '0 0 "$pre_rollout_finality_bindings"'
        )
        replacement_index = self.foundation_script.index(
            'for address in "${validator_replacements[@]}"'
        )
        dispatch_index = self.foundation_script.index(
            'activation_dispatch_epoch="$((validator_slot_epoch_seconds - 60))"'
        )
        enable_index = self.foundation_script.index(
            '30 "$validator_slot_epoch_seconds" "$activated_finality_bindings"'
        )
        self.assertLess(disable_index, replacement_index)
        self.assertLess(replacement_index, dispatch_index)
        self.assertLess(dispatch_index, enable_index)
        self.assertNotIn(
            "set_runtime_finality \\\n"
            '      0 "$validator_slot_epoch_seconds" '
            '"$activated_finality_bindings"',
            self.foundation_script,
        )
        self.assertNotIn("junca_broadcastVote", self.validator_foundation_release)
        self.assertNotIn("ssm-broadcast", self.validator_foundation_release)

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

    def test_post_apply_failures_are_checkpointed_and_ssm_errors_retry(self) -> None:
        for required in (
            "wait_for_ssm_online()",
            "junca-validator-ssm-online-readback/v1",
            "attempts: .",
            "accepted: false",
            "post-apply-validator-${index}-checkpoint.json",
            "terraform-apply started",
            "instance-output started",
            "root-volume started",
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

    def test_ssm_command_retries_only_allowlisted_transient_errors(self) -> None:
        function = ssm_command_functions(self.foundation_script)
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            counter = temp / "counter"
            output = temp / "invocation.json"
            harness = textwrap.dedent(
                """
                aws() {
                  count=0
                  if [[ -f "$COUNTER_PATH" ]]; then
                    count="$(cat "$COUNTER_PATH")"
                  fi
                  count="$((count + 1))"
                  printf '%s' "$count" >"$COUNTER_PATH"
                  if [[ "$MODE" == transient && "$count" == 1 ]]; then
                    echo "InvocationDoesNotExist" >&2
                    return 254
                  fi
                  if [[ "$MODE" == unknown ]]; then
                    echo "AccessDeniedException" >&2
                    return 254
                  fi
                  if [[ " $* " == *" --query Status "* ]]; then
                    printf 'Success\\n'
                  else
                    printf '{"Status":"Success"}\\n'
                  fi
                }
                sleep() { :; }
                junca_fixed_ssm_validate_invocation_readback() { return 0; }
                wait_for_ssm_command "$1" "$2" "$3" "$4" "$5"
                """
            )
            environment = {
                "PATH": "/usr/bin:/bin",
                "COUNTER_PATH": str(counter),
                "MODE": "transient",
            }
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n" + function + harness,
                    "ssm-command-test",
                    "command-1",
                    "i-00000000000000001",
                    str(output),
                    "JuncaPTHealthReadback",
                    "1",
                ],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["Status"], "Success")
            self.assertEqual(counter.read_text(), "3")

            counter.unlink()
            environment["MODE"] = "unknown"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n" + function + harness,
                    "ssm-command-test",
                    "command-1",
                    "i-00000000000000001",
                    str(output),
                    "JuncaPTHealthReadback",
                    "1",
                ],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(counter.read_text(), "1")

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

    def test_public_release_auto_source_is_only_successful_candidate_foundation(self) -> None:
        trigger = self.public_testnet_release.split(
            "permissions:", 1
        )[0]
        self.assertIn(
            '- "JUNCA Validator Foundation Release"',
            trigger,
        )
        self.assertNotIn("JUNCA Public Testnet IAM Recovery", trigger)
        for required in (
            'test "$WORKFLOW_RUN_CONCLUSION" = "success"',
            'test "$WORKFLOW_RUN_NAME" = \\\n'
            '                "JUNCA Validator Foundation Release"',
            'test "$WORKFLOW_RUN_HEAD_BRANCH" = "main"',
            'test "$WORKFLOW_RUN_HEAD_SHA" = "$GITHUB_SHA"',
            'test "$WORKFLOW_RUN_HEAD_REPOSITORY" = "$REPOSITORY"',
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

    def test_foundation_reads_but_cannot_mutate_validator_iam_roles(self) -> None:
        policy = self.iam_separation.split(
            'resource "aws_iam_policy" "deployment_validator_pass"', 1
        )[1].split(
            'resource "aws_iam_role_policy_attachment" '
            '"deployment_validator_pass"',
            1,
        )[0]
        for action in (
            "iam:GetRole",
            "iam:ListAttachedRolePolicies",
            "iam:ListInstanceProfilesForRole",
            "iam:ListRolePolicies",
        ):
            self.assertIn(action, policy)
        self.assertIn("DenyPassRoleUntilAttestedLaunchContract", policy)
        self.assertNotIn("iam:UpdateAssumeRolePolicy", policy)

    def test_managed_acm_and_sns_are_not_external_foundation_inputs(self) -> None:
        for deprecated_input in (
            "CERTIFICATE_ARN",
            "ALERT_TOPIC_ARN",
            "JUNCA_PUBLIC_TESTNET_CERTIFICATE_ARN",
            "JUNCA_PUBLIC_TESTNET_ALERT_TOPIC_ARN",
        ):
            self.assertNotIn(deprecated_input, self.foundation_script)
            self.assertNotIn(
                deprecated_input,
                self.validator_foundation_release,
            )
        for required_input in (
            "NODE_AMI_ID",
            "NODE_ARTIFACT_SHA256",
            "GENESIS_SHA256",
            "SOURCE_COMMIT",
            "AVAILABILITY_ZONES_JSON",
        ):
            self.assertIn(required_input, self.foundation_script)
            self.assertIn(required_input, self.validator_foundation_release)

    def test_canonical_foundation_release_binds_immutable_inputs(self) -> None:
        for required in (
            "Verified immutable AMI workflow run ID",
            "Successful JUNCA Runtime Release Manifest Gate run ID",
            "release-candidate/${GITHUB_SHA}",
            "Attest exact live GitHub OIDC claims",
            "PUBLIC_TESTNET_ROLLOUT",
            "scripts/junca_public_testnet_foundation.sh foundation-apply",
        ):
            self.assertIn(required, self.validator_foundation_release)

    def test_bootstrap_state_contract_remains_durable(self) -> None:
        self.assertIn('backend "s3" {}', self.bootstrap)
        self.assertIn(
            "JuncaChainPublicTestnetDeployment",
            self.iam_separation,
        )

    def test_canonical_foundation_release_preserves_non_monetary_boundary(self) -> None:
        for required in (
            "Public Testnet / No Monetary Value",
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "595710543956",
            "us-east-1",
            "JuncaChainPublicTestnetDeployment",
        ):
            self.assertIn(required, self.validator_foundation_release)

    def test_canonical_foundation_release_requires_manual_dispatch(self) -> None:
        for required in (
            "workflow_dispatch:",
            "authorize_rollout:",
            "ami_run_id:",
            "manifest_gate_run_id:",
        ):
            self.assertIn(required, self.validator_foundation_release)
        self.assertNotIn(
            "\n  workflow_run:",
            self.validator_foundation_release,
        )
        self.assertNotIn("\n  push:", self.validator_foundation_release)

    def test_oidc_self_permission_recovery_entry_point_is_retired(self) -> None:
        self.assertFalse(self.self_permission_recovery_path.exists())
        policy = json.loads(
            (
                ROOT / "config/junca_public_testnet_cloud_role_policy.json"
            ).read_text(encoding="utf-8")
        )
        retired = {
            item["workflow"]: item
            for item in policy["blocked_raw_oidc_workflows"]
        }
        entry = retired[self.self_permission_recovery_path.name]
        self.assertEqual(entry["disposition"], "DELETE_WORKFLOW_FILE")
        self.assertIn("must not repair its own IAM", entry["retired_reason"])

    def test_manual_apply_requires_provenance_and_oidc_attestation(self) -> None:
        for required in (
            'test "$AUTHORIZE_ROLLOUT" = "PUBLIC_TESTNET_ROLLOUT"',
            "release-candidate/${GITHUB_SHA}",
            "scripts/junca_oidc_claim_attestation.py",
            "scripts/junca_public_testnet_foundation.sh foundation-apply",
        ):
            self.assertIn(required, self.validator_foundation_release)

    def test_runtime_role_can_simulate_only_its_own_policy(self) -> None:
        for required in (
            'resource "aws_iam_role_policy" "deployment_self_permission_readback"',
            'name = "SelfPermissionReadback"',
            'Action   = "iam:SimulatePrincipalPolicy"',
            "Resource = aws_iam_role.deployment.arn",
        ):
            self.assertIn(required, self.iam_separation)

    def test_ceo_iam_authorization_is_exact_but_cannot_trigger_raw_oidc(self) -> None:
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
        self.assertFalse(self.self_permission_recovery_path.exists())

    def test_raw_oidc_and_direct_web_identity_sts_are_absent(self) -> None:
        retired = (
            "junca-chain-bootstrap-inline-policy-repair.yml",
            "junca-chain-runtime-self-permission-recovery.yml",
            "junca-point-member-production-recovery.yml",
        )
        for workflow in retired:
            self.assertFalse((ROOT / ".github/workflows" / workflow).exists())
        for workflow_path in (ROOT / ".github/workflows").glob("*.y*ml"):
            text = workflow_path.read_text(encoding="utf-8")
            self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", text)
            self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST_URL", text)
            self.assertNotIn("assume-role-with-web-identity", text)


if __name__ == "__main__":
    unittest.main()
