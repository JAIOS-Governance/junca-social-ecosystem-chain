#!/usr/bin/env python3
"""Independently verify a compiled JSEC native Genesis candidate."""

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
    load_native_genesis_candidate,
    load_native_token_genesis_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        source_plan = load_native_token_genesis_plan(args.plan)
        evidence = load_native_genesis_candidate(
            args.candidate,
            source_plan=source_plan,
        ).as_evidence()
    except NativeTokenGenesisError as exc:
        print(f"JSEC native Genesis candidate verification failed: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
