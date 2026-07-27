#!/usr/bin/env python3
"""Fail-closed promotion gate for a JUNCA immutable validator runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


ACCOUNT_ID = "595710543956"
REGION = "us-east-1"
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
VOLUME = re.compile(r"vol-[0-9a-f]{8,17}")
SNAPSHOT = re.compile(r"snap-[0-9a-f]{8,17}")


def read_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be a JSON object: {path}")
    return value


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _boundary(source: Mapping[str, Any], name: str, failures: list[str]) -> None:
    boundary = source.get("release_boundary")
    if not isinstance(boundary, Mapping):
        failures.append(f"{name}.release_boundary:missing")
        return
    for field in BOUNDARY_FIELDS:
        if boundary.get(field) is not False:
            failures.append(f"{name}.release_boundary.{field}:not_false")


def _candidate_binding(source: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        source.get("source_commit"),
        source.get("node_artifact_sha256"),
        source.get("genesis_sha256"),
        source.get("ami_id"),
    )


def evaluate(
    manifest: Mapping[str, Any],
    explorer: Mapping[str, Any],
    ebs: Mapping[str, Any],
    *,
    explorer_evidence_sha256: str,
    ebs_evidence_sha256: str,
    expected_source_commit: str,
    expected_artifact_sha256: str,
    expected_genesis_sha256: str,
) -> dict[str, Any]:
    failures: list[str] = []
    expected = (
        expected_source_commit,
        expected_artifact_sha256,
        expected_genesis_sha256,
        manifest.get("ami_id"),
    )

    if manifest.get("schema_version") != "junca-runtime-release-manifest/v1":
        failures.append("manifest.schema_version:mismatch")
    if manifest.get("state") != "RELEASE_CANDIDATE":
        failures.append("manifest.state:not_candidate")
    if manifest.get("network") != "Public Testnet":
        failures.append("manifest.network:mismatch")
    if manifest.get("notice") != "Public Testnet / No Monetary Value":
        failures.append("manifest.notice:mismatch")
    if not COMMIT.fullmatch(str(expected_source_commit)):
        failures.append("expected.source_commit:invalid")
    if not SHA256.fullmatch(str(expected_artifact_sha256)):
        failures.append("expected.node_artifact_sha256:invalid")
    if not SHA256.fullmatch(str(expected_genesis_sha256)):
        failures.append("expected.genesis_sha256:invalid")
    if _candidate_binding(manifest) != expected:
        failures.append("manifest.candidate_binding:stale_or_mismatched")
    if not AMI.fullmatch(str(manifest.get("ami_id", ""))):
        failures.append("manifest.ami_id:invalid")

    provenance = manifest.get("ami_provenance")
    if not isinstance(provenance, Mapping):
        failures.append("manifest.ami_provenance:missing")
    else:
        required_tags = {
            "State": "available",
            "OwnerId": ACCOUNT_ID,
            "Region": REGION,
            "SourceCommit": expected_source_commit,
            "NodeArtifactSHA256": expected_artifact_sha256,
            "GenesisSHA256": expected_genesis_sha256,
            "MainnetChanged": "false",
            "AssetsMoved": "false",
            "BridgeActivated": "false",
        }
        for field, value in required_tags.items():
            if provenance.get(field) != value:
                failures.append(f"manifest.ami_provenance.{field}:mismatch")

    signers = manifest.get("signer_bindings")
    signer_prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    if not isinstance(signers, list):
        failures.append("manifest.signer_bindings:missing")
    else:
        identities = tuple(
            sorted(
                item.get("validator_id", "")
                for item in signers
                if isinstance(item, Mapping)
            )
        )
        arns = [
            item.get("resource_arn")
            for item in signers
            if isinstance(item, Mapping)
        ]
        if (
            len(signers) != 3
            or identities != VALIDATOR_IDS
            or len(set(arns)) != 3
            or any(
                not isinstance(arn, str) or not arn.startswith(signer_prefix)
                for arn in arns
            )
        ):
            failures.append("manifest.signer_bindings:not_exact_three")

    previous = manifest.get("previous_runtime")
    if not isinstance(previous, Mapping):
        failures.append("manifest.previous_runtime:missing")
    else:
        previous_binding = _candidate_binding(previous)
        if previous_binding == expected:
            failures.append("manifest.previous_runtime:equals_candidate")
        if not all(previous_binding):
            failures.append("manifest.previous_runtime:incomplete")

    if manifest.get("explorer_acceptance_sha256") != explorer_evidence_sha256:
        failures.append("manifest.explorer_acceptance_sha256:mismatch")
    if manifest.get("ebs_migration_sha256") != ebs_evidence_sha256:
        failures.append("manifest.ebs_migration_sha256:mismatch")

    if explorer.get("schema_version") != "junca-public-explorer-acceptance/v2":
        failures.append("explorer.schema_version:not_v2")
    if explorer.get("accepted") is not True or explorer.get("status") != "PASS":
        failures.append("explorer.acceptance:not_passed")
    if explorer.get("finalized_only") is not True:
        failures.append("explorer.finalized_only:not_true")
    if explorer.get("read_only") is not True:
        failures.append("explorer.read_only:not_true")
    if explorer.get("unsafe_rpc_rejection") is not True:
        failures.append("explorer.unsafe_rpc_rejection:not_true")
    if _candidate_binding(explorer) != expected:
        failures.append("explorer.candidate_binding:mismatch")

    if ebs.get("schema_version") != "junca-validator-ebs-migration/v1":
        failures.append("ebs.schema_version:mismatch")
    if ebs.get("state") != "VERIFIED_PASS":
        failures.append("ebs.state:not_verified_pass")
    if ebs.get("migration_complete") is not True:
        failures.append("ebs.migration_complete:not_true")
    if ebs.get("data_loss") is not False:
        failures.append("ebs.data_loss:not_false")
    if _candidate_binding(ebs) != expected:
        failures.append("ebs.candidate_binding:mismatch")
    volumes = ebs.get("validator_volumes")
    if not isinstance(volumes, list):
        failures.append("ebs.validator_volumes:missing")
    else:
        volume_ids: list[Any] = []
        identities: list[Any] = []
        snapshots: list[Any] = []
        for item in volumes:
            if not isinstance(item, Mapping):
                continue
            identities.append(item.get("validator_id"))
            volume_ids.append(item.get("volume_id"))
            snapshots.append(item.get("rollback_snapshot_id"))
            if (
                item.get("encrypted") is not True
                or item.get("volume_type") != "gp3"
                or item.get("mount_path") != "/var/lib/junca"
                or item.get("filesystem_verified") is not True
                or item.get("state_store_integrity") is not True
                or item.get("finality_certificate_recovered") is not True
            ):
                failures.append("ebs.validator_volumes:acceptance_incomplete")
        if (
            len(volumes) != 3
            or tuple(sorted(identities)) != VALIDATOR_IDS
            or len(set(volume_ids)) != 3
            or any(not VOLUME.fullmatch(str(value)) for value in volume_ids)
            or len(set(snapshots)) != 3
            or any(not SNAPSHOT.fullmatch(str(value)) for value in snapshots)
        ):
            failures.append("ebs.validator_volumes:not_exact_three")

    for name, source in (
        ("manifest", manifest),
        ("explorer", explorer),
        ("ebs", ebs),
    ):
        _boundary(source, name, failures)

    failures = sorted(set(failures))
    return {
        "schema_version": "junca-runtime-release-manifest-decision/v1",
        "decision": "PROMOTION_GATE_PASS" if not failures else "PROMOTION_GATE_REJECTED",
        "accepted": not failures,
        "candidate": {
            "source_commit": expected_source_commit,
            "node_artifact_sha256": expected_artifact_sha256,
            "genesis_sha256": expected_genesis_sha256,
            "ami_id": manifest.get("ami_id"),
        },
        "failure_count": len(failures),
        "failures": failures,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--explorer-acceptance", required=True)
    parser.add_argument("--ebs-migration", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-artifact-sha256", required=True)
    parser.add_argument("--expected-genesis-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    decision = evaluate(
        read_object(args.manifest),
        read_object(args.explorer_acceptance),
        read_object(args.ebs_migration),
        explorer_evidence_sha256=file_sha256(args.explorer_acceptance),
        ebs_evidence_sha256=file_sha256(args.ebs_migration),
        expected_source_commit=args.expected_source_commit,
        expected_artifact_sha256=args.expected_artifact_sha256,
        expected_genesis_sha256=args.expected_genesis_sha256,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"decision": decision["decision"], "output": str(output)}))
    return 0 if decision["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
