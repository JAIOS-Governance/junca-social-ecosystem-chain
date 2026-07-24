#!/usr/bin/env python3
"""Build deterministic partner token or NFT issuance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.asset_issuance import (
    AssetIssuanceError,
    load_issuance_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-state", choices=("TESTNET_READY", "BLOCKED"))
    args = parser.parse_args()
    try:
        manifest = load_issuance_manifest(args.specification)
    except AssetIssuanceError as exc:
        print(f"asset issuance specification rejected: {exc}", file=sys.stderr)
        return 2
    evidence = manifest.as_evidence()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.expect_state and manifest.state != args.expect_state:
        print(f"expected {args.expect_state}, received {manifest.state}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
