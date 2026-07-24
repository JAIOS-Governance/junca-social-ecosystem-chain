#!/usr/bin/env python3
"""Emit canonical repository governance readiness evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.repository_governance import (
    load_repository_boundary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--specification",
        default="governance/repository-boundary.json",
    )
    parser.add_argument("--output")
    parser.add_argument("--expect-state", choices=("BLOCKED", "READY"))
    args = parser.parse_args()
    evidence = load_repository_boundary(args.specification, ROOT)
    if args.expect_state and evidence["state"] != args.expect_state:
        raise SystemExit(
            f"expected {args.expect_state}, received {evidence['state']}"
        )
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
