#!/usr/bin/env python3
"""Generate deterministic public-testnet soak acceptance evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.soak_acceptance import write_soak_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evidence = write_soak_evidence(args.output)
    print(evidence["evidence_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
