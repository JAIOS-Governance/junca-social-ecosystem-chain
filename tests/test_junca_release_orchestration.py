from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts.junca_dispatch_workflow_and_wait import (
    DispatchError,
    ensure_candidate_ref,
    parse_inputs,
    validate_arguments,
    verify_completed_run,
)
from scripts.junca_release_child_provenance import (
    PARENT_NAME,
    PARENT_PATH,
    ProvenanceError,
    canonical_inputs_sha256,
    validate as validate_child_provenance,
)
from scripts.junca_release_dispatch_attestation import build_attestation


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
PARENT = WORKFLOWS / "junca-hardened-immutable-candidate-release-v2.yml"
AMI = WORKFLOWS / "junca-validator-ami-build.yml"
EVIDENCE = WORKFLOWS / "junca-runtime-release-evidence-collector-v2.yml"
MANIFEST = WORKFLOWS / "junca-runtime-release-manifest-gate.yml"
OBSERVER = WORKFLOWS / "junca-public-testnet-release-observer.yml"
FOUNDATION = WORKFLOWS / "junca-validator-foundation-release.yml"
PUBLIC_RELEASE = WORKFLOWS / "junca-public-testnet-release.yml"
SHA = "a" * 40
REF = f"release-candidate/{SHA}"
PINNED_ACTIONS = {
    "actions/checkout": frozenset(
        {"11d5960a326750d5838078e36cf38b85af677262"}
    ),
    "actions/download-artifact": frozenset(
        {"d3f86a106a0bac45b974a628896c90dbdf5c8093"}
    ),
    "actions/setup-node": frozenset(
        {"49933ea5288caeca8642d1e84afbd3f7d6820020"}
    ),
    "actions/setup-python": frozenset(
        {"a26af69be951a213d495a4c3e4e4022e16d87065"}
    ),
    "actions/upload-artifact": frozenset(
        {"ea165f8d65b6e75b540449e92b4886f43607fa02"}
    ),
    "anchore/sbom-action": frozenset(
        {"e22c389904149dbc22b58101806040fa8d37a610"}
    ),
    "aws-actions/configure-aws-credentials": frozenset(
        {
            "7474bc4690e29a8392af63c5b98e7449536d5c3a",
            "acca2b1b2070338fb9fd1ca27ecee81d687e58e5",
        }
    ),
    "hashicorp/setup-terraform": frozenset(
        {"b9cd54a3c349d3f38e8881555d616ced269862dd"}
    ),
}
AWS_PROVIDER_HASHES = {
    "054b8dd49f0549c9a7cc27d159e45327b7b65cf404da5e5a20da154b90b8a644",
    "0b97bf8d5e03d15d83cc40b0530a1f84b459354939ba6f135a0086c20ebbe6b2",
    "1589a2266af699cbd5d80737a0fe02e54ec9cf2ca54e7e00ac51c7359056f274",
    "6330766f1d85f01ae6ea90d1b214b8b74cc8c1badc4696b165b36ddd4cc15f7b",
    "7c8c2e30d8e55291b86fcb64bdf6c25489d538688545eb48fd74ad622e5d3862",
    "99b1003bd9bd32ee323544da897148f46a527f622dc3971af63ea3e251596342",
    "9f8b909d3ec50ade83c8062290378b1ec553edef6a447c56dadc01a99f4eaa93",
    "aaef921ff9aabaf8b1869a86d692ebd24fbd4e12c21205034bb679b9caf883a2",
    "ac882313207aba00dd5a76dbd572a0ddc818bb9cbf5c9d61b28fe30efaec951e",
    "bb64e8aff37becab373a1a0cc1080990785304141af42ed6aa3dd4913b000421",
    "dfe495f6621df5540d9c92ad40b8067376350b005c637ea6efac5dc15028add4",
    "f0ddf0eaf052766cfe09dea8200a946519f653c384ab4336e2a4a64fdd6310e9",
    "f1b7e684f4c7ae1eed272b6de7d2049bb87a0275cb04dbb7cda6636f600699c9",
    "ff461571e3f233699bf690db319dfe46aec75e58726636a0d97dd9ac6e32fb70",
}


