#!/usr/bin/env python3
"""Validate that a release child was called by the canonical live parent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
TOKEN_RE = re.compile(r"^[1-9][0-9]*-[1-9][0-9]*-[0-9a-f]{32}$")
INPUT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
PARENT_NAME = "JUNCA Hardened Immutable Candidate Release"
PARENT_PATH = (
    ".github/workflows/junca-hardened-immutable-candidate-release-v2.yml"
)
RUN_BINDING_SCHEMA = "junca-release-child-run-binding/v1"
EXECUTION_REF = "refs/heads/main"
CHILD_PATHS = (
    ".github/workflows/junca-validator-ami-build.yml",
    ".github/workflows/junca-runtime-release-evidence-collector-v2.yml",
    ".github/workflows/junca-runtime-release-manifest-gate.yml",
)
CHILD_ARTIFACT_KEYS = {
    CHILD_PATHS[0]: "ami",
    CHILD_PATHS[1]: "evidence",
    CHILD_PATHS[2]: "manifest",
}


class ProvenanceError(RuntimeError):
    """Canonical caller or source binding failed."""


def parse_inputs(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if not isinstance(item, str) or "=" not in item:
            raise ProvenanceError("child workflow input is invalid")
        key, value = item.split("=", 1)
        if (
            INPUT_KEY_RE.fullmatch(key) is None
            or key in parsed
            or "\r" in value
            or "\n" in value
        ):
            raise ProvenanceError("child workflow input is invalid")
        parsed[key] = value
    if not parsed:
        raise ProvenanceError("child workflow inputs are required")
    return parsed


def canonical_inputs_sha256(inputs: dict[str, str]) -> str:
    if (
        not isinstance(inputs, dict)
        or not inputs
        or any(
            not isinstance(key, str)
            or INPUT_KEY_RE.fullmatch(key) is None
            or not isinstance(value, str)
            or "\r" in value
            or "\n" in value
            for key, value in inputs.items()
        )
    ):
        raise ProvenanceError("canonical child workflow inputs are invalid")
    encoded = json.dumps(
        inputs,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_binding_artifact_name(
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    workflow_path: str,
    child_run_id: str,
    child_run_attempt: str,
) -> str:
    key = CHILD_ARTIFACT_KEYS.get(workflow_path)
    if (
        RUN_ID_RE.fullmatch(orchestrator_run_id) is None
        or RUN_ID_RE.fullmatch(orchestrator_run_attempt) is None
        or RUN_ID_RE.fullmatch(child_run_id) is None
        or child_run_attempt != "1"
        or key is None
    ):
        raise ProvenanceError("child run binding artifact identity is invalid")
    return (
        "junca-release-child-run-binding-"
        f"{orchestrator_run_id}-{orchestrator_run_attempt}-"
        f"{key}-{child_run_id}-{child_run_attempt}"
    )


def build_run_binding(
    *,
    repository: str,
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    source_commit: str,
    workflow_path: str,
    dispatch_token: str,
    child_run_id: str,
    child_run_attempt: str,
    workflow_inputs: dict[str, str],
) -> dict[str, Any]:
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise ProvenanceError("child run binding repository is invalid")
    if (
        RUN_ID_RE.fullmatch(orchestrator_run_id) is None
        or RUN_ID_RE.fullmatch(orchestrator_run_attempt) is None
        or RUN_ID_RE.fullmatch(child_run_id) is None
        or child_run_attempt != "1"
    ):
        raise ProvenanceError("child run binding run identity is invalid")
    if SHA_RE.fullmatch(source_commit) is None:
        raise ProvenanceError("child run binding source commit is invalid")
    if workflow_path not in CHILD_PATHS:
        raise ProvenanceError("child run binding workflow path is invalid")
    if (
        TOKEN_RE.fullmatch(dispatch_token) is None
        or not dispatch_token.startswith(
            f"{orchestrator_run_id}-{orchestrator_run_attempt}-"
        )
    ):
        raise ProvenanceError("child run binding token is invalid")
    if workflow_inputs.get("source_commit") != source_commit:
        raise ProvenanceError("child run binding source input is not exact")
    inputs_sha256 = canonical_inputs_sha256(workflow_inputs)
    payload: dict[str, Any] = {
        "schema_version": RUN_BINDING_SCHEMA,
        "repository": repository,
        "orchestrator": {
            "run_id": orchestrator_run_id,
            "run_attempt": orchestrator_run_attempt,
            "workflow_name": PARENT_NAME,
            "workflow_path": PARENT_PATH,
        },
        "source_commit": source_commit,
        "candidate_ref": f"release-candidate/{source_commit}",
        "child": {
            "run_id": child_run_id,
            "run_attempt": child_run_attempt,
            "workflow_path": workflow_path,
            "workflow_ref":
                f"{repository}/{workflow_path}@{EXECUTION_REF}",
            "execution_ref": EXECUTION_REF,
            "dispatch_token": dispatch_token,
            "inputs_sha256": inputs_sha256,
        },
    }
    return {
        **payload,
        "binding_sha256": canonical_json_sha256(payload),
    }


def write_run_binding_artifact(
    output_dir: Path,
    binding: dict[str, Any],
) -> None:
    if output_dir.exists():
        raise ProvenanceError("child run binding output already exists")
    output_dir.mkdir(parents=True)
    binding_path = output_dir / "run-binding.json"
    binding_path.write_text(
        json.dumps(
            binding,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_sha256 = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    (output_dir / "SHA256SUMS").write_text(
        f"{artifact_sha256}  run-binding.json\n",
        encoding="utf-8",
    )


def attestation_artifact_name(
    run_id: str,
    run_attempt: str,
    workflow_path: str,
) -> str:
    key = CHILD_ARTIFACT_KEYS.get(workflow_path)
    if (
        RUN_ID_RE.fullmatch(run_id) is None
        or RUN_ID_RE.fullmatch(run_attempt) is None
        or key is None
    ):
        raise ProvenanceError("dispatch attestation artifact identity is invalid")
    return f"junca-release-dispatch-attestation-{run_id}-{run_attempt}-{key}"


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


def fetch_attestation(
    repository: str,
    run_id: str,
    run_attempt: str,
    workflow_path: str,
) -> dict[str, Any]:
    artifact_name = attestation_artifact_name(
        run_id,
        run_attempt,
        workflow_path,
    )
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        result = subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                artifact_name,
                "--dir",
                directory,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise ProvenanceError(
                "cannot download parent dispatch attestation: "
                f"{result.stderr.strip()}"
            )
        entries = sorted(target.iterdir(), key=lambda path: path.name)
        if (
            [path.name for path in entries]
            != ["SHA256SUMS", "dispatch-attestation.json"]
            or any(path.is_symlink() or not path.is_file() for path in entries)
        ):
            raise ProvenanceError(
                "parent dispatch attestation artifact is not exact"
            )
        evidence_path = target / "dispatch-attestation.json"
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        expected_checksum = (
            f"{digest}  dispatch-attestation.json\n"
        )
        if (target / "SHA256SUMS").read_text(
            encoding="utf-8"
        ) != expected_checksum:
            raise ProvenanceError(
                "parent dispatch attestation checksum mismatch"
            )
        try:
            value = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProvenanceError(
                "parent dispatch attestation JSON is invalid"
            ) from exc
        if not isinstance(value, dict):
            raise ProvenanceError(
                "parent dispatch attestation payload is invalid"
            )
        return value


def _load_run_binding_artifact(target: Path) -> dict[str, Any]:
    entries = sorted(target.iterdir(), key=lambda path: path.name)
    if (
        [path.name for path in entries]
        != ["SHA256SUMS", "run-binding.json"]
        or any(path.is_symlink() or not path.is_file() for path in entries)
    ):
        raise ProvenanceError("parent child run binding artifact is not exact")
    binding_path = target / "run-binding.json"
    artifact_sha256 = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    if (target / "SHA256SUMS").read_text(encoding="utf-8") != (
        f"{artifact_sha256}  run-binding.json\n"
    ):
        raise ProvenanceError("parent child run binding checksum mismatch")
    try:
        value = json.loads(binding_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvenanceError(
            "parent child run binding JSON is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise ProvenanceError("parent child run binding payload is invalid")
    return value


def fetch_run_binding(
    repository: str,
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    workflow_path: str,
    child_run_id: str,
    child_run_attempt: str,
    *,
    attempts: int = 45,
    sleep_seconds: int = 2,
) -> dict[str, Any]:
    if attempts < 1 or sleep_seconds < 1:
        raise ProvenanceError("child run binding poll bounds are invalid")
    artifact_name = run_binding_artifact_name(
        orchestrator_run_id,
        orchestrator_run_attempt,
        workflow_path,
        child_run_id,
        child_run_attempt,
    )
    last_detail = ""
    for attempt in range(1, attempts + 1):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    orchestrator_run_id,
                    "--repo",
                    repository,
                    "--name",
                    artifact_name,
                    "--dir",
                    directory,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return _load_run_binding_artifact(Path(directory))
            last_detail = (
                result.stderr.strip() or result.stdout.strip()
            )[:512]
        if attempt < attempts:
            time.sleep(sleep_seconds)
    raise ProvenanceError(
        "exact child run binding was not published within the bounded poll: "
        f"{last_detail}"
    )


def validate(
    run: dict[str, Any],
    attestation: dict[str, Any],
    run_binding: dict[str, Any],
    *,
    repository: str,
    source_commit: str,
    dispatch_token: str,
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    github_ref: str,
    github_sha: str,
    github_run_id: str,
    github_run_attempt: str,
    github_workflow_ref: str,
    workflow_path: str,
    workflow_inputs: dict[str, str],
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
    if workflow_path not in CHILD_PATHS:
        raise ProvenanceError("child workflow path is invalid")
    if (
        RUN_ID_RE.fullmatch(github_run_id) is None
        or github_run_attempt != "1"
    ):
        raise ProvenanceError("child run identity is invalid")
    if workflow_inputs.get("source_commit") != source_commit:
        raise ProvenanceError("child workflow source input is not exact")
    actual_inputs_sha256 = canonical_inputs_sha256(workflow_inputs)
    expected_ref = EXECUTION_REF
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
        and run.get("event") == "workflow_dispatch"
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
    if set(attestation) != {
        "schema_version",
        "orchestrator_run_id",
        "orchestrator_run_attempt",
        "source_commit",
        "candidate_ref",
        "dispatch",
    }:
        raise ProvenanceError("parent dispatch attestation keys are not exact")
    dispatch = attestation.get("dispatch")
    if (
        attestation.get("schema_version")
        != "junca-release-dispatch-attestation/v2"
        or attestation.get("orchestrator_run_id") != orchestrator_run_id
        or attestation.get("orchestrator_run_attempt")
        != orchestrator_run_attempt
        or attestation.get("source_commit") != source_commit
        or attestation.get("candidate_ref")
        != f"release-candidate/{source_commit}"
        or not isinstance(dispatch, dict)
    ):
        raise ProvenanceError("parent dispatch attestation binding rejected")
    if (
        set(dispatch)
        != {
            "workflow_path",
            "dispatch_token",
            "inputs",
            "inputs_sha256",
        }
        or dispatch.get("workflow_path") != workflow_path
        or dispatch.get("dispatch_token") != dispatch_token
        or dispatch.get("inputs") != workflow_inputs
        or dispatch.get("inputs_sha256") != actual_inputs_sha256
    ):
        raise ProvenanceError(
            "dispatch token or exact child inputs were not issued by the parent"
        )
    expected_run_binding = build_run_binding(
        repository=repository,
        orchestrator_run_id=orchestrator_run_id,
        orchestrator_run_attempt=orchestrator_run_attempt,
        source_commit=source_commit,
        workflow_path=workflow_path,
        dispatch_token=dispatch_token,
        child_run_id=github_run_id,
        child_run_attempt=github_run_attempt,
        workflow_inputs=workflow_inputs,
    )
    if (
        run_binding != expected_run_binding
        or not SHA256_RE.fullmatch(
            str(run_binding.get("binding_sha256", ""))
        )
        or github_workflow_ref
        != f"{repository}/{workflow_path}@{EXECUTION_REF}"
    ):
        raise ProvenanceError(
            "exact child run binding rejected before side effects"
        )


def main() -> int:
    value = argparse.ArgumentParser()
    value.add_argument("--source-commit", required=True)
    value.add_argument("--dispatch-token", required=True)
    value.add_argument("--orchestrator-run-id", required=True)
    value.add_argument("--orchestrator-run-attempt", required=True)
    value.add_argument("--workflow-path", required=True)
    value.add_argument("--input", action="append", default=[])
    args = value.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    github_ref = os.environ.get("GITHUB_REF", "")
    github_sha = os.environ.get("GITHUB_SHA", "")
    github_run_id = os.environ.get("GITHUB_RUN_ID", "")
    github_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    github_workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    if not os.environ.get("GH_TOKEN"):
        print("release provenance failed: GH_TOKEN is required", file=sys.stderr)
        return 1
    try:
        attestation = fetch_attestation(
            repository,
            args.orchestrator_run_id,
            args.orchestrator_run_attempt,
            args.workflow_path,
        )
        workflow_inputs = parse_inputs(args.input)
        run_binding = fetch_run_binding(
            repository,
            args.orchestrator_run_id,
            args.orchestrator_run_attempt,
            args.workflow_path,
            github_run_id,
            github_run_attempt,
        )
        # Read the parent after the bounded binding poll so its in-progress
        # status is fresh at the final pre-side-effect authorization boundary.
        run = fetch_run(repository, args.orchestrator_run_id)
        validate(
            run,
            attestation,
            run_binding,
            repository=repository,
            source_commit=args.source_commit,
            dispatch_token=args.dispatch_token,
            orchestrator_run_id=args.orchestrator_run_id,
            orchestrator_run_attempt=args.orchestrator_run_attempt,
            github_ref=github_ref,
            github_sha=github_sha,
            github_run_id=github_run_id,
            github_run_attempt=github_run_attempt,
            github_workflow_ref=github_workflow_ref,
            workflow_path=args.workflow_path,
            workflow_inputs=workflow_inputs,
        )
    except ProvenanceError as exc:
        print(f"release provenance failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
