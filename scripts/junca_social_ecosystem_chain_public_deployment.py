#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.public_deployment import load_public_deployment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-state", choices=("BLOCKED", "ACCEPTED"))
    args = parser.parse_args()
    evidence = load_public_deployment(args.specification)
    if args.expect_state and evidence.state != args.expect_state:
        raise SystemExit(f"expected {args.expect_state}, received {evidence.state}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence.as_dict(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
