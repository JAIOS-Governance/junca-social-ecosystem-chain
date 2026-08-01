from pathlib import Path
import importlib.util
import json
import unittest

from jaios.social_ecosystem_chain.rolling_compatibility import (
    RECOVERY_FILE_ALLOWLIST,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-validator-ami-build.yml"
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
RUNTIME_RECOVERY = ROOT / ".github/workflows/junca-validator-runtime-recovery.yml"
ORCHESTRATOR = (
    ROOT / ".github/workflows/junca-validator-public-testnet-orchestrator.yml"
)
FOUNDATION = ROOT / ".github/workflows/junca-validator-foundation-release.yml"
REQUEST = ROOT / "tests/fixtures/junca_validator_ami_build_request.json"
LIVE_REQUEST = ROOT / "config/junca_validator_ami_build_request.json"
REQUEST_VALIDATOR_PATH = ROOT / "scripts/junca_validator_ami_build_request.py"
SPEC = importlib.util.spec_from_file_location(
    "junca_validator_ami_build_request",
    REQUEST_VALIDATOR_PATH,
)
assert SPEC is not None and SPEC.loader is not None
REQUEST_VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REQUEST_VALIDATOR)


class ValidatorAmiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.component = COMPONENT.read_text(encoding="utf-8")
        cls.runtime_recovery = RUNTIME_RECOVERY.read_text(encoding="utf-8")
        cls.orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
        cls.foundation = FOUNDATION.read_text(encoding="utf-8")
        cls.request = REQUEST.read_text(encoding="utf-8")
        cls.live_request = LIVE_REQUEST.read_text(encoding="utf-8")
        cls.live_request_data = json.loads(cls.live_request)

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
        self.assertIn("--require-migration-binding", self.orchestrator)

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
        self.assertIn(
            "steps.request.outputs.migration_run_id",
            self.orchestrator,
        )
        self.assertIn(
            "steps.request.outputs.migration_evidence_sha256",
            self.orchestrator,
        )
        self.assertIn(
            "inputs[migration_evidence_sha256]",
            self.orchestrator,
        )
        self.assertNotIn(
            "JUNCA Validator Durable State Migration",
            self.orchestrator,
        )
        self.assertNotIn(
            "inputs[authorize_migration]",
            self.orchestrator,
        )
        self.assertNotIn("terraform apply", self.orchestrator)
        self.assertNotIn("cloudformation", self.orchestrator.lower())

    def test_foundation_resume_is_one_shot_and_skips_rebuild_chain(self):
        self.assertIn(
            "junca-validator-foundation-resume-request/v1",
            self.orchestrator,
        )
        self.assertEqual(
            self.orchestrator.count(
                "if: steps.request.outputs.request_type == 'ami-build'"
            ),
            3,
        )
        self.assertIn('test "$GITHUB_RUN_ATTEMPT" = 1', self.orchestrator)
        self.assertIn(
            'git rev-list "${GITHUB_SHA}^" -- "$REQUEST_PATH"',
            self.orchestrator,
        )
        self.assertIn("(.files | length) == 5", self.orchestrator)
        self.assertIn(
            "foundation-resume-30311386951-20260727-retry-2",
            self.orchestrator,
        )
        self.assertIn(
            "9fa0cef6329eb55fa7c5180afab8e29df72dd84be4cca4711759e67e960129af",
            self.orchestrator,
        )
        self.assertIn(
            "inputs[resume_run_id]=${RESUME_RUN_ID}",
            self.orchestrator,
        )
        self.assertIn(
            "steps.request.outputs.ami_run_id",
            self.orchestrator,
        )
        self.assertIn(
            "steps.request.outputs.manifest_gate_run_id",
            self.orchestrator,
        )
        self.assertIn(
            "steps.request.outputs.resume_run_id",
            self.orchestrator,
        )
        self.assertIn("FOUNDATION_RESUME_REQUEST_CONSUMED", self.orchestrator)
        self.assertIn("rebuild_ami: false", self.orchestrator)
        self.assertIn("rebuild_manifest: false", self.orchestrator)
        self.assertIn("always()", self.orchestrator)
        self.assertIn("if-no-files-found: error", self.orchestrator)
        for path in (
            ".github/workflows/"
            "junca-validator-public-testnet-orchestrator.yml",
            "config/junca_validator_ami_build_request.json",
            "scripts/junca_validator_ami_build_request.py",
            "tests/test_junca_validator_ami_workflow.py",
        ):
            self.assertIn(path, RECOVERY_FILE_ALLOWLIST)
        for field in ("ami_run_id", "manifest_gate_run_id", "resume_run_id"):
            self.assertRegex(self.live_request_data[field], r"^[1-9][0-9]*$")
        self.assertEqual(
            self.live_request_data["approval_phrase"],
            "PUBLIC_TESTNET_ROLLOUT",
        )
        self.assertEqual(
            self.live_request_data["request_sha256"],
            REQUEST_VALIDATOR.canonical_request_sha256(
                self.live_request_data
            ),
        )
        self.assertRegex(
            self.live_request_data["one_shot_nonce"],
            rf"^foundation-resume-{self.live_request_data['resume_run_id']}"
            r"-[0-9]{8}(?:-[a-z0-9-]+)?$",
        )

    def test_exact_v24_finality_resume_bypasses_only_the_stale_monitor(self):
        self.assertIn("cancel-in-progress: true", self.orchestrator)
        self.assertIn(
            "junca-public-testnet-finality-next-slot-v24",
            self.foundation,
        )
        for exact_binding in (
            "inputs.ami_run_id == '30682660387'",
            "inputs.manifest_gate_run_id == '30683678492'",
            "inputs.resume_run_id == '30688476089'",
            "inputs.renew_expired_epoch == 'NONE'",
            "inputs.renewal_preserve_prefix_count == '0'",
        ):
            self.assertIn(exact_binding, self.foundation)
        self.assertIn(
            "'junca-public-testnet-aws-foundation'",
            self.foundation,
        )
        self.assertIn("cancel-in-progress: false", self.foundation)
        concurrency = self.foundation.split("concurrency:", 1)[1].split(
            "\njobs:", 1
        )[0]
        self.assertNotIn("inputs.resume_run_id !=", concurrency)
        self.assertNotIn("startsWith(inputs.resume_run_id", concurrency)

    def test_exact_foundation_resume_request_is_digest_bound(self):
        request = {
            "schema_version": (
                "junca-validator-foundation-resume-request/v1"
            ),
            "state": "AUTHORIZED",
            "network": "Public Testnet",
            "environment": "public-testnet",
            "mode": "foundation-resume-only",
            "approval_phrase": "PUBLIC_TESTNET_ROLLOUT",
            "ami_run_id": "30311265807",
            "manifest_gate_run_id": "30311368029",
            "resume_run_id": "30311386951",
            "target_workflow": (
                ".github/workflows/junca-validator-foundation-release.yml"
            ),
            "one_shot_nonce": "foundation-resume-30311386951-20260727",
            "renew_expired_epoch": "NONE",
            "renewal_preserve_prefix_count": "0",
            "boundaries": {
                "rebuild_ami": False,
                "rebuild_manifest": False,
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            },
            "request_sha256": "",
        }
        request["request_sha256"] = (
            REQUEST_VALIDATOR.canonical_request_sha256(request)
        )
        outputs = REQUEST_VALIDATOR.validate_request(
            request,
            require_migration_binding=True,
        )
        self.assertEqual(outputs["request_type"], "foundation-resume")
        self.assertEqual(outputs["ami_run_id"], "30311265807")
        self.assertEqual(outputs["manifest_gate_run_id"], "30311368029")
        self.assertEqual(outputs["resume_run_id"], "30311386951")
        self.assertEqual(outputs["renew_expired_epoch"], "NONE")
        self.assertEqual(outputs["renewal_preserve_prefix_count"], "0")

        renewed = dict(request)
        renewed["renew_expired_epoch"] = "RENEW_EXPIRED_QUIESCED_EPOCH"
        renewed["renewal_preserve_prefix_count"] = "2"
        renewed["request_sha256"] = (
            REQUEST_VALIDATOR.canonical_request_sha256(renewed)
        )
        renewed_outputs = REQUEST_VALIDATOR.validate_request(renewed)
        self.assertEqual(
            renewed_outputs["renew_expired_epoch"],
            "RENEW_EXPIRED_QUIESCED_EPOCH",
        )
        self.assertEqual(
            renewed_outputs["renewal_preserve_prefix_count"], "2"
        )

        for field, value in (
            ("ami_run_id", "0"),
            ("manifest_gate_run_id", "invalid"),
            ("resume_run_id", "0"),
            ("approval_phrase", "PUBLIC_TESTNET_RUNTIME_RECOVERY"),
            ("mode", "ami-build"),
            ("renew_expired_epoch", "RENEW_ANY_EPOCH"),
            ("renewal_preserve_prefix_count", "4"),
        ):
            with self.subTest(field=field):
                invalid = dict(request)
                invalid[field] = value
                with self.assertRaises(
                    REQUEST_VALIDATOR.RequestValidationError
                ):
                    REQUEST_VALIDATOR.validate_request(invalid)

        invalid = dict(request)
        invalid["unexpected"] = True
        with self.assertRaises(REQUEST_VALIDATOR.RequestValidationError):
            REQUEST_VALIDATOR.validate_request(invalid)

        for renewal, prefix in (
            ("NONE", "1"),
            ("RENEW_EXPIRED_QUIESCED_EPOCH", "0"),
        ):
            invalid = dict(request)
            invalid["renew_expired_epoch"] = renewal
            invalid["renewal_preserve_prefix_count"] = prefix
            invalid["request_sha256"] = (
                REQUEST_VALIDATOR.canonical_request_sha256(invalid)
            )
            with self.assertRaises(
                REQUEST_VALIDATOR.RequestValidationError
            ):
                REQUEST_VALIDATOR.validate_request(invalid)

        invalid = dict(request)
        invalid.pop("renewal_preserve_prefix_count")
        invalid["request_sha256"] = (
            REQUEST_VALIDATOR.canonical_request_sha256(invalid)
        )
        with self.assertRaises(REQUEST_VALIDATOR.RequestValidationError):
            REQUEST_VALIDATOR.validate_request(invalid)

        invalid = dict(request)
        invalid["boundaries"] = dict(request["boundaries"])
        invalid["boundaries"]["rebuild_ami"] = True
        invalid["request_sha256"] = (
            REQUEST_VALIDATOR.canonical_request_sha256(invalid)
        )
        with self.assertRaises(REQUEST_VALIDATOR.RequestValidationError):
            REQUEST_VALIDATOR.validate_request(invalid)

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
        self.assertIn(
            "install -d -o root -g junca -m 0750 /etc/junca",
            self.component,
        )
        self.assertIn(
            "install -o root -g junca -m 0640 "
            "/tmp/genesis.json /etc/junca/genesis.json",
            self.component,
        )
        self.assertIn(
            "install -o root -g junca -m 0640 "
            "/dev/null /etc/junca/validator.toml",
            self.component,
        )
        self.assertNotIn(
            "chown root:junca /etc/junca/validator.toml",
            self.component,
        )
        self.assertIn(
            "runuser -u junca -- test -r /etc/junca/genesis.json",
            self.component,
        )
        self.assertIn(
            "runuser -u junca -- test -r /etc/junca/validator.toml",
            self.component,
        )


if __name__ == "__main__":
    unittest.main()
