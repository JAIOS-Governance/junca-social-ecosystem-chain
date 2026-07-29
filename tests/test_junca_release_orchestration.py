from __future__ import annotations

import argparse
from pathlib import Path
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
    validate as validate_child_provenance,
)


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
    def test_exactly_one_automatic_release_controller(self) -> None:
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
        self.assertEqual(
            listeners,
            ["junca-hardened-immutable-candidate-release-v2.yml"],
        )
        for retired in (
            "junca-hardened-immutable-candidate-release.yml",
            "junca-validator-public-testnet-orchestrator.yml",
            "junca-runtime-release-evidence-collector.yml",
        ):
            self.assertFalse((WORKFLOWS / retired).exists())

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

    def test_parent_uses_immutable_ref_and_python_dispatcher(self) -> None:
        text = PARENT.read_text(encoding="utf-8")
        self.assertIn("contents: write", text)
        self.assertIn("release-candidate/$SOURCE_COMMIT", text)
        self.assertEqual(
            text.count("python3 scripts/junca_dispatch_workflow_and_wait.py"),
            3,
        )
        self.assertEqual(text.count('--dispatch-ref "$CANDIDATE_REF"'), 3)
        self.assertIn("--candidate-ami-run-id", text)

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
        parent = {
            "id": 12,
            "run_attempt": 3,
            "name": PARENT_NAME,
            "path": PARENT_PATH,
            "event": "workflow_run",
            "status": "in_progress",
            "head_branch": "main",
            "head_sha": SHA,
            "repository": {"full_name": FakeGitHub.repository},
            "head_repository": {"full_name": FakeGitHub.repository},
        }
        validate_child_provenance(
            parent,
            repository=FakeGitHub.repository,
            source_commit=SHA,
            dispatch_token=token,
            orchestrator_run_id="12",
            orchestrator_run_attempt="3",
            github_ref=f"refs/heads/{REF}",
            github_sha=SHA,
        )
        parent["status"] = "completed"
        with self.assertRaisesRegex(
            ProvenanceError, "canonical orchestrator"
        ):
            validate_child_provenance(
                parent,
                repository=FakeGitHub.repository,
                source_commit=SHA,
                dispatch_token=token,
                orchestrator_run_id="12",
                orchestrator_run_attempt="3",
                github_ref=f"refs/heads/{REF}",
                github_sha=SHA,
            )


if __name__ == "__main__":
    unittest.main()
