#!/usr/bin/env python3
"""Validate and emit public-preview testnet evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.public_testnet import (
    PublicTestnetError,
    load_public_testnet_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config/junca_social_ecosystem_chain_public_testnet.json"),
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        evidence = load_public_testnet_plan(args.config).as_evidence()
    except PublicTestnetError as exc:
        print(f"public-testnet validation failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
