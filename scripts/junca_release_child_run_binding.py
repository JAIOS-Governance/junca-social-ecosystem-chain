#!/usr/bin/env python3
"""Emit the exact release-child run binding discovered by the parent."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

if __package__:
    from .junca_release_child_provenance import (
        ProvenanceError,
        build_run_binding,
        parse_inputs,
        write_run_binding_artifact,
    )
else:
    from junca_release_child_provenance import (
        ProvenanceError,
        build_run_binding,
        parse_inputs,
        write_run_binding_artifact,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--dispatch-token", required=True)
    parser.add_argument("--child-run-id", required=True)
    parser.add_argument("--child-run-attempt", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input", action="append", default=[])
    args = parser.parse_args()
    try:
        binding = build_run_binding(
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            orchestrator_run_id=os.environ.get("GITHUB_RUN_ID", ""),
            orchestrator_run_attempt=os.environ.get(
                "GITHUB_RUN_ATTEMPT",
                "",
            ),
            source_commit=args.source_commit,
            workflow_path=args.workflow_path,
            dispatch_token=args.dispatch_token,
            child_run_id=args.child_run_id,
            child_run_attempt=args.child_run_attempt,
            workflow_inputs=parse_inputs(args.input),
        )
        write_run_binding_artifact(args.output_dir, binding)
    except (OSError, ProvenanceError, UnicodeError) as exc:
        print(f"child run binding failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
