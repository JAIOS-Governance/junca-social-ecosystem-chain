#!/usr/bin/env python3
"""Validate launch bindings and generate deterministic genesis and rollback evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.deployment_bundle import (
    DeploymentBundleError,
    build_rollback_manifest,
    load_launch_manifest,
    render_genesis,
    serialize_genesis,
    write_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "config/junca_social_ecosystem_chain_launch_manifest.json"),
    )
    parser.add_argument("--output-dir")
    parser.add_argument("--binary-digest")
    parser.add_argument("--source-commit")
    parser.add_argument("--expect-state", choices=("pending-bindings", "bound"), default="pending-bindings")
    args = parser.parse_args()
    try:
        manifest = load_launch_manifest(args.manifest)
        if manifest.state != args.expect_state:
            raise DeploymentBundleError(
                f"launch state {manifest.state!r} does not match {args.expect_state!r}"
            )
        evidence = manifest.as_evidence()
        if manifest.state == "bound":
            if not args.output_dir or not args.binary_digest or not args.source_commit:
                raise DeploymentBundleError(
                    "bound generation requires output-dir, binary-digest and source-commit"
                )
            genesis = render_genesis(manifest)
            rollback = build_rollback_manifest(
                genesis,
                binary_digest=args.binary_digest,
                source_commit=args.source_commit,
            )
            output = Path(args.output_dir)
            write_atomic(output / "genesis.json", serialize_genesis(genesis))
            write_atomic(
                output / "rollback-manifest.json",
                (json.dumps(rollback, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
            evidence["genesis_digest"] = rollback["genesis_digest"]
            evidence["rollback_identity_digest"] = rollback["identity_digest"]
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0
    except DeploymentBundleError as exc:
        print(f"deployment bundle rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
