#!/usr/bin/env python3
"""Dispatch one release child workflow on an immutable candidate branch.

The command writes only the successful child run ID to stdout. Diagnostics are
written to stderr so callers may safely use command substitution.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import time
import uuid
from typing import Any, Iterable


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REF_RE = re.compile(r"^release-candidate/[0-9a-f]{40}$")
WORKFLOW_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml$")
INPUT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")


class DispatchError(RuntimeError):
    """Fail-closed release orchestration error."""


class GitHub:
    def __init__(self, repository: str) -> None:
        self.repository = repository

    def api(
        self,
        endpoint: str,
        *arguments: str,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["gh", "api", endpoint, *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode and not allow_failure:
            detail = result.stderr.strip() or result.stdout.strip()
            raise DispatchError(f"GitHub API failed for {endpoint}: {detail}")
        return result

    def json(self, endpoint: str, *arguments: str) -> Any:
        result = self.api(endpoint, *arguments)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DispatchError(
                f"GitHub API returned invalid JSON for {endpoint}"
            ) from exc


def require_environment() -> tuple[str, str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    parent_run_id = os.environ.get("GITHUB_RUN_ID", "")
    parent_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise DispatchError("GITHUB_REPOSITORY is invalid")
    if not RUN_ID_RE.fullmatch(parent_run_id):
        raise DispatchError("GITHUB_RUN_ID is invalid")
    if not RUN_ID_RE.fullmatch(parent_run_attempt):
        raise DispatchError("GITHUB_RUN_ATTEMPT is invalid")
    if not os.environ.get("GH_TOKEN"):
        raise DispatchError("GH_TOKEN is required")
    return repository, parent_run_id, parent_run_attempt


def parse_inputs(values: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise DispatchError(f"workflow input lacks '=': {item}")
        key, value = item.split("=", 1)
        if not INPUT_KEY_RE.fullmatch(key):
            raise DispatchError(f"workflow input key is invalid: {key}")
        if key in parsed:
            raise DispatchError(f"workflow input is duplicated: {key}")
        if "\r" in value or "\n" in value:
            raise DispatchError(f"workflow input contains a newline: {key}")
        parsed[key] = value
    return parsed


def validate_arguments(args: argparse.Namespace) -> None:
    if not args.workflow_name.strip():
        raise DispatchError("workflow name is required")
    if not WORKFLOW_RE.fullmatch(args.workflow_path):
        raise DispatchError("workflow path is invalid")
    if not SHA_RE.fullmatch(args.expected_head):
        raise DispatchError("expected head is invalid")
    if not REF_RE.fullmatch(args.dispatch_ref):
        raise DispatchError("dispatch ref is invalid")
    if args.dispatch_ref != f"release-candidate/{args.expected_head}":
        raise DispatchError("dispatch ref is not bound to expected head")
    if args.attempts < 1 or args.sleep_seconds < 1:
        raise DispatchError("attempts and sleep seconds must be positive")


def ref_endpoint(repository: str, dispatch_ref: str) -> str:
    return f"repos/{repository}/git/ref/heads/{dispatch_ref}"


def resolve_candidate_ref(
    github: GitHub,
    dispatch_ref: str,
    *,
    allow_missing: bool = False,
) -> str | None:
    result = github.api(
        ref_endpoint(github.repository, dispatch_ref),
        allow_failure=allow_missing,
    )
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
        sha = value["object"]["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DispatchError("candidate ref response is invalid") from exc
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise DispatchError("candidate ref resolved to an invalid SHA")
    return sha


def ensure_candidate_ref(
    github: GitHub, dispatch_ref: str, expected_head: str
) -> None:
    actual = resolve_candidate_ref(github, dispatch_ref, allow_missing=True)
    if actual is None:
        created = github.api(
            f"repos/{github.repository}/git/refs",
            "--method",
            "POST",
            "-f",
            f"ref=refs/heads/{dispatch_ref}",
            "-f",
            f"sha={expected_head}",
            allow_failure=True,
        )
        if created.returncode:
            # A concurrent canonical parent may have created the same ref.
            actual = resolve_candidate_ref(github, dispatch_ref)
        else:
            actual = resolve_candidate_ref(github, dispatch_ref)
    if actual != expected_head:
        raise DispatchError(
            "candidate ref mismatch: "
            f"ref={dispatch_ref} expected={expected_head} actual={actual}"
        )


def select_workflow(
    github: GitHub, workflow_name: str, workflow_path: str
) -> dict[str, Any]:
    value = github.json(
        f"repos/{github.repository}/actions/workflows?per_page=100"
    )
    workflows = value.get("workflows", []) if isinstance(value, dict) else []
    matches = [
        item
        for item in workflows
        if item.get("name") == workflow_name
        and item.get("path") == workflow_path
        and item.get("state") == "active"
    ]
    if len(matches) != 1:
        raise DispatchError(
            f"workflow identity mismatch: name={workflow_name} "
            f"path={workflow_path} matches={len(matches)}"
        )
    return matches[0]


def discover_run(
    github: GitHub,
    workflow_id: int,
    *,
    workflow_name: str,
    workflow_path: str,
    dispatch_ref: str,
    expected_head: str,
    display_title: str,
    dispatched_at: str,
) -> dict[str, Any] | None:
    value = github.json(
        f"repos/{github.repository}/actions/workflows/{workflow_id}/runs"
        "?event=workflow_dispatch&per_page=100"
    )
    runs = value.get("workflow_runs", []) if isinstance(value, dict) else []
    matches = [
        run
        for run in runs
        if run.get("created_at", "") >= dispatched_at
        and run.get("name") == workflow_name
        and run.get("path") == workflow_path
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == dispatch_ref
        and run.get("head_sha") == expected_head
        and run.get("display_title") == display_title
    ]
    if len(matches) > 1:
        ids = [run.get("id") for run in matches]
        raise DispatchError(
            f"dispatch correlation is ambiguous: token={display_title} runs={ids}"
        )
    return matches[0] if matches else None


def verify_completed_run(
    run: dict[str, Any],
    *,
    repository: str,
    workflow_name: str,
    workflow_path: str,
    dispatch_ref: str,
    expected_head: str,
    display_title: str,
) -> int:
    observed_repository = (run.get("repository") or {}).get("full_name")
    observed_head_repository = (run.get("head_repository") or {}).get(
        "full_name"
    )
    run_id = str(run.get("id", ""))
    valid = (
        RUN_ID_RE.fullmatch(run_id)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("name") == workflow_name
        and run.get("path") == workflow_path
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == dispatch_ref
        and run.get("head_sha") == expected_head
        and run.get("display_title") == display_title
        and observed_repository == repository
        and observed_head_repository == repository
    )
    if not valid:
        raise DispatchError(
            "child workflow rejected: "
            f"run_id={run_id} status={run.get('status')} "
            f"conclusion={run.get('conclusion')} "
            f"ref={run.get('head_branch')} sha={run.get('head_sha')}"
        )
    return int(run_id)


def execute(args: argparse.Namespace) -> int:
    validate_arguments(args)
    repository, parent_run_id, parent_run_attempt = require_environment()
    github = GitHub(repository)
    inputs = parse_inputs(args.input)
    reserved = {
        "dispatch_token",
        "orchestrator_run_id",
        "orchestrator_run_attempt",
    }
    collision = reserved.intersection(inputs)
    if collision:
        raise DispatchError(
            f"reserved workflow input supplied by caller: {sorted(collision)}"
        )

    ensure_candidate_ref(github, args.dispatch_ref, args.expected_head)
    workflow = select_workflow(
        github, args.workflow_name, args.workflow_path
    )
    workflow_id = workflow.get("id")
    if not isinstance(workflow_id, int) or workflow_id < 1:
        raise DispatchError("workflow ID is invalid")

    token = (
        f"{parent_run_id}-{parent_run_attempt}-"
        f"{uuid.uuid4().hex}"
    )
    display_title = f"JSEC dispatch {token}"
    inputs.update(
        {
            "dispatch_token": token,
            "orchestrator_run_id": parent_run_id,
            "orchestrator_run_attempt": parent_run_attempt,
        }
    )
    dispatched_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    arguments = [
        "--method",
        "POST",
        f"repos/{repository}/actions/workflows/{workflow_id}/dispatches",
        "-f",
        f"ref={args.dispatch_ref}",
    ]
    for key, value in sorted(inputs.items()):
        arguments.extend(("-f", f"inputs[{key}]={value}"))
    github.api(arguments.pop(2), *arguments)

    run: dict[str, Any] | None = None
    for attempt in range(1, 91):
        ensure_candidate_ref(github, args.dispatch_ref, args.expected_head)
        run = discover_run(
            github,
            workflow_id,
            workflow_name=args.workflow_name,
            workflow_path=args.workflow_path,
            dispatch_ref=args.dispatch_ref,
            expected_head=args.expected_head,
            display_title=display_title,
            dispatched_at=dispatched_at,
        )
        if run is not None:
            break
        if attempt == 90:
            raise DispatchError(
                f"child run not found: workflow={args.workflow_name} "
                f"ref={args.dispatch_ref} sha={args.expected_head}"
            )
        time.sleep(2)
    assert run is not None
    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id < 1:
        raise DispatchError("discovered child run ID is invalid")

    for attempt in range(1, args.attempts + 1):
        run = github.json(f"repos/{repository}/actions/runs/{run_id}")
        if run.get("status") == "completed":
            break
        if attempt == args.attempts:
            raise DispatchError(
                f"child workflow timed out: run_id={run_id} "
                f"status={run.get('status')}"
            )
        time.sleep(args.sleep_seconds)

    ensure_candidate_ref(github, args.dispatch_ref, args.expected_head)
    return verify_completed_run(
        run,
        repository=repository,
        workflow_name=args.workflow_name,
        workflow_path=args.workflow_path,
        dispatch_ref=args.dispatch_ref,
        expected_head=args.expected_head,
        display_title=display_title,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--workflow-name", required=True)
    value.add_argument("--workflow-path", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--dispatch-ref", required=True)
    value.add_argument("--attempts", type=int, default=240)
    value.add_argument("--sleep-seconds", type=int, default=15)
    value.add_argument("--input", action="append", default=[])
    return value


def main() -> int:
    try:
        run_id = execute(parser().parse_args())
    except DispatchError as exc:
        print(f"release dispatch failed: {exc}", file=sys.stderr)
        return 1
    print(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
