#!/usr/bin/env python3
"""Compile an approved JSEC native-token plan into a Genesis candidate."""

from __future__ import annotations

import argparse
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        candidate = load_native_token_genesis_plan(args.plan).genesis_candidate()
    except NativeTokenGenesisError as exc:
        print(f"JSEC native Genesis candidate blocked: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(candidate, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
