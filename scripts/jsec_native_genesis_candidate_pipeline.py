#!/usr/bin/env python3
"""Compile, independently verify and seal a non-activated JSEC Genesis candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.native_token_genesis import (
    NativeTokenGenesisError,
    evaluate_native_genesis_candidate,
    load_native_token_genesis_plan,
)


SCHEMA_VERSION = "jsec-native-genesis-candidate-pipeline/v1"
BLOCKED = "BLOCKED"
VERIFIED = "VERIFIED_NON_ACTIVATED_CANDIDATE"
SAFETY = {
    "mainnet_changed": False,
    "genesis_applied": False,
    "assets_moved": False,
    "bridge_activated": False,
    "mainnet_activation_authorized": False,
}


def _write_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8")
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _remove_stale(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def run_pipeline(plan_path: Path, output_dir: Path) -> dict[str, Any]:
    candidate_path = output_dir / "native-genesis-candidate.json"
    verification_path = output_dir / "native-genesis-candidate-verification.json"
    manifest_path = output_dir / "pipeline-manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in (manifest_path, candidate_path, verification_path):
        _remove_stale(path)

    plan = load_native_token_genesis_plan(plan_path)

    if not plan.ready_for_genesis_ceremony:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "state": BLOCKED,
            "source_plan_sha256": plan.specification_digest,
            "blockers": list(plan.blockers),
            "candidate": None,
            "verification": None,
            "safety": dict(SAFETY),
        }
        _write_json(manifest_path, manifest)
        return manifest

    candidate = plan.genesis_candidate()
    verification = evaluate_native_genesis_candidate(
        candidate,
        source_plan=plan,
    ).as_evidence()
    candidate_file_sha256 = _write_json(candidate_path, candidate)
    verification_file_sha256 = _write_json(verification_path, verification)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state": VERIFIED,
        "source_plan_sha256": plan.specification_digest,
        "blockers": [],
        "candidate": {
            "path": candidate_path.name,
            "canonical_sha256": verification["candidate_sha256"],
            "file_sha256": candidate_file_sha256,
        },
        "verification": {
            "path": verification_path.name,
            "file_sha256": verification_file_sha256,
            "source_plan_bound": verification["source_plan_bound"],
        },
        "safety": dict(SAFETY),
    }
    _write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expect-state", choices=(BLOCKED, VERIFIED))
    args = parser.parse_args()

    try:
        manifest = run_pipeline(args.plan, args.output_dir)
    except NativeTokenGenesisError as exc:
        print(f"JSEC native Genesis candidate pipeline failed: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.expect_state is not None and manifest["state"] != args.expect_state:
        print(
            "JSEC native Genesis candidate pipeline state mismatch: "
            f"expected {args.expect_state}, got {manifest['state']}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
