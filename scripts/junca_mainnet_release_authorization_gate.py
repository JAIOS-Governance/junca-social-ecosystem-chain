#!/usr/bin/env python3
"""Validate Mainnet release authorization evidence without activating Mainnet."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import (
    MainnetReleaseAuthorizationError,
    validate_mainnet_release_authorization,
)


def _load(path: str, field: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetReleaseAuthorizationError(f"unable to load {field}: {path}") from exc


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not value.endswith("Z"):
        raise MainnetReleaseAuthorizationError("--now must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise MainnetReleaseAuthorizationError("--now is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise MainnetReleaseAuthorizationError("--now must use UTC")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--expected-binding", required=True)
    parser.add_argument("--approval-policy", required=True)
    parser.add_argument("--consumed-ledger", required=True)
    parser.add_argument("--now", help="RFC3339 UTC test/readback time; defaults to current UTC")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        now = _parse_now(args.now)
        ledger = _load(args.consumed_ledger, "consumed ledger")
        if not isinstance(ledger, list):
            raise MainnetReleaseAuthorizationError("consumed ledger must be a JSON array")
        evidence = validate_mainnet_release_authorization(
            _load(args.authorization, "authorization"),
            _load(args.expected_binding, "expected binding"),
            _load(args.approval_policy, "approval policy"),
            ledger,
            now=now,
        ).as_evidence()
    except (MainnetReleaseAuthorizationError, ValueError) as exc:
        print(f"mainnet release authorization rejected: {exc}", file=sys.stderr)
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
