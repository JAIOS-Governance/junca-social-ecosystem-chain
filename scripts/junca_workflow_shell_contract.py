#!/usr/bin/env python3
"""Validate language and heredoc boundaries in GitHub Actions workflows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


HEREDOC_OPEN_RE = re.compile(
    r"(?<!<)<<(?P<strip_tabs>-)?\s*"
    r"(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P=quote)"
)
PYTHON_COMMAND_RE = re.compile(
    r"(?:^|[\s;&|()])python(?:3(?:\.\d+)?)?(?:\s|$)"
)
PYTHON_FILE_RE = re.compile(r"(?:^|[\s>])[^<>|;&\s]+\.py(?:\s|$)")
PYTHON_IN_BASH_PATTERNS = (
    re.compile(r"^\s*(?:from\s+[A-Za-z_][\w.]*\s+import\b|import\s+[A-Za-z_])"),
    re.compile(r"^\s*(?:async\s+def|def|class)\s+[A-Za-z_]\w*"),
    re.compile(
        r"^\s*(?:try|else|finally):\s*(?:#.*)?$|"
        r"^\s*(?:except|elif|for\s+.+\s+in|while\s+.+|with\s+.+|if\s+.+):"
        r"\s*(?:#.*)?$"
    ),
    re.compile(r"^\s*(?:print|isinstance|enumerate)\s*\("),
    re.compile(r"^\s*(?:raise|assert|yield|pass)\b"),
    re.compile(r"^\s*[A-Za-z_]\w*(?:\[[^]]+\])?\s+=\s+[^=]"),
    re.compile(
        r"^\s*(?:sys|os|json|pathlib|subprocess|requests|boto3|hashlib|base64)"
        r"\.[A-Za-z_]\w*\s*\("
    ),
)
BASH_IN_PYTHON_PATTERNS = (
    re.compile(r"^\s*set\s+-[A-Za-z]"),
    re.compile(r"^\s*(?:echo|export|source|chmod|mkdir|curl|aws|jq)\s+"),
    re.compile(r"^\s*(?:if\s+\[\[|fi\s*$|then\s*$|done\s*$|case\s+|esac\s*$)"),
    re.compile(r"^\s*[A-Za-z_]\w*=\$\("),
)
BASH_SHELLS = {"bash", "sh"}
PYTHON_SHELLS = {"python", "python3"}


class WorkflowShellContractError(RuntimeError):
    """A workflow violates its declared shell or heredoc contract."""


@dataclass(frozen=True)
class RunBlock:
    path: Path
    line: int
    body_line: int
    shell: str
    shell_explicit: bool
    runner: str
    body: str


@dataclass
class PendingHeredoc:
    delimiter: str
    strip_tabs: bool
    line: int
    command: str
    body: list[str]


@dataclass(frozen=True)
class ContractSummary:
    workflows: int
    run_blocks: int
    bash_run_blocks: int
    heredocs: int
    python_heredocs: int


def _mapping(node: Node) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    return {
        key.value: value
        for key, value in node.value
        if isinstance(key, ScalarNode)
    }


def _scalar(mapping: dict[str, Node], key: str, default: str = "") -> str:
    node = mapping.get(key)
    return node.value if isinstance(node, ScalarNode) else default


def _default_shell(mapping: dict[str, Node]) -> str:
    defaults_node = mapping.get("defaults")
    defaults = _mapping(defaults_node) if defaults_node is not None else {}
    run_node = defaults.get("run")
    run = _mapping(run_node) if run_node is not None else {}
    return _scalar(run, "shell")


def _load_workflow(path: Path) -> Node:
    try:
        document = yaml.compose(
            path.read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowShellContractError(
            f"{path}: YAML parse failed: {exc}"
        ) from exc
    if not isinstance(document, MappingNode):
        raise WorkflowShellContractError(f"{path}: workflow must be a YAML mapping")
    return document


def _run_blocks(path: Path, document: Node) -> list[RunBlock]:
    root = _mapping(document)
    workflow_shell = _default_shell(root)
    jobs = root.get("jobs")
    if not isinstance(jobs, MappingNode):
        raise WorkflowShellContractError(f"{path}: jobs mapping is missing")

    blocks: list[RunBlock] = []
    for job_key, job_node in jobs.value:
        if not isinstance(job_key, ScalarNode) or not isinstance(job_node, MappingNode):
            raise WorkflowShellContractError(f"{path}: invalid job mapping")
        job = _mapping(job_node)
        steps = job.get("steps")
        if steps is None:
            continue
        if not isinstance(steps, SequenceNode):
            raise WorkflowShellContractError(
                f"{path}:{steps.start_mark.line + 1}: steps must be a sequence"
            )
        runner = _scalar(job, "runs-on")
        job_shell = _default_shell(job) or workflow_shell
        for step_node in steps.value:
            if not isinstance(step_node, MappingNode):
                raise WorkflowShellContractError(
                    f"{path}:{step_node.start_mark.line + 1}: step must be a mapping"
                )
            step = _mapping(step_node)
            run = step.get("run")
            if run is None:
                continue
            if not isinstance(run, ScalarNode):
                raise WorkflowShellContractError(
                    f"{path}:{run.start_mark.line + 1}: run must be a scalar"
                )
            shell = _scalar(step, "shell") or job_shell
            shell_explicit = bool(shell)
            if not shell:
                shell = "bash" if "ubuntu" in runner else "platform-default"
            blocks.append(
                RunBlock(
                    path=path,
                    line=run.start_mark.line + 1,
                    body_line=run.start_mark.line + 2,
                    shell=shell.split()[0],
                    shell_explicit=shell_explicit,
                    runner=runner,
                    body=run.value,
                )
            )
    return blocks


def _looks_like_python(line: str) -> bool:
    return any(pattern.search(line) for pattern in PYTHON_IN_BASH_PATTERNS)


def _looks_like_bash(line: str) -> bool:
    return any(pattern.search(line) for pattern in BASH_IN_PYTHON_PATTERNS)


def _is_python_heredoc(heredoc: PendingHeredoc) -> bool:
    return bool(
        PYTHON_COMMAND_RE.search(heredoc.command)
        or (
            heredoc.delimiter in {"PY", "PYTHON"}
            and PYTHON_FILE_RE.search(heredoc.command)
        )
    )


def _validate_python_source(
    source: str,
    *,
    path: Path,
    line: int,
    description: str,
) -> None:
    for offset, source_line in enumerate(source.splitlines()):
        if _looks_like_bash(source_line):
            raise WorkflowShellContractError(
                f"{path}:{line + offset}: bash statement inside {description}: "
                f"{source_line.strip()}"
            )
    try:
        compile(source, f"{path}:{line}", "exec")
    except SyntaxError as exc:
        error_line = line + max((exc.lineno or 1) - 1, 0)
        raise WorkflowShellContractError(
            f"{path}:{error_line}: invalid Python in {description}: {exc.msg}"
        ) from exc


def _validate_bash_syntax(block: RunBlock) -> None:
    try:
        result = subprocess.run(
            ["bash", "-n"],
            input=block.body,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise WorkflowShellContractError(
            f"{block.path}:{block.line}: bash is unavailable"
        ) from exc
    diagnostics = result.stderr.strip()
    if result.returncode != 0 or diagnostics:
        detail = diagnostics.splitlines()[0] if diagnostics else "bash -n failed"
        raise WorkflowShellContractError(
            f"{block.path}:{block.line}: invalid bash run block: {detail}"
        )


def _validate_bash_block(block: RunBlock) -> tuple[int, int]:
    pending: list[PendingHeredoc] = []
    heredoc_count = 0
    python_heredoc_count = 0

    for offset, line in enumerate(block.body.splitlines()):
        source_line = block.body_line + offset
        if pending:
            current = pending[0]
            candidate = line.lstrip("\t") if current.strip_tabs else line
            if candidate == current.delimiter:
                pending.pop(0)
                heredoc_count += 1
                if _is_python_heredoc(current):
                    python_heredoc_count += 1
                    _validate_python_source(
                        "\n".join(current.body) + "\n",
                        path=block.path,
                        line=current.line + 1,
                        description=(
                            f"Python heredoc opened at line {current.line}"
                        ),
                    )
                continue
            if line.strip() == current.delimiter:
                raise WorkflowShellContractError(
                    f"{block.path}:{source_line}: heredoc terminator "
                    f"{current.delimiter!r} has invalid indentation or whitespace"
                )
            current.body.append(line)
            continue

        matches = list(HEREDOC_OPEN_RE.finditer(line))
        if matches:
            for match in matches:
                pending.append(
                    PendingHeredoc(
                        delimiter=match.group("delimiter"),
                        strip_tabs=bool(match.group("strip_tabs")),
                        line=source_line,
                        command=line,
                        body=[],
                    )
                )
            continue

        if _looks_like_python(line):
            raise WorkflowShellContractError(
                f"{block.path}:{source_line}: Python statement outside a Python "
                f"heredoc in bash run block: {line.strip()}"
            )

    if pending:
        current = pending[0]
        raise WorkflowShellContractError(
            f"{block.path}:{current.line}: unclosed heredoc "
            f"{current.delimiter!r}"
        )
    if heredoc_count and not block.shell_explicit:
        raise WorkflowShellContractError(
            f"{block.path}:{block.line}: heredoc run block must declare "
            f"shell: bash explicitly"
        )
    _validate_bash_syntax(block)
    return heredoc_count, python_heredoc_count


def _validate_run_block(block: RunBlock) -> tuple[int, int, bool]:
    if block.shell in BASH_SHELLS:
        heredocs, python_heredocs = _validate_bash_block(block)
        return heredocs, python_heredocs, True
    if block.shell in PYTHON_SHELLS:
        _validate_python_source(
            block.body,
            path=block.path,
            line=block.body_line,
            description=f"{block.shell} run block",
        )
        return 0, 0, False
    if block.shell == "platform-default":
        raise WorkflowShellContractError(
            f"{block.path}:{block.line}: shell is ambiguous for runner "
            f"{block.runner!r}"
        )
    if any(_looks_like_bash(line) for line in block.body.splitlines()):
        raise WorkflowShellContractError(
            f"{block.path}:{block.line}: bash-looking body uses shell "
            f"{block.shell!r}"
        )
    return 0, 0, False


def validate_workflows(workflows_dir: Path) -> ContractSummary:
    paths = sorted(
        {
            *workflows_dir.glob("*.yml"),
            *workflows_dir.glob("*.yaml"),
        }
    )
    if not paths:
        raise WorkflowShellContractError(
            f"{workflows_dir}: no workflow YAML files found"
        )

    run_blocks = 0
    bash_run_blocks = 0
    heredocs = 0
    python_heredocs = 0
    for path in paths:
        document = _load_workflow(path)
        for block in _run_blocks(path, document):
            run_blocks += 1
            block_heredocs, block_python_heredocs, is_bash = _validate_run_block(
                block
            )
            bash_run_blocks += int(is_bash)
            heredocs += block_heredocs
            python_heredocs += block_python_heredocs
    return ContractSummary(
        workflows=len(paths),
        run_blocks=run_blocks,
        bash_run_blocks=bash_run_blocks,
        heredocs=heredocs,
        python_heredocs=python_heredocs,
    )


def _format_summary(summary: ContractSummary) -> str:
    return (
        "JSEC workflow shell contract: VERIFIED "
        f"(workflows={summary.workflows}, "
        f"run_blocks={summary.run_blocks}, "
        f"bash_run_blocks={summary.bash_run_blocks}, "
        f"heredocs={summary.heredocs}, "
        f"python_heredocs={summary.python_heredocs})"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=Path(".github/workflows"),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        summary = validate_workflows(args.workflows_dir)
    except WorkflowShellContractError as exc:
        print(f"JSEC workflow shell contract: FAILED: {exc}", file=sys.stderr)
        return 1
    print(_format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
