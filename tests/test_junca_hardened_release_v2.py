from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / ".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"
BASELINE = ROOT / ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"
MANIFEST = ROOT / ".github/workflows/junca-runtime-release-manifest-gate.yml"
RUNTIME = ROOT / ".github/workflows/junca-validator-runtime-artifacts.yml"
AMI = ROOT / ".github/workflows/junca-validator-ami-build.yml"
BINDING = ROOT / "scripts/junca_release_child_run_binding.py"
PROVENANCE = ROOT / "scripts/junca_release_child_provenance.py"


class HardenedReleaseV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parent = PARENT.read_text(encoding="utf-8")
        cls.baseline = BASELINE.read_text(encoding="utf-8")
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.ami = AMI.read_text(encoding="utf-8")
        cls.binding = BINDING.read_text(encoding="utf-8")
        cls.provenance = PROVENANCE.read_text(encoding="utf-8")

    def test_parent_is_exact_source_and_candidate_ready(self) -> None:
        for value in (
            "JUNCA Validator Runtime Artifacts",
            "workflow_dispatch:",
            "source_run_id:",
            "parent_ami_id:",
            "python3_boto3_nevra:",
            "PUBLIC_TESTNET_IMMUTABLE_CANDIDATE",
            '.event == "push"',
            '.head_branch == "main"',
            ".head_repository.full_name == $repository",
            "ref: ${{ inputs.source_commit }}",
            '"junca-validator-ami-build-request/v2"',
            "release-candidate/$SOURCE_COMMIT",
            "junca_dispatch_workflow_and_wait.py",
            ".github/workflows/junca-validator-ami-build.yml",
            ".github/workflows/junca-runtime-release-evidence-collector-v2.yml",
            ".github/workflows/junca-runtime-release-manifest-gate.yml",
            "PUBLIC_TESTNET_CANDIDATE_READY_FOR_SERIAL_ROLLOUT",
            "serial_rollout_dispatched: false",
            "continuity_dispatched: false",
        ):
            self.assertIn(value, self.parent)
        self.assertNotIn("workflow_run:", self.parent)
        self.assertNotIn("ami-amazon-linux-latest", self.parent)
        self.assertNotIn("resume_run_id=0", self.parent)
        self.assertNotIn("JUNCA Validator Foundation Release", self.parent)

    def test_parent_preserves_activation_boundaries(self) -> None:
        for value in (
            "transaction_submission_enabled: false",
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
            "mainnet_activation_authorized: false",
        ):
            self.assertIn(value, self.parent)
        self.assertNotIn("terraform apply", self.parent)
        self.assertNotIn("eth_send", self.parent)
        self.assertNotIn("junca_broadcast", self.parent)

    def test_parent_binds_each_exact_child_before_waiting(self) -> None:
        self.assertEqual(self.parent.count("--operation dispatch"), 3)
        self.assertEqual(self.parent.count("--operation wait"), 3)
        self.assertEqual(
            self.parent.count(
                "python3 scripts/junca_release_child_run_binding.py"
            ),
            3,
        )
        sequences = (
            (
                "Dispatch exact-request immutable AMI child",
                "Bind exact immutable AMI child run",
                "Publish exact immutable AMI child run binding",
                "Wait for bound exact-request immutable AMI",
            ),
            (
                "Dispatch V2 pre-rollout baseline child",
                "Bind exact V2 pre-rollout baseline child run",
                "Publish exact V2 pre-rollout baseline child run binding",
                "Wait for bound V2 pre-rollout baseline evidence",
            ),
            (
                "Dispatch release manifest gate child",
                "Bind exact release manifest gate child run",
                "Publish exact release manifest gate child run binding",
                "Wait for bound release manifest gate",
            ),
        )
        for sequence in sequences:
            with self.subTest(child=sequence[0]):
                positions = [
                    self.parent.index(f"- name: {name}")
                    for name in sequence
                ]
                self.assertEqual(positions, sorted(positions))
        self.assertIn(
            'RUN_BINDING_SCHEMA = "junca-release-child-run-binding/v1"',
            self.provenance,
        )
        self.assertIn('"binding_sha256"', self.provenance)
        self.assertIn("--child-run-id", self.binding)
        self.assertIn("--child-run-attempt", self.binding)

    def test_children_reject_unbound_runs_before_aws_or_output(self) -> None:
        for workflow, gate, boundary in (
            (
                self.ami,
                "Verify exact child run binding before AMI side effects",
                "aws-actions/configure-aws-credentials",
            ),
            (
                self.baseline,
                "Verify exact child run binding before AWS readback",
                "aws-actions/configure-aws-credentials",
            ),
            (
                self.manifest,
                "Verify exact child run binding before manifest output",
                "actions/upload-artifact",
            ),
        ):
            with self.subTest(gate=gate):
                self.assertIn(gate, workflow)
                self.assertLess(
                    workflow.index(
                        "python3 scripts/junca_release_child_provenance.py"
                    ),
                    workflow.index(boundary),
                )
        for value in (
            'github_run_attempt != "1"',
            "github_run_id=github_run_id",
            "github_workflow_ref=github_workflow_ref",
            "exact child run binding rejected before side effects",
            "exact child run binding was not published within the bounded poll",
        ):
            self.assertIn(value, self.provenance)

    def test_v2_baseline_is_read_only_and_drift_explicit(self) -> None:
        for value in (
            "environment: public-testnet",
            "junca_runtime_release_evidence_collector_drift.py",
            "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE",
            "candidate_ami_preexisting == false",
            "terraform -chdir=infra/aws/bootstrap output -json",
            "terraform -chdir=infra/aws/public-testnet output -json",
            "junca-runtime-release-evidence-${{ github.run_id }}",
        ):
            self.assertIn(value, self.baseline)
        for forbidden in (
            "terraform apply",
            "terraform plan",
            "terraform import",
            "terraform state ",
            "aws ec2 create-",
            "aws ec2 modify-",
            "aws ec2 attach-",
            "aws ec2 detach-",
            "aws route53 change-",
            "eth_send",
        ):
            self.assertNotIn(forbidden, self.baseline)

    def test_manifest_accepts_only_exact_v2_collector(self) -> None:
        self.assertIn(
            '.path == ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            self.manifest,
        )
        self.assertIn('.name == "JUNCA Runtime Release Evidence Collector"', self.manifest)
        self.assertIn('.conclusion == "success"', self.manifest)
        self.assertIn(".head_sha == $source_commit", self.manifest)
        self.assertIn(".head_branch == $execution_ref", self.manifest)
        self.assertNotIn(
            ".github/workflows/junca-runtime-release-evidence-collector.yml",
            self.manifest,
        )

    def test_runtime_artifact_rebinds_v2_release_changes(self) -> None:
        push_block = self.runtime.split("push:", 1)[1].split(
            "pull_request:", 1
        )[0]
        self.assertIn("branches: [main]", push_block)
        self.assertNotIn("paths:", push_block)
        pull_request_block = self.runtime.split("pull_request:", 1)[1].split(
            "workflow_dispatch:", 1
        )[0]
        for path in (
            '"scripts/junca_runtime_release_evidence_collector_drift.py"',
            '"scripts/junca_dispatch_workflow_and_wait.py"',
            '"scripts/junca_release_child_provenance.py"',
            '"scripts/junca_release_dispatch_attestation.py"',
            '"scripts/junca_validator_ami_build_request.py"',
            '"tests/test_junca_runtime_release_ami_drift.py"',
            '"tests/test_junca_release_orchestration.py"',
            '"tests/test_junca_hardened_release_v2.py"',
            '"tests/test_junca_validator_ami_build_request.py"',
            '"config/junca_validator_ami_supply_chain_lock.json"',
            '".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"',
            '".github/workflows/junca-runtime-release-manifest-gate.yml"',
        ):
            self.assertEqual(pull_request_block.count(path), 1)
        self.assertIn(
            "scripts/junca_release_dispatch_attestation.py",
            self.runtime.split("python3 -m py_compile", 1)[1],
        )
        self.assertIn("tests.test_junca_hardened_release_v2", self.runtime)
        self.assertIn("tests.test_junca_runtime_release_ami_drift", self.runtime)
        self.assertIn(
            "tests.test_junca_validator_ami_build_request",
            self.runtime,
        )

    def test_runtime_artifact_validates_fixed_ssm_with_and_without_pyyaml(
        self,
    ) -> None:
        pull_request_block = self.runtime.split("pull_request:", 1)[1].split(
            "workflow_dispatch:", 1
        )[0]
        for path in (
            '"infrastructure/aws/ssm-documents/**"',
            '"scripts/junca_fixed_ssm_document_contract.py"',
            '"tests/test_junca_fixed_ssm_document_contract.py"',
            '"docs/runbooks/junca-public-testnet-fixed-ssm-launch-design.md"',
        ):
            self.assertEqual(pull_request_block.count(path), 1)
        self.assertIn(
            "tests.test_junca_fixed_ssm_document_contract",
            self.runtime,
        )
        compile_block = self.runtime.split("python3 -m py_compile", 1)[1]
        self.assertIn(
            "scripts/junca_fixed_ssm_document_contract.py",
            compile_block,
        )
        self.assertIn(
            "python3 scripts/junca_fixed_ssm_document_contract.py",
            self.runtime,
        )
        self.assertIn(
            "python3 -S scripts/junca_fixed_ssm_document_contract.py",
            self.runtime,
        )
        self.assertIn(
            '$RUNNER_TEMP/junca-fixed-ssm-contract-stdlib.json',
            self.runtime,
        )
        self.assertNotIn("pip install PyYAML", self.runtime)


if __name__ == "__main__":
    unittest.main()
