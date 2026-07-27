#!/usr/bin/env python3
"""Final post-rollout Public Testnet Runtime Acceptance gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be an object: {path}")
    return value


def _digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(
    soak: Mapping[str, Any],
    final_readback: Mapping[str, Any],
    foundation_outputs: Mapping[str, Any],
    foundation_acceptance: Mapping[str, Any],
    publication: Mapping[str, Any],
    *,
    final_readback_sha256: str,
) -> dict[str, Any]:
    failures: list[str] = []
    candidate = soak.get("candidate_binding")
    provenance = soak.get("provenance")
    if not isinstance(candidate, Mapping):
        failures.append("soak.candidate_binding:missing")
        candidate = {}
    if SHA256.fullmatch(str(candidate.get("request_sha256", ""))) is None:
        failures.append("soak.candidate_binding.request_sha256:invalid")
    if not isinstance(provenance, Mapping):
        failures.append("soak.provenance:missing")
        provenance = {}
    if (
        soak.get("schema_version") != "junca-public-testnet-live-soak/v1"
        or soak.get("status") != "PASS"
        or soak.get("accepted") is not True
        or soak.get("duration_seconds", 0) < 86_400
        or soak.get("segments_completed") != 6
        or soak.get("continuous_observation") is not True
        or soak.get("head_advanced") is not True
    ):
        failures.append("soak.acceptance:not_passed")
    if provenance.get("final_runtime_readback_sha256") != final_readback_sha256:
        failures.append("soak.final_runtime_readback_sha256:mismatch")
    if (
        final_readback.get("schema_version")
        != "junca-public-testnet-final-runtime-readback/v1"
        or final_readback.get("status") != "PASS"
        or final_readback.get("candidate_binding") != candidate
        or len(final_readback.get("instance_ids", [])) != 3
        or len(set(final_readback.get("instance_ids", []))) != 3
    ):
        failures.append("final_runtime_readback:not_candidate_exact_three")
    approved = foundation_outputs.get("approved_node_ami_readback", {})
    approved = approved.get("value", {}) if isinstance(approved, Mapping) else {}
    expected_approved = {
        "id": candidate.get("ami_id"),
        "source_commit": candidate.get("source_commit"),
        "node_sha256": candidate.get("node_artifact_sha256"),
        "genesis_sha256": candidate.get("genesis_sha256"),
    }
    if any(approved.get(key) != value for key, value in expected_approved.items()):
        failures.append("foundation_outputs.candidate_binding:mismatch")
    if (
        foundation_acceptance.get("schema_version")
        != "junca-public-testnet-runtime-acceptance/v1"
        or foundation_acceptance.get("result") != "PASS"
        or foundation_acceptance.get("observations", {}).get("head_advanced")
        is not True
    ):
        failures.append("foundation_acceptance:not_passed")
    if (
        publication.get("schema_version")
        != "junca-public-testnet-publication/v1"
        or publication.get("result") != "PASS"
        or publication.get("candidate_binding") != candidate
        or str(publication.get("foundation_run_id"))
        != str(provenance.get("foundation_run_id"))
    ):
        failures.append("publication:candidate_or_provenance_mismatch")
    for name, source in (
        ("soak", soak),
        ("final_runtime_readback", final_readback),
        ("publication", publication),
    ):
        boundary = source.get("release_boundary", source)
        if not isinstance(boundary, Mapping) or any(
            boundary.get(field) is not False for field in BOUNDARY_FIELDS
        ):
            failures.append(f"{name}.release_boundary:not_false")
    failures = sorted(set(failures))
    return {
        "schema_version": "junca-public-testnet-runtime-acceptance-decision/v1",
        "decision": "PUBLIC_TESTNET_RUNTIME_ACCEPTED"
        if not failures
        else "PUBLIC_TESTNET_RUNTIME_REJECTED",
        "accepted": not failures,
        "candidate": dict(candidate),
        "provenance": dict(provenance),
        "failures": failures,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soak", required=True)
    parser.add_argument("--final-runtime-readback", required=True)
    parser.add_argument("--foundation-outputs", required=True)
    parser.add_argument("--foundation-acceptance", required=True)
    parser.add_argument("--publication", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    decision = evaluate(
        _read(args.soak),
        _read(args.final_runtime_readback),
        _read(args.foundation_outputs),
        _read(args.foundation_acceptance),
        _read(args.publication),
        final_readback_sha256=_digest(args.final_runtime_readback),
    )
    Path(args.output).write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if decision["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
