#!/usr/bin/env python3
"""Create one exact, input-bound release-child dispatch attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.junca_release_child_provenance import (
    CHILD_PATHS,
    ProvenanceError,
    RUN_ID_RE,
    SHA_RE,
    TOKEN_RE,
    canonical_inputs_sha256,
    parse_inputs,
)


def build_attestation(
    *,
    orchestrator_run_id: str,
    orchestrator_run_attempt: str,
    source_commit: str,
    workflow_path: str,
    dispatch_token: str,
    workflow_inputs: dict[str, str],
) -> dict[str, object]:
    if (
        RUN_ID_RE.fullmatch(orchestrator_run_id) is None
        or RUN_ID_RE.fullmatch(orchestrator_run_attempt) is None
        or SHA_RE.fullmatch(source_commit) is None
        or workflow_path not in CHILD_PATHS
        or TOKEN_RE.fullmatch(dispatch_token) is None
        or not dispatch_token.startswith(
            f"{orchestrator_run_id}-{orchestrator_run_attempt}-"
        )
        or workflow_inputs.get("source_commit") != source_commit
    ):
        raise ProvenanceError("dispatch attestation binding is invalid")
    return {
        "schema_version": "junca-release-dispatch-attestation/v2",
        "orchestrator_run_id": orchestrator_run_id,
        "orchestrator_run_attempt": orchestrator_run_attempt,
        "source_commit": source_commit,
        "candidate_ref": f"release-candidate/{source_commit}",
        "dispatch": {
            "workflow_path": workflow_path,
            "dispatch_token": dispatch_token,
            "inputs": workflow_inputs,
            "inputs_sha256": canonical_inputs_sha256(workflow_inputs),
        },
    }


def write_attestation(output_dir: Path, value: dict[str, object]) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ProvenanceError("dispatch attestation output directory is not empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = output_dir / "dispatch-attestation.json"
    evidence.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    (output_dir / "SHA256SUMS").write_text(
        f"{digest}  dispatch-attestation.json\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--dispatch-token", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input", action="append", default=[])
    args = parser.parse_args()
    try:
        workflow_inputs = parse_inputs(args.input)
        value = build_attestation(
            orchestrator_run_id=os.environ.get("GITHUB_RUN_ID", ""),
            orchestrator_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            source_commit=args.source_commit,
            workflow_path=args.workflow_path,
            dispatch_token=args.dispatch_token,
            workflow_inputs=workflow_inputs,
        )
        write_attestation(Path(args.output_dir), value)
    except (OSError, ProvenanceError) as exc:
        print(f"dispatch attestation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
