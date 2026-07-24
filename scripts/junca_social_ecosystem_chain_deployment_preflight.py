#!/usr/bin/env python3
"""Validate and emit redacted public-testnet deployment preflight evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.deployment_preflight import (
    DeploymentPreflightError,
    load_deployment_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config/junca_social_ecosystem_chain_deployment_preflight.json"),
    )
    parser.add_argument("--expect-state", choices=("blocked", "ready"), default="blocked")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        preflight = load_deployment_preflight(args.config)
    except DeploymentPreflightError as exc:
        print(f"deployment preflight rejected: {exc}", file=sys.stderr)
        return 2
    if preflight.state != args.expect_state:
        print(
            f"deployment preflight state {preflight.state!r} does not match {args.expect_state!r}",
            file=sys.stderr,
        )
        return 3
    rendered = json.dumps(preflight.as_evidence(), indent=2, sort_keys=True) + "\n"
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