def run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip() != "run: |":
            index += 1
            continue
        indent = len(line) - len(line.lstrip())
        index += 1
        body: list[str] = []
        while index < len(lines):
            current = lines[index]
            current_indent = len(current) - len(current.lstrip())
            if current.strip() and current_indent <= indent:
                break
            body.append(current[indent + 2 :])
            index += 1
        blocks.append("\n".join(body).strip())
    return blocks


class FakeGitHub:
    repository = "JAIOS-Governance/junca-social-ecosystem-chain"

    def __init__(self, resolved: str | None) -> None:
        self.resolved = resolved
        self.created = False

    def api(self, endpoint, *arguments, allow_failure=False):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if endpoint.endswith("/git/refs"):
            self.created = True
            self.resolved = SHA
        return Result()


class ReleaseOrchestrationTests(unittest.TestCase):
    def test_release_controller_requires_explicit_exact_supply_chain(
        self,
    ) -> None:
        listeners = []
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if (
                'workflows:\n      - "JUNCA Validator Runtime Artifacts"'
                in text
                and "types: [completed]" in text
                and "workflow_run.conclusion == 'success'" in text
            ):
                listeners.append(path.name)
        self.assertEqual(listeners, [])
        parent = PARENT.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", parent)
        self.assertNotIn("workflow_run:", parent)
        self.assertIn(
            'test "$APPROVAL_PHRASE" = \\\n'
            '            "PUBLIC_TESTNET_IMMUTABLE_CANDIDATE"',
            parent,
        )
        self.assertNotIn("if: inputs.approval_phrase", parent)
        self.assertIn(
            'test "$GITHUB_REF" = "refs/heads/main"',
            parent,
        )
        self.assertIn(
            'test "$GITHUB_SHA" = "$SOURCE_COMMIT"',
            parent,
        )
        for retired in (
            "junca-hardened-immutable-candidate-release.yml",
            "junca-validator-public-testnet-orchestrator.yml",
            "junca-runtime-release-evidence-collector.yml",
        ):
            self.assertFalse((WORKFLOWS / retired).exists())

    def test_release_execution_dependencies_are_immutable(self) -> None:
        action_pattern = re.compile(
            r"^\s*(?:-\s+)?uses:\s+([^#\s]+)",
            re.MULTILINE,
        )
        external_count = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                external = [
                    value
                    for value in action_pattern.findall(text)
                    if not value.startswith("./")
                ]
                external_count += len(external)
                for value in external:
                    action, separator, revision = value.partition("@")
                    self.assertEqual(separator, "@")
                    self.assertIn(
                        revision,
                        PINNED_ACTIONS.get(action, frozenset()),
                        f"unapproved action revision in {path.name}: {value}",
                    )
                uses_credential_action = any(
                    value.startswith(
                        "aws-actions/configure-aws-credentials@"
                    )
                    for value in external
                )
                uses_raw_oidc = any(
                    marker in text
                    for marker in (
                        "assume-role-with-web-identity",
                        "ACTIONS_ID_TOKEN_REQUEST_URL",
                    )
                )
                has_cloud_identity = uses_credential_action or uses_raw_oidc
                if has_cloud_identity:
                    self.assertIn("\n  workflow_dispatch:", text)
                    self.assertNotIn(
                        "\n  push:",
                        text,
                        f"AWS workflow must be fail-closed: {path.name}",
                    )
                if uses_raw_oidc:
                    self.assertNotIn("\n  pull_request:", text)
                    self.assertNotIn("\n  workflow_run:", text)
        self.assertGreater(external_count, 0)

        for module in ("bootstrap", "public-testnet"):
            with self.subTest(terraform_module=module):
                directory = ROOT / "infra" / "aws" / module
                main = (directory / "main.tf").read_text(encoding="utf-8")
                lock = (directory / ".terraform.lock.hcl").read_text(
                    encoding="utf-8"
                )
                self.assertIn('version = "= 5.100.0"', main)
                self.assertNotIn('version = "~>', main)
                self.assertIn('version     = "5.100.0"', lock)
                self.assertIn('constraints = "5.100.0"', lock)
                self.assertEqual(
                    set(re.findall(r'"zh:([0-9a-f]{64})"', lock)),
                    AWS_PROVIDER_HASHES,
                )

    def test_parent_stops_before_unsafe_fresh_rollout(self) -> None:
        text = PARENT.read_text(encoding="utf-8")
        self.assertIn(
            "PUBLIC_TESTNET_CANDIDATE_READY_FOR_SERIAL_ROLLOUT", text
        )
        self.assertIn("serial_rollout_dispatched: false", text)
        self.assertIn("continuity_dispatched: false", text)
        self.assertNotIn('resume_run_id=0', text)
        self.assertNotIn("JUNCA Validator Foundation Release", text)
        self.assertNotIn("JUNCA Public Testnet Continuity Evidence", text)
        self.assertNotIn("junca_dispatch_workflow_and_wait.sh", text)

    def test_public_release_rejects_invalid_trigger_without_skip_success(
        self,
    ) -> None:
        text = PUBLIC_RELEASE.read_text(encoding="utf-8")
        job_prefix = text.split("  publish-and-verify:", 1)[1].split(
            "    runs-on:", 1
        )[0]
        self.assertNotIn("if:", job_prefix)
        self.assertIn("Authorize exact release trigger", text)
        self.assertIn(
            'test "$GITHUB_REF" = \\\n'
            '                "refs/heads/release-candidate/$GITHUB_SHA"',
            text,
        )
        self.assertIn(
            '"release-candidate/$WORKFLOW_RUN_HEAD_SHA"',
            text,
        )
        self.assertIn(
            'if [[ "$EVENT_NAME" == "workflow_dispatch" ]]; then\n'
            '            test "$GITHUB_SHA" = "$head_sha"',
            text,
        )

    def test_parent_uses_immutable_ref_and_python_dispatcher(self) -> None:
        text = PARENT.read_text(encoding="utf-8")
        self.assertIn("contents: write", text)
        self.assertIn("release-candidate/$SOURCE_COMMIT", text)
        self.assertEqual(
            text.count("python3 scripts/junca_dispatch_workflow_and_wait.py"),
            3,
        )
        self.assertEqual(text.count('--dispatch-ref "$CANDIDATE_REF"'), 3)
        self.assertEqual(text.count("--dispatch-token"), 6)
        self.assertIn(
            "junca-release-dispatch-attestation-"
            "${{ github.run_id }}-${{ github.run_attempt }}-ami",
            text,
        )
        self.assertIn(
            "python3 scripts/junca_release_dispatch_attestation.py",
            text,
        )
        self.assertEqual(
            text.count("python3 scripts/junca_release_dispatch_attestation.py"),
            3,
        )
        self.assertIn("--candidate-ami-run-id", text)

    def test_ami_child_parent_request_and_dispatch_contracts_are_exact(
        self,
    ) -> None:
        parent = PARENT.read_text(encoding="utf-8")
        child = AMI.read_text(encoding="utf-8")
        input_section = child.split("inputs:", 1)[1].split(
            "\npermissions:", 1
        )[0]
        child_inputs = set(
            re.findall(
                r"^      ([a-z0-9_]+):$",
                input_section,
                re.MULTILINE,
            )
        )
        expected_business_inputs = child_inputs - {
            "dispatch_token",
            "orchestrator_run_id",
            "orchestrator_run_attempt",
        }
        self.assertEqual(
            expected_business_inputs,
            {
                "source_run_id",
                "source_commit",
                "node_artifact_name",
                "genesis_artifact_name",
                "node_sha256",
                "genesis_sha256",
                "parent_ami_id",
                "parent_ami_owner_id",
                "parent_ami_name",
                "component_source_sha256",
                "dependency_lock_sha256",
                "dnf_releasever",
                "python3_boto3_nevra",
                "python3_botocore_nevra",
                "request_sha256",
            },
        )
        ami_path = (
            '--workflow-path ".github/workflows/'
            'junca-validator-ami-build.yml"'
        )
        first = parent.index(ami_path)
        attestation_block = parent[
            first : parent.index("\n          {\n", first)
        ]
        second = parent.index(ami_path, first + 1)
        dispatch_block = parent[
            second : parent.index('\n          )"', second)
        ]
        key_pattern = r'--input (?:\\\n\s+)?"([a-z0-9_]+)='
        self.assertEqual(
            set(re.findall(key_pattern, attestation_block)),
            expected_business_inputs,
        )
        self.assertEqual(
            set(re.findall(key_pattern, dispatch_block)),
            expected_business_inputs,
        )
        self.assertIn(
            'schema_version: "junca-validator-ami-build-request/v2"',
            parent,
        )
        self.assertNotIn(
            'schema_version: "junca-validator-ami-build-request/v1"',
            parent,
        )

    def test_children_require_canonical_parent_and_exact_source(self) -> None:
        for path in (AMI, EVIDENCE, MANIFEST):
            text = path.read_text(encoding="utf-8")
            self.assertIn("run-name: JSEC dispatch", text)
            self.assertIn("dispatch_token:", text)
            self.assertIn("orchestrator_run_id:", text)
            self.assertIn("orchestrator_run_attempt:", text)
            self.assertIn(
                "python3 scripts/junca_release_child_provenance.py", text
            )
            self.assertIn("--workflow-path", text)
            self.assertIn("--input", text)
            self.assertIn("ref: ${{ inputs.source_commit }}", text)
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn(
            '.path == ".github/workflows/'
            'junca-runtime-release-evidence-collector-v2.yml"',
            manifest,
        )
        self.assertIn(".head_sha == $source_commit", manifest)
        self.assertNotIn(
            ".github/workflows/junca-runtime-release-evidence-collector.yml",
            manifest,
        )

    def test_parent_run_blocks_are_strict_and_expression_free(self) -> None:
        blocks = run_blocks(PARENT.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(blocks), 5)
        for block in blocks:
            self.assertTrue(block.startswith("set -euo pipefail"))
            self.assertNotIn("${{", block)
            self.assertNotIn("<<EOF", block)

    def test_observer_preserves_immutable_candidate(self) -> None:
        text = OBSERVER.read_text(encoding="utf-8")
        self.assertIn("IMMUTABLE_CANDIDATE_REF", text)
        self.assertIn(
            'workflow_path="junca-hardened-immutable-candidate-release-v2.yml"',
            text,
        )
        self.assertIn(
            'workflow_path="junca-runtime-release-evidence-collector-v2.yml"',
            text,
        )
        self.assertIn(
            "In-flight immutable candidates are never cancelled merely "
            "because main advances",
            text,
        )
        self.assertIn("actions: read", text)
        self.assertIn("HUMAN_REVIEW_REQUIRED", text)
        self.assertIn("CONTINUITY_CONTRACT_TEST", text)
        self.assertIn("CONTRACT_TEST_PASS", text)
        self.assertIn("live_state_eligible=false", text)
        self.assertNotIn("pending_deployments", text)
        self.assertNotIn('"approved"', text)

    def test_serial_rollout_consumes_only_immutable_candidate_runs(self) -> None:
        foundation = FOUNDATION.read_text(encoding="utf-8")
        public_release = PUBLIC_RELEASE.read_text(encoding="utf-8")
        for text in (foundation, public_release):
            self.assertIn("refs/heads/release-candidate/", text)
            self.assertIn(
                '"release-candidate/" + .head_sha',
                text,
            )
        self.assertEqual(
            foundation.count(
                '.head_branch == ("release-candidate/" + $head)'
            ),
            2,
        )
        self.assertIn(
            'test "$GITHUB_REF" = '
            '"refs/heads/release-candidate/$GITHUB_SHA"',
            foundation,
        )
        self.assertEqual(
            foundation.count("sha256sum --strict --check SHA256SUMS"),
            2,
        )
        self.assertNotIn(
            "github.ref == 'refs/heads/main'",
            foundation,
        )

    def test_post_release_chain_accepts_candidate_foundation_only(self) -> None:
        for path in (
            WORKFLOWS / "junca-public-testnet-live-soak.yml",
            WORKFLOWS
            / "junca-public-testnet-runtime-acceptance-gate.yml",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                '.head_branch == ("release-candidate/" + $source_commit)',
                text,
            )
            self.assertIn(".head_sha == $source_commit", text)
            foundation_block = text.split(
                ".github/workflows/"
                "junca-validator-foundation-release.yml",
                1,
            )[1]
            self.assertNotIn('.head_branch == "main"', foundation_block[:600])

    def test_dispatch_inputs_reject_ambiguity_and_newlines(self) -> None:
        self.assertEqual(parse_inputs(["alpha=one=two"]), {"alpha": "one=two"})
        for values in (
            ["broken"],
            ["9bad=value"],
            ["same=one", "same=two"],
            ["value=line\nbreak"],
        ):
            with self.subTest(values=values):
                with self.assertRaises(DispatchError):
                    parse_inputs(values)

    def test_dispatch_ref_is_exact_sha_bound(self) -> None:
        valid = argparse.Namespace(
            workflow_name="JUNCA Runtime Release Manifest Gate",
            workflow_path=".github/workflows/"
            "junca-runtime-release-manifest-gate.yml",
            expected_head=SHA,
            dispatch_ref=REF,
            dispatch_token="12-3-" + "f" * 32,
            attempts=1,
            sleep_seconds=1,
        )
        validate_arguments(valid)
        valid.dispatch_ref = f"release-candidate/{'b' * 40}"
        with self.assertRaisesRegex(DispatchError, "not bound"):
            validate_arguments(valid)

    def test_candidate_ref_is_create_once_and_never_moved(self) -> None:
        github = FakeGitHub(None)
        with mock.patch(
            "scripts.junca_dispatch_workflow_and_wait.resolve_candidate_ref",
            side_effect=[None, SHA],
        ):
            ensure_candidate_ref(github, REF, SHA)
        self.assertTrue(github.created)
        with mock.patch(
            "scripts.junca_dispatch_workflow_and_wait.resolve_candidate_ref",
            return_value="b" * 40,
        ):
            with self.assertRaisesRegex(DispatchError, "mismatch"):
                ensure_candidate_ref(github, REF, SHA)

    def test_completed_run_requires_token_ref_sha_and_repository(self) -> None:
        token = "12-3-" + "f" * 32
        title = f"JSEC dispatch {token}"
        run = {
            "id": 44,
            "status": "completed",
            "conclusion": "success",
            "name": "JUNCA Runtime Release Manifest Gate",
            "path": ".github/workflows/"
            "junca-runtime-release-manifest-gate.yml",
            "event": "workflow_dispatch",
            "head_branch": REF,
            "head_sha": SHA,
            "display_title": title,
            "repository": {"full_name": FakeGitHub.repository},
            "head_repository": {"full_name": FakeGitHub.repository},
        }
        self.assertEqual(
            verify_completed_run(
                run,
                repository=FakeGitHub.repository,
                workflow_name=run["name"],
                workflow_path=run["path"],
                dispatch_ref=REF,
                expected_head=SHA,
                display_title=title,
            ),
            44,
        )
        run["head_sha"] = "b" * 40
        with self.assertRaisesRegex(DispatchError, "rejected"):
            verify_completed_run(
                run,
                repository=FakeGitHub.repository,
                workflow_name=run["name"],
                workflow_path=run["path"],
                dispatch_ref=REF,
                expected_head=SHA,
                display_title=title,
            )

    def test_child_provenance_is_live_parent_bound(self) -> None:
        token = "12-3-" + "f" * 32
        workflow_path = (
            ".github/workflows/junca-runtime-release-manifest-gate.yml"
        )
        workflow_inputs = {
            "evidence_run_id": "44",
            "source_commit": SHA,
            "node_artifact_sha256": "b" * 64,
            "genesis_sha256": "c" * 64,
        }
        attestation = build_attestation(
            orchestrator_run_id="12",
            orchestrator_run_attempt="3",
            source_commit=SHA,
            workflow_path=workflow_path,
            dispatch_token=token,
            workflow_inputs=workflow_inputs,
        )
        self.assertEqual(
            attestation["dispatch"]["inputs_sha256"],
            canonical_inputs_sha256(workflow_inputs),
        )
        parent = {
            "id": 12,
            "run_attempt": 3,
            "name": PARENT_NAME,
            "path": PARENT_PATH,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "head_branch": "main",
            "head_sha": SHA,
            "repository": {"full_name": FakeGitHub.repository},
            "head_repository": {"full_name": FakeGitHub.repository},
        }
        validate_child_provenance(
            parent,
            attestation,
            repository=FakeGitHub.repository,
            source_commit=SHA,
            dispatch_token=token,
            orchestrator_run_id="12",
            orchestrator_run_attempt="3",
            github_ref=f"refs/heads/{REF}",
            github_sha=SHA,
            workflow_path=workflow_path,
            workflow_inputs=workflow_inputs,
        )
        forged = {
            **attestation,
            "dispatch": {
                **attestation["dispatch"],
                "dispatch_token": "12-3-" + "a" * 32,
            },
        }
        with self.assertRaisesRegex(
            ProvenanceError, "not issued"
        ):
            validate_child_provenance(
                parent,
                forged,
                repository=FakeGitHub.repository,
                source_commit=SHA,
                dispatch_token=token,
                orchestrator_run_id="12",
                orchestrator_run_attempt="3",
                github_ref=f"refs/heads/{REF}",
                github_sha=SHA,
                workflow_path=workflow_path,
                workflow_inputs=workflow_inputs,
            )
        swapped_inputs = {**workflow_inputs, "evidence_run_id": "45"}
        with self.assertRaisesRegex(ProvenanceError, "exact child inputs"):
            validate_child_provenance(
                parent,
                attestation,
                repository=FakeGitHub.repository,
                source_commit=SHA,
                dispatch_token=token,
                orchestrator_run_id="12",
                orchestrator_run_attempt="3",
                github_ref=f"refs/heads/{REF}",
                github_sha=SHA,
                workflow_path=workflow_path,
                workflow_inputs=swapped_inputs,
            )
        parent["event"] = "workflow_run"
        with self.assertRaisesRegex(
            ProvenanceError, "canonical orchestrator"
        ):
            validate_child_provenance(
                parent,
                attestation,
                repository=FakeGitHub.repository,
                source_commit=SHA,
                dispatch_token=token,
                orchestrator_run_id="12",
                orchestrator_run_attempt="3",
                github_ref=f"refs/heads/{REF}",
                github_sha=SHA,
                workflow_path=workflow_path,
                workflow_inputs=workflow_inputs,
            )
        parent["event"] = "workflow_dispatch"
        parent["status"] = "completed"
        with self.assertRaisesRegex(
            ProvenanceError, "canonical orchestrator"
        ):
            validate_child_provenance(
                parent,
                attestation,
                repository=FakeGitHub.repository,
                source_commit=SHA,
                dispatch_token=token,
                orchestrator_run_id="12",
                orchestrator_run_attempt="3",
                github_ref=f"refs/heads/{REF}",
                github_sha=SHA,
                workflow_path=workflow_path,
                workflow_inputs=workflow_inputs,
            )

    def test_dispatch_attestation_cli_binds_exact_inputs(self) -> None:
        token = "12-3-" + "f" * 32
        workflow_path = (
            ".github/workflows/"
            "junca-runtime-release-evidence-collector-v2.yml"
        )
        workflow_inputs = {
            "ami_run_id": "44",
            "migration_run_id": "45",
            "migration_evidence_sha256": "b" * 64,
            "source_commit": SHA,
        }
        with TemporaryDirectory() as directory:
            output = Path(directory, "attestation")
            command = [
                "python",
                str(ROOT / "scripts/junca_release_dispatch_attestation.py"),
                "--source-commit",
                SHA,
                "--workflow-path",
                workflow_path,
                "--dispatch-token",
                token,
                "--output-dir",
                str(output),
            ]
            for key, value in workflow_inputs.items():
                command.extend(("--input", f"{key}={value}"))
            environment = {
                **os.environ,
                "GITHUB_RUN_ID": "12",
                "GITHUB_RUN_ATTEMPT": "3",
            }
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                ["SHA256SUMS", "dispatch-attestation.json"],
            )
            value = json.loads(
                (output / "dispatch-attestation.json").read_text()
            )
            self.assertEqual(value["dispatch"]["inputs"], workflow_inputs)
            self.assertEqual(
                value["dispatch"]["inputs_sha256"],
                canonical_inputs_sha256(workflow_inputs),
            )


if __name__ == "__main__":
    unittest.main()
