#!/usr/bin/env python3
"""Validate that a release child was called by the canonical live parent."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
TOKEN_RE = re.compile(r"^[1-9][0-9]*-[1-9][0-9]*-[0-9a-f]{32}$")
PARENT_NAME = "JUNCA Hardened Immutable Candidate Release"
PARENT_PATH = (
    ".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"
)


class ProvenanceError(RuntimeError):
    """Canonical caller or source binding failed."""


def fetch_run(repository: str, run_id: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/actions/runs/{run_id}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ProvenanceError(
            f"cannot read orchestrator run {run_id}: {result.stderr.strip()}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProvenanceError("orchestrator run JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ProvenanceError("orchestrator run payload is invalid")
    return value


def validate(
    run: dict[str, Any],
    *,
    repository: str,
    source_commit: str,
    dispatch_token: str,
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    github_ref: str,
    github_sha: str,
) -> None:
    if not SHA_RE.fullmatch(source_commit):
        raise ProvenanceError("source commit is invalid")
    if not RUN_ID_RE.fullmatch(orchestrator_run_id):
        raise ProvenanceError("orchestrator run ID is invalid")
    if not RUN_ID_RE.fullmatch(orchestrator_run_attempt):
        raise ProvenanceError("orchestrator run attempt is invalid")
    if not TOKEN_RE.fullmatch(dispatch_token):
        raise ProvenanceError("dispatch token is invalid")
    if not dispatch_token.startswith(
        f"{orchestrator_run_id}-{orchestrator_run_attempt}-"
    ):
        raise ProvenanceError("dispatch token is not parent-bound")
    expected_ref = f"refs/heads/release-candidate/{source_commit}"
    if github_ref != expected_ref or github_sha != source_commit:
        raise ProvenanceError(
            "child execution ref mismatch: "
            f"ref={github_ref} sha={github_sha} expected={expected_ref}"
        )
    parent_repository = (run.get("repository") or {}).get("full_name")
    parent_head_repository = (run.get("head_repository") or {}).get(
        "full_name"
    )
    if not (
        str(run.get("id")) == orchestrator_run_id
        and str(run.get("run_attempt")) == orchestrator_run_attempt
        and run.get("name") == PARENT_NAME
        and run.get("path") == PARENT_PATH
        and run.get("event") == "workflow_run"
        and run.get("status") == "in_progress"
        and run.get("head_branch") == "main"
        and run.get("head_sha") == source_commit
        and parent_repository == repository
        and parent_head_repository == repository
    ):
        raise ProvenanceError(
            "canonical orchestrator binding rejected: "
            f"run={orchestrator_run_id} status={run.get('status')} "
            f"path={run.get('path')} sha={run.get('head_sha')}"
        )


def main() -> int:
    value = argparse.ArgumentParser()
    value.add_argument("--source-commit", required=True)
    value.add_argument("--dispatch-token", required=True)
    value.add_argument("--orchestrator-run-id", required=True)
    value.add_argument("--orchestrator-run-attempt", required=True)
    args = value.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    github_ref = os.environ.get("GITHUB_REF", "")
    github_sha = os.environ.get("GITHUB_SHA", "")
    if not os.environ.get("GH_TOKEN"):
        print("release provenance failed: GH_TOKEN is required", file=sys.stderr)
        return 1
    try:
        run = fetch_run(repository, args.orchestrator_run_id)
        validate(
            run,
            repository=repository,
            source_commit=args.source_commit,
            dispatch_token=args.dispatch_token,
            orchestrator_run_id=args.orchestrator_run_id,
            orchestrator_run_attempt=args.orchestrator_run_attempt,
            github_ref=github_ref,
            github_sha=github_sha,
        )
    except ProvenanceError as exc:
        print(f"release provenance failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
