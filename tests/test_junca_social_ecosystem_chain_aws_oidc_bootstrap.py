from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
POLICY_PATH = ROOT / "config/junca_public_testnet_cloud_role_policy.json"
TOMBSTONE_PATH = (
    ROOT / "infrastructure/aws/public-testnet-oidc-trust-handoff.json"
)
RETIRED_TEMPLATES = (
    ROOT / "infrastructure/aws/bootstrap/github-oidc.yaml",
    ROOT / "infrastructure/aws/bootstrap/public-testnet-inventory-role.yaml",
)
LEGACY_SUBJECT = (
    "repo:JAIOS-Governance@308604370/"
    "junca-social-ecosystem-chain@1310568313:"
    "environment:public-testnet"
)


class AwsOidcBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        cls.tombstone = json.loads(
            TOMBSTONE_PATH.read_text(encoding="utf-8")
        )

    def test_legacy_cloudformation_bootstrap_entry_points_are_absent(self) -> None:
        for template in RETIRED_TEMPLATES:
            self.assertFalse(template.exists(), template)

    def test_handoff_is_a_non_executable_tombstone(self) -> None:
        self.assertEqual(
            self.tombstone["schema_version"],
            "junca-public-testnet-oidc-trust-handoff-retired/v2",
        )
        self.assertEqual(self.tombstone["state"], "RETIRED_NON_EXECUTABLE")
        self.assertFalse(self.tombstone["executable"])
        self.assertEqual(
            self.tombstone["prohibited_legacy_subject"],
            LEGACY_SUBJECT,
        )
        for field in self.tombstone["execution_fields_intentionally_absent"]:
            self.assertNotIn(field, self.tombstone)
        self.assertFalse(self.tombstone["deployment_performed"])

    def test_tombstone_points_only_to_current_fail_closed_contracts(self) -> None:
        replacements = self.tombstone["replacement_contracts"]
        for relative_path in replacements.values():
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)
        self.assertEqual(
            self.tombstone["runtime_recovery_state"],
            "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        )

    def test_current_subject_contract_is_workflow_and_runner_exact(self) -> None:
        self.assertEqual(
            self.policy["oidc_subject_claim_keys"],
            ["repo", "context", "workflow_ref", "runner_environment"],
        )
        self.assertEqual(
            self.policy["prohibited_legacy_subject"],
            LEGACY_SUBJECT,
        )
        for role in ("foundation", "ami_builder", "observer"):
            subjects = self.policy["roles"][role]["exact_subject_allowlist"]
            self.assertTrue(subjects)
            for subject in subjects:
                self.assertIn(":workflow_ref:", subject)
                self.assertTrue(
                    subject.endswith(":runner_environment:github-hosted")
                )
                self.assertNotEqual(subject, LEGACY_SUBJECT)

    def test_security_bootstrap_has_no_github_oidc_subject(self) -> None:
        security = self.policy["roles"]["security_bootstrap"]
        self.assertFalse(security["oidc_enabled"])
        self.assertEqual(security["exact_workflow_allowlist"], [])
        self.assertEqual(security["exact_subject_allowlist"], [])
        self.assertEqual(
            security["prohibited_principals"],
            ["token.actions.githubusercontent.com"],
        )

    def test_canonical_readbacks_attest_before_aws_identity(self) -> None:
        for workflow_name in (
            "junca-social-ecosystem-chain-aws-binding-readback.yml",
            "junca-social-ecosystem-chain-aws-readback.yml",
        ):
            document = yaml.safe_load(
                (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
            )
            credential_locations = []
            for job_name, job in document["jobs"].items():
                steps = job.get("steps") or []
                for index, step in enumerate(steps):
                    if "configure-aws-credentials@" not in str(
                        step.get("uses", "")
                    ):
                        continue
                    credential_locations.append((job_name, steps, index))
            self.assertEqual(len(credential_locations), 1, workflow_name)
            job_name, steps, index = credential_locations[0]
            self.assertGreater(index, 0)
            attestation = steps[index - 1]
            self.assertEqual(
                attestation["name"],
                "Attest exact live GitHub OIDC claims",
            )
            self.assertIn(
                "python3 scripts/junca_oidc_claim_attestation.py",
                attestation["run"],
            )
            self.assertIn("--role-arn", attestation["run"])
            self.assertEqual(
                document["jobs"][job_name]["environment"],
                "public-testnet",
            )

    def test_repository_global_cutover_is_currently_blocked(self) -> None:
        gate = self.policy["repo_global_oidc_cutover_gate"]
        self.assertNotEqual(
            gate["preparation_state"],
            gate["prepared_state"],
        )
        self.assertNotEqual(
            gate["activation_state"],
            gate["ready_state"],
        )
        self.assertEqual(gate["baseline_credential_call_count"], 27)
        self.assertEqual(gate["active_credential_call_count"], 7)
        self.assertEqual(gate["blocked_pending_migration_call_count"], 0)
        self.assertEqual(gate["retired_call_count"], 20)

    def test_public_testnet_constitutional_boundary_is_preserved(self) -> None:
        for document in (self.policy, self.tombstone):
            boundary = document.get("release_boundary", document)
            self.assertFalse(boundary["mainnet_changed"])
            self.assertFalse(boundary["assets_moved"])
            self.assertFalse(boundary["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
