#!/usr/bin/env python3
"""Validate and emit deterministic cross-chain testnet route evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.interoperability import load_interoperability_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification", required=True)
    parser.add_argument("--output")
    parser.add_argument("--expect-state", choices=("BLOCKED", "TESTNET_READY"))
    args = parser.parse_args()
    manifest = load_interoperability_manifest(args.specification)
    payload = json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.expect_state and manifest.state != args.expect_state:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
