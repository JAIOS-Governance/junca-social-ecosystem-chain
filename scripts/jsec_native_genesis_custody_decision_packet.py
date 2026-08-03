#!/usr/bin/env python3
"""Emit the exact CEO decision packet for JSEC native Genesis custody."""

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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()

    try:
        packet = load_native_token_genesis_plan(
            args.plan
        ).custody_decision_packet()
    except NativeTokenGenesisError as exc:
        print(f"JSEC Genesis custody packet failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    if args.require_approved and packet["status"] != "approved":
        print("JSEC Genesis custody approval is still required", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
