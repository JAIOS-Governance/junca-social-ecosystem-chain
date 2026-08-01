#!/usr/bin/env python3
"""Emit the active JSEC Mainnet implementation cell governance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.mainnet_delivery_governance import (
    MainnetDeliveryGovernanceError,
    load_mainnet_delivery_cell,
)


DEFAULT_CELL = Path("config/jsec_mainnet_delivery_cell_v1.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell", type=Path, default=DEFAULT_CELL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        evidence = load_mainnet_delivery_cell(args.cell).as_evidence()
    except MainnetDeliveryGovernanceError as exc:
        print(f"JSEC Mainnet delivery governance failed: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
