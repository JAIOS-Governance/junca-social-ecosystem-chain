from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.junca_public_testnet_cloud_role_policy import (
    BLOCKED_CREDENTIAL_DISPOSITION,
    CANONICAL_ROLE_MAPPING,
    CANONICAL_CREDENTIAL_DISPOSITION,
    CUTOVER_READY_STATE,
    CloudRolePolicyError,
    LEGACY_SUBJECT,
    MIGRATED_CREDENTIAL_DISPOSITION,
    OIDC_TEMPLATE_MUTATOR_WORKFLOWS,
    QUARANTINE_WORKFLOWS,
    RAW_OIDC_QUARANTINE_WORKFLOWS,
    REPO_GLOBAL_OIDC_CUTOVER_STATE,
    REPO_GLOBAL_OIDC_PREPARATION_STATE,
    REPO_GLOBAL_OIDC_PREPARED_STATE,
    ROLE_NAMES,
    ROLE_WORKFLOWS,
    WORKFLOW_ROLE_EXPECTATIONS,
    collect_repository_credential_calls,
    exact_subject,
    load_policy,
    require_repo_global_oidc_cutover_ready,
    validate_policy,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/junca_public_testnet_cloud_role_policy.json"
WORKFLOWS_DIR = ROOT / ".github/workflows"


class PublicTestnetCloudRolePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(POLICY_PATH)

    def test_repository_policy_and_deleted_quarantine_verify(self) -> None:
        validate_policy(self.policy, WORKFLOWS_DIR)

    def test_quarantine_set_is_exact_absent_and_auditable(self) -> None:
        self.assertEqual(self.policy["quarantine_mode"], "DELETE_WORKFLOW_FILE")
        entries = {
            item["workflow"]: item
            for item in self.policy["quarantine"]
        }
        self.assertEqual(set(entries), QUARANTINE_WORKFLOWS)
        self.assertEqual(len(entries), 22)
        for workflow, entry in entries.items():
            self.assertFalse((WORKFLOWS_DIR / workflow).exists())
            self.assertTrue(entry["original_name"].startswith("JUNCA "))
            self.assertTrue(entry["retired_reason"].strip())

    def test_oidc_template_mutator_workflows_are_deleted_and_auditable(self) -> None:
        entries = {
            item["workflow"]: item
            for item in self.policy["blocked_oidc_template_mutators"]
        }
        self.assertEqual(set(entries), OIDC_TEMPLATE_MUTATOR_WORKFLOWS)
        self.assertEqual(len(entries), 8)
        for workflow, entry in entries.items():
            self.assertFalse((WORKFLOWS_DIR / workflow).exists())
            self.assertTrue(entry["original_name"].startswith("JUNCA "))
            self.assertTrue(entry["retired_reason"].strip())
            self.assertEqual(entry["disposition"], "DELETE_WORKFLOW_FILE")

    def test_no_workflow_can_mutate_repository_oidc_template(self) -> None:
        forbidden = (
            "actions/oidc/customization/sub",
            "include_claim_keys",
            "use_immutable_subject",
            "use_default",
        )
        for workflow in WORKFLOWS_DIR.glob("*.y*ml"):
            text = workflow.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, workflow.name)

    def test_exact_workflow_and_subject_allowlists(self) -> None:
        roles = self.policy["roles"]
        for role_key, expected_workflows in ROLE_WORKFLOWS.items():
            role = roles[role_key]
            self.assertEqual(role["role_name"], ROLE_NAMES[role_key])
            self.assertEqual(
                set(role["exact_workflow_allowlist"]),
                expected_workflows,
            )
            self.assertEqual(
                set(role["exact_subject_allowlist"]),
                {exact_subject(workflow) for workflow in expected_workflows},
            )
            self.assertNotIn(LEGACY_SUBJECT, role["exact_subject_allowlist"])
            for subject in role["exact_subject_allowlist"]:
                self.assertIn(":workflow_ref:", subject)
                self.assertNotIn(":job_workflow_ref:", subject)
                self.assertTrue(
                    subject.startswith(
                        "repo:JAIOS-Governance@308604370/"
                        "junca-social-ecosystem-chain@1310568313:"
                    )
                )
                self.assertTrue(
                    subject.endswith(":runner_environment:github-hosted")
                )

    def test_direct_workflow_subject_claim_contract_is_exact(self) -> None:
        self.assertIs(self.policy["oidc_use_immutable_subject"], True)
        self.assertEqual(
            self.policy["oidc_subject_claim_keys"],
            ["repo", "context", "workflow_ref", "runner_environment"],
        )
        self.assertTrue(
            self.policy["subject_template"].startswith(
                "repo:JAIOS-Governance@308604370/"
                "junca-social-ecosystem-chain@1310568313:"
            )
        )
        self.assertIn(":workflow_ref:", self.policy["subject_template"])
        self.assertTrue(
            self.policy["subject_template"].endswith(
                ":runner_environment:github-hosted"
            )
        )
        self.assertNotIn("job_workflow_ref", json.dumps(self.policy))
        self.assertEqual(
            self.policy["external_oidc_readback_state"],
            "BLOCKED_PENDING_EXTERNAL_READBACK",
        )
        self.assertEqual(
            self.policy["runtime_recovery_execution_state"],
            "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        )

    def test_foundation_validator_host_and_shell_capabilities_stay_blocked(
        self,
    ) -> None:
        self.assertEqual(
            self.policy["roles"]["foundation"]["blocked_capabilities"],
            [
                "ec2:validator-host-replacement",
                "iam:PassRole:validator-instance-role",
                "ssm:validator-command-execution",
            ],
        )

    def test_public_release_is_foundation_because_it_applies_terraform(self) -> None:
        self.assertEqual(
            CANONICAL_ROLE_MAPPING["junca-public-testnet-release.yml"],
            "foundation",
        )
        self.assertIn(
            "junca-public-testnet-release.yml",
            ROLE_WORKFLOWS["foundation"],
        )
        self.assertNotIn(
            "junca-public-testnet-release.yml",
            ROLE_WORKFLOWS["observer"],
        )
        release_script = (
            ROOT / "scripts/junca_public_testnet_release.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "terraform -chdir=infra/aws/public-testnet apply",
            release_script,
        )

    def test_canonical_five_mapping_is_exact(self) -> None:
        self.assertEqual(
            self.policy["canonical_release_role_mapping"],
            CANONICAL_ROLE_MAPPING,
        )
        self.assertEqual(len(CANONICAL_ROLE_MAPPING), 5)
        self.assertEqual(len(WORKFLOW_ROLE_EXPECTATIONS), 7)

    def test_repository_credential_inventory_is_exhaustive_and_retired(
        self,
    ) -> None:
        gate = self.policy["repo_global_oidc_cutover_gate"]
        inventory = gate["active_credential_calls"]
        canonical = [
            item
            for item in inventory
            if item["disposition"] == CANONICAL_CREDENTIAL_DISPOSITION
        ]
        blocked = [
            item
            for item in inventory
            if item["disposition"] == BLOCKED_CREDENTIAL_DISPOSITION
        ]
        self.assertEqual(
            gate["preparation_state"],
            REPO_GLOBAL_OIDC_PREPARATION_STATE,
        )
        self.assertEqual(
            gate["prepared_state"],
            REPO_GLOBAL_OIDC_PREPARED_STATE,
        )
        self.assertEqual(
            gate["activation_state"],
            REPO_GLOBAL_OIDC_CUTOVER_STATE,
        )
        self.assertEqual(gate["ready_state"], CUTOVER_READY_STATE)
        self.assertEqual(gate["baseline_credential_call_count"], 27)
        self.assertEqual(gate["active_credential_call_count"], 7)
        self.assertEqual(gate["canonical_call_count"], 7)
        self.assertEqual(gate["migrated_exact_call_count"], 0)
        self.assertEqual(gate["blocked_pending_migration_call_count"], 0)
        self.assertEqual(gate["retired_call_count"], 20)
        self.assertEqual(len(canonical), 7)
        self.assertEqual(len(blocked), 0)
        self.assertEqual(len(gate["retired_credential_calls"]), 20)
        for item in gate["retired_credential_calls"]:
            self.assertEqual(
                item["disposition"],
                "RETIRED_WORKFLOW_FILE_REMOVED",
            )
            self.assertFalse((WORKFLOWS_DIR / item["workflow"]).exists())
            self.assertTrue(item["retirement_reason"].strip())
        self.assertEqual(
            {
                (item["workflow"], item["job"], item["call_index"])
                for item in inventory
            },
            {
                (item["workflow"], item["job"], item["call_index"])
                for item in collect_repository_credential_calls(WORKFLOWS_DIR)
            },
        )
        with self.assertRaisesRegex(
            CloudRolePolicyError,
            "template change is blocked",
        ):
            require_repo_global_oidc_cutover_ready(self.policy)

    def test_raw_oidc_workflows_are_deleted_and_globally_forbidden(self) -> None:
        entries = {
            item["workflow"]: item
            for item in self.policy["blocked_raw_oidc_workflows"]
        }
        self.assertEqual(set(entries), RAW_OIDC_QUARANTINE_WORKFLOWS)
        for workflow, entry in entries.items():
            self.assertFalse((WORKFLOWS_DIR / workflow).exists())
            self.assertEqual(entry["disposition"], "DELETE_WORKFLOW_FILE")
            self.assertTrue(entry["retired_reason"].strip())
        for workflow_path in WORKFLOWS_DIR.glob("*.y*ml"):
            text = workflow_path.read_text(encoding="utf-8")
            self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", text)
            self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST_URL", text)
            self.assertNotIn("assume-role-with-web-identity", text)

    def test_unclassified_repository_credential_call_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            (workflows / "unreviewed-aws.yml").write_text(
                "name: unreviewed\n"
                "on: workflow_dispatch\n"
                "jobs:\n"
                "  mutate:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: aws-actions/configure-aws-credentials@"
                "acca2b1b2070338fb9fd1ca27ecee81d687e58e5\n"
                "        with:\n"
                "          role-to-assume: arn:aws:iam::595710543956:"
                "role/Unreviewed\n"
                "          aws-region: us-east-1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "credential call set differs",
            ):
                validate_policy(self.policy, workflows)

    def test_retired_call_cannot_be_relabelled_migrated_without_contract(
        self,
    ) -> None:
        policy = copy.deepcopy(self.policy)
        gate = policy["repo_global_oidc_cutover_gate"]
        item = gate["retired_credential_calls"][0]
        item["disposition"] = MIGRATED_CREDENTIAL_DISPOSITION
        with self.assertRaisesRegex(
            CloudRolePolicyError,
            "retired AWS credential entry is incomplete",
        ):
            validate_policy(policy, WORKFLOWS_DIR)

    def test_repository_credential_role_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            target = workflows / "junca-public-testnet-live-soak.yml"
            target.write_text(
                target.read_text(encoding="utf-8").replace(
                    "${{ env.OBSERVER_ROLE_ARN }}",
                    "arn:aws:iam::595710543956:role/Unexpected",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "credential call set differs",
            ):
                validate_policy(self.policy, workflows)

    def test_cutover_state_cannot_claim_ready_without_external_evidence(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["repo_global_oidc_cutover_gate"][
            "activation_state"
        ] = CUTOVER_READY_STATE
        with self.assertRaisesRegex(
            CloudRolePolicyError,
            "ready OIDC cutover requires",
        ):
            validate_policy(policy, WORKFLOWS_DIR)

    def test_security_bootstrap_is_non_oidc(self) -> None:
        security = self.policy["roles"]["security_bootstrap"]
        self.assertFalse(security["oidc_enabled"])
        self.assertEqual(security["exact_workflow_allowlist"], [])
        self.assertEqual(security["exact_subject_allowlist"], [])
        self.assertEqual(
            security["trust_boundary"],
            "NON_OIDC_MFA_ADMIN_SESSION_ONLY",
        )
        self.assertEqual(
            security["prohibited_principals"],
            ["token.actions.githubusercontent.com"],
        )

    def test_state_migration_is_not_a_steady_state_oidc_workflow(self) -> None:
        self.assertNotIn(
            "junca-validator-state-migration.yml",
            ROLE_WORKFLOWS["foundation"],
        )
        self.assertEqual(
            self.policy["temporary_non_oidc_operations"],
            [
                {
                    "workflow": "junca-validator-state-migration.yml",
                    "purpose": "One-time durable validator state migration",
                    "steady_state_role_allowed": False,
                    "oidc_enabled": False,
                    "execution_state": (
                        "BLOCKED_UNTIL_DEDICATED_NON_OIDC_AUTHORIZATION"
                    ),
                }
            ],
        )

    def test_subject_drift_fails_closed(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["roles"]["observer"]["exact_subject_allowlist"][0] = LEGACY_SUBJECT
        with self.assertRaisesRegex(
            CloudRolePolicyError,
            "exact subject allowlist differs",
        ):
            validate_policy(policy, WORKFLOWS_DIR)

    def test_reintroduced_quarantine_workflow_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            retired = sorted(QUARANTINE_WORKFLOWS)[0]
            (workflows / retired).write_text(
                "name: unsafe\non: workflow_dispatch\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "quarantined workflow must be absent",
            ):
                validate_policy(self.policy, workflows)

    def test_stale_dispatch_reference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            retired = sorted(QUARANTINE_WORKFLOWS)[0]
            (workflows / "stale-reference.yml").write_text(
                f"# prohibited dispatch target: {retired}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "references quarantined workflows",
            ):
                validate_policy(self.policy, workflows)

    def test_role_to_assume_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            target = workflows / "junca-validator-ami-build.yml"
            text = target.read_text(encoding="utf-8").replace(
                "role/JuncaChainPublicTestnetAmiBuilder",
                "role/JuncaChainPublicTestnetDeployment",
            )
            target.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "acquired roles differ",
            ):
                validate_policy(self.policy, workflows)

    def test_missing_main_ref_and_sha_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            target = workflows / "junca-validator-ami-build.yml"
            text = target.read_text(encoding="utf-8")
            text = text.replace(
                'test "$GITHUB_REF" = "refs/heads/main"',
                'test "$GITHUB_REF" = "refs/heads/other"',
            )
            text = text.replace(
                'test "$GITHUB_SHA" = "$SOURCE_COMMIT"',
                'test "$GITHUB_RUN_ID" = "$SOURCE_COMMIT"',
            )
            text = text.replace('.head_branch == "main"', '.head_branch == "other"')
            text = text.replace(".head_sha ==", ".other_sha ==")
            target.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "untrusted source can execute",
            ):
                validate_policy(self.policy, workflows)

    def test_attestation_must_immediately_precede_aws_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            target = workflows / "junca-validator-ami-build.yml"
            text = target.read_text(encoding="utf-8").replace(
                "      - uses: aws-actions/configure-aws-credentials@",
                "      - name: Untrusted interposed code\n"
                "        run: echo unsafe\n\n"
                "      - uses: aws-actions/configure-aws-credentials@",
                1,
            )
            target.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "attestation must immediately precede",
            ):
                validate_policy(self.policy, workflows)

    def test_reintroduced_oidc_template_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / "workflows"
            shutil.copytree(WORKFLOWS_DIR, workflows)
            target = workflows / "unsafe-oidc-template.yml"
            target.write_text(
                "# actions/oidc/customization/sub\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CloudRolePolicyError,
                "repository OIDC template mutation is forbidden",
            ):
                validate_policy(self.policy, workflows)

    def test_policy_json_is_canonical_json(self) -> None:
        parsed = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(parsed, self.policy)


if __name__ == "__main__":
    unittest.main()
