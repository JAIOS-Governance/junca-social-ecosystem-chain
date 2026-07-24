#!/usr/bin/env python3
"""Validate the legacy build contract and sovereign testnet bootstrap plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import (
    ChainArchitectureError,
    ChainBootstrapError,
    load_build_contract,
    load_scale_profile,
    load_testnet_bootstrap,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-contract",
        default="config/junca_social_ecosystem_chain_build_manifest.json",
    )
    parser.add_argument(
        "--testnet-bootstrap",
        default="config/junca_social_ecosystem_chain_testnet_bootstrap.json",
    )
    parser.add_argument(
        "--scale-profile",
        default="config/junca_social_ecosystem_chain_scalability_profile.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        build = load_build_contract(args.build_contract)
        bootstrap = load_testnet_bootstrap(args.testnet_bootstrap)
        scale = load_scale_profile(args.scale_profile)
    except (ChainBootstrapError, ChainArchitectureError) as exc:
        print(f"bootstrap validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "build": build.as_evidence(),
                "scale": scale.as_evidence(),
                "testnet": bootstrap.as_evidence(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
