#!/usr/bin/env python3
"""Validate and emit redacted JUNCA Social Ecosystem Chain release-policy evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import ChainReleasePolicyError, load_release_policy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        default=str(ROOT / "config/junca_social_ecosystem_chain_release_policy.json"),
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        evidence = load_release_policy(args.policy).as_evidence()
    except ChainReleasePolicyError as exc:
        print(f"release policy rejected: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(target)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
