#!/usr/bin/env python3
"""Produce fail-closed validator artifact or verified AMI handoff evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.validator_artifacts import (
    ValidatorArtifactError,
    build_validator_artifact_handoff,
    pending_validator_artifact_handoff,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", action="store_true")
    parser.add_argument("--specification")
    parser.add_argument("--node-binary")
    parser.add_argument("--genesis")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.pending:
            if any((args.specification, args.node_binary, args.genesis)):
                raise ValidatorArtifactError(
                    "--pending cannot be mixed with immutable artifact inputs"
                )
            result = pending_validator_artifact_handoff()
        else:
            if not all((args.specification, args.node_binary, args.genesis)):
                raise ValidatorArtifactError(
                    "specification, node-binary and genesis are required"
                )
            specification = json.loads(
                Path(args.specification).read_text(encoding="utf-8")
            )
            result = build_validator_artifact_handoff(
                specification,
                node_binary=Path(args.node_binary),
                genesis=Path(args.genesis),
            )
    except (OSError, json.JSONDecodeError, ValidatorArtifactError) as exc:
        print(f"validator artifact handoff rejected: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
