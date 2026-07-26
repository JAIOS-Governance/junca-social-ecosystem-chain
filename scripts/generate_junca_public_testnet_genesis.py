#!/usr/bin/env python3
"""Generate the canonical zero-allocation JUNCA public-testnet genesis."""

from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.validator_node import build_genesis, canonical_json

parser = ArgumentParser()
parser.add_argument("--chain-id", type=int, default=20260723)
parser.add_argument("--validator", action="append", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(canonical_json(build_genesis(
    chain_id=args.chain_id,
    validators=args.validator,
)))
