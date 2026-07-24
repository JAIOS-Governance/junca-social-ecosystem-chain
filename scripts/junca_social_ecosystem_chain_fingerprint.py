#!/usr/bin/env python3
"""Generate redacted, deterministic fingerprint evidence for legacy source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import LegacyFingerprintError, fingerprint_legacy_source


DEFAULT_REPOSITORY = "https://github.com/juncachain/juncachain"
DEFAULT_COMMIT = "a3e47b6a96c36378606764c35cfcdb2de97cb685"
DEFAULT_TAG = "v0.2.8"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--source-commit", default=DEFAULT_COMMIT)
    parser.add_argument("--source-tag", default=DEFAULT_TAG)
    parser.add_argument(
        "--output",
        default="artifacts/junca-social-ecosystem-chain-legacy-fingerprint.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        fingerprint = fingerprint_legacy_source(
            args.source_root,
            source_repository=args.source_repository,
            source_commit=args.source_commit,
            source_tag=args.source_tag,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(
            json.dumps(
                fingerprint.as_evidence(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
    except (LegacyFingerprintError, OSError) as exc:
        print(f"legacy fingerprint failed: {exc}", file=sys.stderr)
        return 1
    print(f"legacy fingerprint verified: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
