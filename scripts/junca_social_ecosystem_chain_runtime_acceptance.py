#!/usr/bin/env python3
"""Generate fail-closed Public Testnet runtime acceptance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.runtime_acceptance import (
    RuntimeAcceptanceError,
    load_and_evaluate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-state", choices=("ACCEPTED", "BLOCKED"))
    args = parser.parse_args()
    try:
        result = load_and_evaluate(args.policy, args.observations)
    except RuntimeAcceptanceError as exc:
        print(f"runtime acceptance input rejected: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.as_evidence(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.expect_state and result.state != args.expect_state:
        print(f"expected {args.expect_state}, received {result.state}", file=sys.stderr)
        return 1
    print(json.dumps(result.as_evidence(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
