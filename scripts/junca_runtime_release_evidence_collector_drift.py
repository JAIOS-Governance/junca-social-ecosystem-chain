#!/usr/bin/env python3
"""Collect Public Testnet pre-rollout evidence with exact AMI-drift inventory.

The canonical collector historically required every running validator instance to
match Terraform's approved previous AMI. Emergency in-place runtime recovery can
leave a healthy, finalized validator on a different pre-candidate AMI while the
Terraform state still identifies the prior approved image. This wrapper does not
normalize or conceal that drift. It records the exact observed AMI per validator,
rejects any candidate AMI already present before rollout, preserves the canonical
state/finality/migration checks, and labels drift as pre-rollout inventory rather
than candidate acceptance.
"""

from __future__ import annotations

import argparse
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
_observed_validator_runtimes: list[dict[str, Any]] = []
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
        root_volumes[instance_id] = root_volume_id
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


def _rewrite(path: Path, additions: Mapping[str, Any]) -> None:
    value = collector.read_object(path)
    value.update(additions)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def collect_with_drift(**kwargs: Any) -> tuple[Path, Path, Path]:
    global _candidate_ami_id, _observed_validator_runtimes
    candidate = kwargs["candidate"]
    _candidate_ami_id = str(candidate.get("ami_id", ""))
    collector.require(
        collector.AMI.fullmatch(_candidate_ami_id) is not None,
        "candidate.ami_id:invalid",
    )
    _observed_validator_runtimes = []

    original = collector.verify_instances
    collector.verify_instances = verify_instances_with_drift
    try:
        manifest_path, explorer_path, ebs_path = collector.collect(**kwargs)
    finally:
        collector.verify_instances = original

    collector.require(
        len(_observed_validator_runtimes) == 3,
        "observed_validator_runtimes:not_exact_three",
    )
    drift = any(
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
        "runtime_ami_drift_detected": drift,
        "candidate_ami_preexisting": False,
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
