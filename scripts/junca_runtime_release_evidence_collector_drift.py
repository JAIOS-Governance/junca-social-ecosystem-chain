#!/usr/bin/env python3
"""Collect exact Public Testnet pre-rollout drift and lineage evidence.

The canonical collector requires the running validator instances and root volumes
to remain identical to the durable-state migration run. A governed serial
replacement may legitimately rotate an EC2 instance and its ephemeral root
volume while retaining the validator identity, KMS signer, durable state EBS
volume and rollback snapshot. This wrapper never erases that history. It records
both the migration-time and current identities, rejects a candidate AMI already
present before rollout, and accepts rotation only when retained-state lineage is
exactly verified.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "scripts" / "junca_runtime_release_evidence_collector.py"


def _load_canonical():
    spec = importlib.util.spec_from_file_location(
        "junca_runtime_release_evidence_collector_canonical", CANONICAL
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical collector module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


collector = _load_canonical()
_canonical_verify_instances = collector.verify_instances
_canonical_verify_migration_evidence = collector.verify_migration_evidence
_observed_validator_runtimes: list[dict[str, Any]] = []
_migration_lineage: dict[str, Any] = {}
_candidate_ami_id = ""


def verify_instances_with_drift(
    response: Mapping[str, Any],
    instance_ids: Sequence[str],
    previous_ami_id: str,
) -> dict[str, str]:
    reservations = response.get("Reservations")
    collector.require(isinstance(reservations, list), "aws.instances:missing")
    instances: list[Mapping[str, Any]] = []
    for reservation in reservations:
        collector.require(
            isinstance(reservation, Mapping), "aws.instances:invalid"
        )
        values = reservation.get("Instances")
        collector.require(isinstance(values, list), "aws.instances:invalid")
        collector.require(
            all(isinstance(item, Mapping) for item in values),
            "aws.instances:invalid",
        )
        instances.extend(values)

    by_id = {item.get("InstanceId"): item for item in instances}
    collector.require(
        set(by_id) == set(instance_ids), "aws.instances:identity_mismatch"
    )

    root_volumes: dict[str, str] = {}
    observed: list[dict[str, Any]] = []
    for validator_id, instance_id in zip(
        collector.VALIDATOR_IDS, instance_ids, strict=True
    ):
        instance = by_id[instance_id]
        state = instance.get("State")
        collector.require(
            isinstance(state, Mapping) and state.get("Name") == "running",
            f"aws.instances.{instance_id}:not_running",
        )
        image_id = instance.get("ImageId")
        collector.require(
            collector.AMI.fullmatch(str(image_id)) is not None,
            f"aws.instances.{instance_id}:invalid_current_ami",
        )
        collector.require(
            image_id != _candidate_ami_id,
            f"aws.instances.{instance_id}:candidate_preexisting",
        )

        root_device = instance.get("RootDeviceName")
        mappings = instance.get("BlockDeviceMappings")
        collector.require(
            isinstance(root_device, str) and isinstance(mappings, list),
            f"aws.instances.{instance_id}.root_volume:missing",
        )
        matches = [
            item
            for item in mappings
            if isinstance(item, Mapping)
            and item.get("DeviceName") == root_device
            and isinstance(item.get("Ebs"), Mapping)
        ]
        collector.require(
            len(matches) == 1,
            f"aws.instances.{instance_id}.root_volume:not_exact_one",
        )
        root_volume_id = matches[0]["Ebs"].get("VolumeId")
        collector.require(
            collector.VOLUME.fullmatch(str(root_volume_id)) is not None,
            f"aws.instances.{instance_id}.root_volume:invalid",
        )
        root_volumes[instance_id] = str(root_volume_id)
        observed.append(
            {
                "validator_id": validator_id,
                "instance_id": instance_id,
                "image_id": image_id,
                "state": "running",
                "terraform_approved_ami": image_id == previous_ami_id,
                "candidate_ami": False,
                "root_volume_id": root_volume_id,
            }
        )

    collector.require(
        len(set(root_volumes.values())) == 3,
        "aws.instances.root_volumes:not_distinct",
    )
    global _observed_validator_runtimes
    _observed_validator_runtimes = observed
    return root_volumes


def _lineage_mapping(
    *,
    validator_id: str,
    instance_id: Any,
    signer_arn: Any,
    state_volume_id: Any,
    rollback_snapshot_id: Any,
    root_volume_id: Any,
) -> dict[str, str]:
    collector.require(
        collector.INSTANCE.fullmatch(str(instance_id)) is not None,
        f"migration.lineage.{validator_id}.instance_id:invalid",
    )
    collector.require(
        isinstance(signer_arn, str)
        and signer_arn.startswith(
            f"arn:aws:kms:{collector.REGION}:{collector.ACCOUNT_ID}:key/"
        ),
        f"migration.lineage.{validator_id}.signer_arn:invalid",
    )
    collector.require(
        collector.VOLUME.fullmatch(str(state_volume_id)) is not None,
        f"migration.lineage.{validator_id}.state_volume_id:invalid",
    )
    collector.require(
        collector.SNAPSHOT.fullmatch(str(rollback_snapshot_id)) is not None,
        f"migration.lineage.{validator_id}.rollback_snapshot_id:invalid",
    )
    collector.require(
        collector.VOLUME.fullmatch(str(root_volume_id)) is not None,
        f"migration.lineage.{validator_id}.root_volume_id:invalid",
    )
    return {
        "validator_id": validator_id,
        "instance_id": str(instance_id),
        "signer_arn": signer_arn,
        "state_volume_id": str(state_volume_id),
        "rollback_snapshot_id": str(rollback_snapshot_id),
        "root_volume_id": str(root_volume_id),
    }


def verify_migration_evidence_with_lineage(
    evidence: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_head_sha: str,
    expected_request_sha256: str,
    instance_ids: Sequence[str],
    signers: Sequence[Mapping[str, str]],
    state_outputs: Sequence[Mapping[str, Any]],
    validator_volumes: Sequence[Mapping[str, Any]],
    instance_root_volumes: Mapping[str, str],
    snapshot_root_volumes: Mapping[str, str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    mappings = evidence.get("validator_mappings")
    migration_instance_ids = evidence.get("instance_ids")
    collector.require(
        isinstance(mappings, list)
        and len(mappings) == 3
        and all(isinstance(item, Mapping) for item in mappings),
        "migration.validator_mappings:not_exact_three",
    )
    collector.require(
        isinstance(migration_instance_ids, list)
        and len(migration_instance_ids) == 3
        and len(set(migration_instance_ids)) == 3
        and all(
            collector.INSTANCE.fullmatch(str(item)) is not None
            for item in migration_instance_ids
        ),
        "migration.instance_ids:invalid",
    )
    collector.require(
        len(instance_ids) == 3
        and len(set(instance_ids)) == 3
        and all(
            collector.INSTANCE.fullmatch(str(item)) is not None
            for item in instance_ids
        ),
        "migration.current_instance_ids:invalid",
    )

    expected_state_volume_ids = [
        item.get("volume_id") for item in state_outputs
    ]
    expected_snapshot_ids = [
        item.get("rollback_snapshot_id") for item in state_outputs
    ]
    collector.require(
        evidence.get("state_volume_ids") == expected_state_volume_ids,
        "migration.state_volume_ids:mismatch",
    )
    collector.require(
        evidence.get("rollback_snapshot_ids") == expected_snapshot_ids,
        "migration.rollback_snapshot_ids:mismatch",
    )
    collector.require(
        [item.get("volume_id") for item in validator_volumes]
        == expected_state_volume_ids,
        "migration.live_state_volume_ids:mismatch",
    )
    collector.require(
        [item.get("rollback_snapshot_id") for item in validator_volumes]
        == expected_snapshot_ids,
        "migration.live_rollback_snapshot_ids:mismatch",
    )

    original_lineage: list[dict[str, str]] = []
    current_lineage: list[dict[str, str]] = []
    adapted = copy.deepcopy(dict(evidence))
    adapted["instance_ids"] = list(instance_ids)
    adapted_mappings = adapted.get("validator_mappings")
    collector.require(
        isinstance(adapted_mappings, list) and len(adapted_mappings) == 3,
        "migration.adapted_mappings:not_exact_three",
    )
    adapted_snapshot_roots: dict[str, str] = {}

    for index, validator_id in enumerate(collector.VALIDATOR_IDS):
        migration_mapping = mappings[index]
        adapted_mapping = adapted_mappings[index]
        current_instance_id = instance_ids[index]
        signer_arn = signers[index].get("resource_arn")
        state_volume_id = expected_state_volume_ids[index]
        rollback_snapshot_id = expected_snapshot_ids[index]
        current_root_volume_id = instance_root_volumes.get(current_instance_id)

        original = _lineage_mapping(
            validator_id=validator_id,
            instance_id=migration_mapping.get("instance_id"),
            signer_arn=migration_mapping.get("signer_arn"),
            state_volume_id=migration_mapping.get("state_volume_id"),
            rollback_snapshot_id=migration_mapping.get(
                "rollback_snapshot_id"
            ),
            root_volume_id=migration_mapping.get("root_volume_id"),
        )
        collector.require(
            migration_mapping.get("validator_id") == validator_id,
            f"migration.lineage.{validator_id}.validator_id:mismatch",
        )
        collector.require(
            original["instance_id"] == str(migration_instance_ids[index]),
            f"migration.lineage.{validator_id}.instance_id:mismatch",
        )
        collector.require(
            original["signer_arn"] == signer_arn,
            f"migration.lineage.{validator_id}.signer_arn:mismatch",
        )
        collector.require(
            original["state_volume_id"] == state_volume_id,
            f"migration.lineage.{validator_id}.state_volume_id:mismatch",
        )
        collector.require(
            original["rollback_snapshot_id"] == rollback_snapshot_id,
            f"migration.lineage.{validator_id}.rollback_snapshot_id:mismatch",
        )
        collector.require(
            snapshot_root_volumes.get(str(rollback_snapshot_id))
            == original["root_volume_id"],
            f"migration.lineage.{validator_id}.snapshot_root:mismatch",
        )

        current = _lineage_mapping(
            validator_id=validator_id,
            instance_id=current_instance_id,
            signer_arn=signer_arn,
            state_volume_id=state_volume_id,
            rollback_snapshot_id=rollback_snapshot_id,
            root_volume_id=current_root_volume_id,
        )
        original_lineage.append(original)
        current_lineage.append(current)

        collector.require(
            isinstance(adapted_mapping, dict),
            f"migration.lineage.{validator_id}.adapted_mapping:invalid",
        )
        adapted_mapping["instance_id"] = current["instance_id"]
        adapted_mapping["root_volume_id"] = current["root_volume_id"]
        adapted_snapshot_roots[current["rollback_snapshot_id"]] = current[
            "root_volume_id"
        ]

    collector.require(
        len({item["state_volume_id"] for item in original_lineage}) == 3,
        "migration.lineage.state_volumes:not_distinct",
    )
    collector.require(
        len({item["rollback_snapshot_id"] for item in original_lineage}) == 3,
        "migration.lineage.snapshots:not_distinct",
    )
    collector.require(
        len({item["signer_arn"] for item in original_lineage}) == 3,
        "migration.lineage.signers:not_distinct",
    )
    collector.require(
        len({item["root_volume_id"] for item in original_lineage}) == 3,
        "migration.lineage.original_roots:not_distinct",
    )
    collector.require(
        len({item["root_volume_id"] for item in current_lineage}) == 3,
        "migration.lineage.current_roots:not_distinct",
    )

    normalized, finality = _canonical_verify_migration_evidence(
        adapted,
        expected_run_id=expected_run_id,
        expected_head_sha=expected_head_sha,
        expected_request_sha256=expected_request_sha256,
        instance_ids=instance_ids,
        signers=signers,
        state_outputs=state_outputs,
        validator_volumes=validator_volumes,
        instance_root_volumes=instance_root_volumes,
        snapshot_root_volumes=adapted_snapshot_roots,
    )

    global _migration_lineage
    _migration_lineage = {
        "migration_lineage_state": "RETAINED_STATE_LINEAGE_VERIFIED",
        "migration_retained_state_lineage_verified": True,
        "migration_instance_rotation_detected": any(
            original["instance_id"] != current["instance_id"]
            for original, current in zip(
                original_lineage, current_lineage, strict=True
            )
        ),
        "migration_root_volume_rotation_detected": any(
            original["root_volume_id"] != current["root_volume_id"]
            for original, current in zip(
                original_lineage, current_lineage, strict=True
            )
        ),
        "migration_original_validator_mappings": original_lineage,
        "migration_current_validator_mappings": current_lineage,
        "migration_retained_state_volume_ids": expected_state_volume_ids,
        "migration_retained_rollback_snapshot_ids": expected_snapshot_ids,
        "migration_retained_signer_arns": [
            item["signer_arn"] for item in current_lineage
        ],
    }
    return normalized, finality


def _rewrite(path: Path, additions: Mapping[str, Any]) -> None:
    value = collector.read_object(path)
    value.update(additions)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def collect_with_drift(**kwargs: Any) -> tuple[Path, Path, Path]:
    global _candidate_ami_id, _observed_validator_runtimes, _migration_lineage
    candidate = kwargs["candidate"]
    _candidate_ami_id = str(candidate.get("ami_id", ""))
    collector.require(
        collector.AMI.fullmatch(_candidate_ami_id) is not None,
        "candidate.ami_id:invalid",
    )
    _observed_validator_runtimes = []
    _migration_lineage = {}

    collector.verify_instances = verify_instances_with_drift
    collector.verify_migration_evidence = verify_migration_evidence_with_lineage
    try:
        manifest_path, explorer_path, ebs_path = collector.collect(**kwargs)
    finally:
        collector.verify_instances = _canonical_verify_instances
        collector.verify_migration_evidence = (
            _canonical_verify_migration_evidence
        )

    collector.require(
        len(_observed_validator_runtimes) == 3,
        "observed_validator_runtimes:not_exact_three",
    )
    collector.require(
        _migration_lineage.get("migration_retained_state_lineage_verified")
        is True,
        "migration_lineage:not_verified",
    )
    ami_drift = any(
        item["terraform_approved_ami"] is False
        for item in _observed_validator_runtimes
    )
    observed_ami_ids = sorted(
        {str(item["image_id"]) for item in _observed_validator_runtimes}
    )
    additions = {
        "observed_runtime_ami_state": (
            "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE"
        ),
        "observed_validator_runtimes": _observed_validator_runtimes,
        "observed_runtime_ami_ids": observed_ami_ids,
        "runtime_ami_drift_detected": ami_drift,
        "candidate_ami_preexisting": False,
        **_migration_lineage,
    }
    _rewrite(explorer_path, additions)
    _rewrite(ebs_path, additions)
    manifest = collector.read_object(manifest_path)
    manifest.update(additions)
    manifest["explorer_baseline_sha256"] = collector.digest(explorer_path)
    manifest["ebs_baseline_sha256"] = collector.digest(ebs_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, explorer_path, ebs_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-ami", required=True)
    parser.add_argument("--bootstrap-outputs", required=True)
    parser.add_argument("--public-testnet-outputs", required=True)
    parser.add_argument("--images", required=True)
    parser.add_argument("--instances", required=True)
    parser.add_argument("--volumes", required=True)
    parser.add_argument("--snapshots", required=True)
    runtime_readback = parser.add_mutually_exclusive_group(required=True)
    runtime_readback.add_argument("--endpoint-acceptance")
    runtime_readback.add_argument("--private-validator-health")
    parser.add_argument("--public-endpoint-outage")
    parser.add_argument("--migration-evidence", required=True)
    parser.add_argument("--expected-migration-run-id", required=True)
    parser.add_argument("--expected-migration-head-sha", required=True)
    parser.add_argument("--expected-migration-request-sha256", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        paths = collect_with_drift(
            candidate=collector.read_object(args.candidate_ami),
            bootstrap=collector.read_object(args.bootstrap_outputs),
            public=collector.read_object(args.public_testnet_outputs),
            images=collector.read_object(args.images),
            instances=collector.read_object(args.instances),
            volumes=collector.read_object(args.volumes),
            snapshots=collector.read_object(args.snapshots),
            endpoints=(
                collector.read_object(args.endpoint_acceptance)
                if args.endpoint_acceptance
                else None
            ),
            private_validator_health=(
                collector.read_object(args.private_validator_health)
                if args.private_validator_health
                else None
            ),
            public_endpoint_outage=(
                collector.read_object(args.public_endpoint_outage)
                if args.public_endpoint_outage
                else None
            ),
            migration_evidence=collector.read_object(args.migration_evidence),
            migration_evidence_sha256=collector.digest(args.migration_evidence),
            expected_migration_run_id=args.expected_migration_run_id,
            expected_migration_head_sha=args.expected_migration_head_sha,
            expected_migration_request_sha256=(
                args.expected_migration_request_sha256
            ),
            expected_source_commit=args.expected_source_commit,
            output_dir=args.output_dir,
        )
    except collector.EvidenceError as exc:
        print(json.dumps({"state": "EVIDENCE_REJECTED", "reason": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "state": "EVIDENCE_VERIFIED",
                "files": [str(path) for path in paths],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
