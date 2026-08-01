#!/usr/bin/env python3
"""Emit JSEC native-token Genesis schedule evidence and fail on deadline drift."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.native_token_genesis import (
    NativeTokenGenesisError,
    load_native_token_genesis_plan,
)


DEFAULT_PLAN = Path("config/jsec_native_token_genesis_plan_v1.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    as_of = args.as_of or datetime.now(timezone.utc).date()
    try:
        plan = load_native_token_genesis_plan(args.plan)
        evidence = plan.as_evidence(as_of)
        plan.assert_on_track(as_of)
    except NativeTokenGenesisError as exc:
        print(f"JSEC native Genesis schedule gate failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
