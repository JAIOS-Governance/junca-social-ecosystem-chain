from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "scripts/junca_dispatch_workflow_and_wait.sh"
HEAD = "a" * 40
RUN_ID = 30605099999
RUN_URL = (
    "https://github.com/JAIOS-Governance/"
    f"junca-social-ecosystem-chain/actions/runs/{RUN_ID}"
)


class DispatchWorkflowAndWaitTests(unittest.TestCase):
    def run_dispatch(self, conclusion: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_gh = root / "gh"
            fake_gh.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    args="$*"
                    if [[ "$args" == *"/git/ref/heads/main"* ]]; then
                      printf '%s\\n' '{HEAD}'
                    elif [[ "$args" == *"/actions/workflows?per_page=100"* ]]; then
                      printf '%s\\n' '{{"workflows":[{{"id":77,"name":"JUNCA Validator Foundation Release","path":".github/workflows/junca-validator-foundation-release.yml","state":"active"}}]}}'
                    elif [[ "$args" == *"/dispatches"* ]]; then
                      :
                    elif [[ "$args" == *"/runs?branch=main"* ]]; then
                      printf '%s\\n' '{{"workflow_runs":[{{"id":{RUN_ID},"created_at":"9999-12-31T23:59:59Z","head_sha":"{HEAD}"}}]}}'
                    elif [[ "$args" == *"/actions/runs/{RUN_ID}"* ]]; then
                      printf '%s\\n' '{{"id":{RUN_ID},"html_url":"{RUN_URL}","status":"completed","conclusion":"{conclusion}","name":"JUNCA Validator Foundation Release","path":".github/workflows/junca-validator-foundation-release.yml","event":"workflow_dispatch","head_branch":"main","head_sha":"{HEAD}","repository":{{"full_name":"JAIOS-Governance/junca-social-ecosystem-chain"}},"head_repository":{{"full_name":"JAIOS-Governance/junca-social-ecosystem-chain"}}}}'
                    else
                      printf 'unexpected gh invocation: %s\\n' "$args" >&2
                      exit 90
                    fi
                    """
                ),
                encoding="utf-8",
            )
            fake_gh.chmod(0o700)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{root}:{environment['PATH']}",
                    "GH_TOKEN": "test-token",
                    "GITHUB_REPOSITORY": "JAIOS-Governance/junca-social-ecosystem-chain",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(DISPATCH),
                    "--workflow-name",
                    "JUNCA Validator Foundation Release",
                    "--workflow-path",
                    ".github/workflows/junca-validator-foundation-release.yml",
                    "--expected-head",
                    HEAD,
                    "--evidence-path",
                    "artifacts/release-v2/foundation-dispatch.json",
                    "--attempts",
                    "1",
                    "--sleep-seconds",
                    "1",
                ],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            evidence = json.loads(
                (root / "artifacts/release-v2/foundation-dispatch.json").read_text(
                    encoding="utf-8"
                )
            )
            return result, evidence

    def test_failure_preserves_exact_child_evidence_without_stdout_id(self) -> None:
        result, evidence = self.run_dispatch("failure")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"run_id={RUN_ID}", result.stderr)
        self.assertIn(f"url={RUN_URL}", result.stderr)
        self.assertIn("conclusion=failure", result.stderr)
        self.assertEqual(evidence["schema_version"], "junca-workflow-dispatch-evidence/v1")
        self.assertEqual(evidence["run"]["id"], RUN_ID)
        self.assertEqual(evidence["run"]["url"], RUN_URL)
        self.assertEqual(evidence["run"]["conclusion"], "failure")
        self.assertTrue(evidence["identity_valid"])
        self.assertFalse(evidence["mainnet_changed"])

    def test_success_keeps_numeric_stdout_contract_and_evidence(self) -> None:
        result, evidence = self.run_dispatch("success")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{RUN_ID}\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(evidence["run"]["conclusion"], "success")
        self.assertTrue(evidence["identity_valid"])


if __name__ == "__main__":
    unittest.main()
