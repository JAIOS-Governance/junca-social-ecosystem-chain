from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest

from scripts.junca_workflow_shell_contract import (
    WorkflowShellContractError,
    validate_workflows,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(step: str, *, shell: str | None = "bash") -> str:
    indented = textwrap.indent(textwrap.dedent(step).strip("\n"), "          ")
    shell_line = f"        shell: {shell}\n" if shell is not None else ""
    return (
        "name: Contract fixture\n"
        "on: workflow_dispatch\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-24.04\n"
        "    steps:\n"
        "      - name: Verify\n"
        f"{shell_line}"
        "        run: |\n"
        f"{indented}\n"
    )


class WorkflowShellContractTests(unittest.TestCase):
    def fixture(self, content: str) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workflows = Path(temporary.name)
        (workflows / "fixture.yml").write_text(content, encoding="utf-8")
        return workflows

    def test_repository_workflows_are_language_safe(self) -> None:
        summary = validate_workflows(WORKFLOWS)
        expected_workflows = len(
            {
                *WORKFLOWS.glob("*.yml"),
                *WORKFLOWS.glob("*.yaml"),
            }
        )
        self.assertEqual(summary.workflows, expected_workflows)
        self.assertGreater(summary.run_blocks, 0)
        self.assertGreater(summary.bash_run_blocks, 0)
        self.assertGreater(summary.heredocs, 0)
        self.assertGreater(summary.python_heredocs, 0)

    def test_yaml_dependency_is_hash_pinned_on_fresh_runners(self) -> None:
        requirement = (
            ROOT / "requirements/ci-yaml.txt"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            requirement,
            "PyYAML==6.0.3 \\\n"
            "    --hash=sha256:"
            "ba1cc08a7ccde2d2ec775841541641e4548226580ab850948"
            "cbfda66a1befcdc\n",
        )
        for workflow_name in (
            "junca-developer-environment-ci.yml",
            "junca-validator-runtime-artifacts.yml",
            "junca-social-ecosystem-chain-repository-governance.yml",
            "junca-social-ecosystem-chain-aws-plan.yml",
        ):
            text = (WORKFLOWS / workflow_name).read_text(
                encoding="utf-8"
            )
            self.assertIn('python-version: "3.12.11"', text)
            self.assertIn("--only-binary=:all:", text)
            self.assertIn("--require-hashes", text)
            self.assertIn("-r requirements/ci-yaml.txt", text)

    def test_invalid_yaml_fails_closed(self) -> None:
        workflows = self.fixture("name: [unterminated\n")
        with self.assertRaisesRegex(WorkflowShellContractError, "YAML parse failed"):
            validate_workflows(workflows)

    def test_bash_syntax_error_fails_closed(self) -> None:
        workflows = self.fixture(workflow("if true; then\n  echo missing-fi"))
        with self.assertRaisesRegex(WorkflowShellContractError, "invalid bash"):
            validate_workflows(workflows)

    def test_unclosed_heredoc_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                python3 - <<'PY'
                print("never closed")
                """
            )
        )
        with self.assertRaisesRegex(WorkflowShellContractError, "unclosed heredoc"):
            validate_workflows(workflows)

    def test_indented_heredoc_terminator_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                python3 - <<'PY'
                print("safe")
                  PY
                """
            )
        )
        with self.assertRaisesRegex(
            WorkflowShellContractError,
            "invalid indentation or whitespace",
        ):
            validate_workflows(workflows)

    def test_heredoc_requires_explicit_bash_shell(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                python3 - <<'PY'
                print("safe")
                PY
                """,
                shell=None,
            )
        )
        with self.assertRaisesRegex(
            WorkflowShellContractError,
            "must declare shell: bash explicitly",
        ):
            validate_workflows(workflows)

    def test_python_statement_directly_in_bash_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                set -euo pipefail
                import json
                """
            )
        )
        with self.assertRaisesRegex(
            WorkflowShellContractError,
            "Python statement outside",
        ):
            validate_workflows(workflows)

    def test_bash_inside_python_heredoc_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                python3 - <<'PY'
                set -euo pipefail
                PY
                """
            )
        )
        with self.assertRaisesRegex(
            WorkflowShellContractError,
            "bash statement inside",
        ):
            validate_workflows(workflows)

    def test_invalid_python_heredoc_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow(
                """
                python3 - <<'PY'
                if True
                    print("invalid")
                PY
                """
            )
        )
        with self.assertRaisesRegex(WorkflowShellContractError, "invalid Python"):
            validate_workflows(workflows)

    def test_bash_body_with_python_shell_fails_closed(self) -> None:
        workflows = self.fixture(
            workflow("set -euo pipefail\necho unsafe", shell="python")
        )
        with self.assertRaisesRegex(
            WorkflowShellContractError,
            "bash statement inside",
        ):
            validate_workflows(workflows)


if __name__ == "__main__":
    unittest.main()
