#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.bridge_deployment import load_bridge_deployment_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-state", default="BLOCKED")
    args = parser.parse_args()
    manifest = load_bridge_deployment_manifest(args.specification)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n")
    return 0 if manifest.state == args.expect_state else 2


if __name__ == "__main__":
    raise SystemExit(main())
