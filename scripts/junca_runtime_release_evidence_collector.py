#!/usr/bin/env python3
"""Build fail-closed Public Testnet release evidence from read-only readbacks.

The collector never invents identifiers or acceptance results.  It accepts an
immutable AMI build artifact, canonical Terraform outputs, AWS describe API
responses, and the existing live endpoint acceptance report.  Missing durable
state migration markers or mismatched runtime identity reject collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


ACCOUNT_ID = "595710543956"
REGION = "us-east-1"
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
BOUNDARY = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
INSTANCE = re.compile(r"i-[0-9a-f]{8,17}")
VOLUME = re.compile(r"vol-[0-9a-f]{8,17}")
SNAPSHOT = re.compile(r"snap-[0-9a-f]{8,17}")


class EvidenceError(RuntimeError):
    """Raised when an observed release invariant is absent or mismatched."""


def read_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"unable to read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"evidence must be a JSON object: {path}")
    return value


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def output_value(outputs: Mapping[str, Any], name: str) -> Any:
    item = outputs.get(name)
    require(isinstance(item, Mapping) and "value" in item, f"terraform.{name}:missing")
    return item["value"]


def tags(source: Mapping[str, Any]) -> dict[str, str]:
    raw = source.get("Tags")
    require(isinstance(raw, list), "aws.tags:missing")
    result: dict[str, str] = {}
    for item in raw:
        require(isinstance(item, Mapping), "aws.tags:invalid")
        key, value = item.get("Key"), item.get("Value")
        require(isinstance(key, str) and isinstance(value, str), "aws.tags:invalid")
        require(key not in result, f"aws.tags.{key}:duplicate")
        result[key] = value
    return result


def exact_items(
    source: Mapping[str, Any], name: str, expected: int
) -> list[Mapping[str, Any]]:
    value = source.get(name)
    require(isinstance(value, list) and len(value) == expected, f"aws.{name}:not_exact_{expected}")
    require(all(isinstance(item, Mapping) for item in value), f"aws.{name}:invalid")
    return value


def candidate_binding(candidate: Mapping[str, Any]) -> dict[str, str]:
    result = {
        "source_commit": candidate.get("source_commit"),
        "node_artifact_sha256": candidate.get("node_artifact_sha256"),
        "genesis_sha256": candidate.get("genesis_sha256"),
        "ami_id": candidate.get("ami_id"),
        "request_sha256": candidate.get("request_sha256"),
    }
    require(COMMIT.fullmatch(str(result["source_commit"])) is not None, "candidate.source_commit:invalid")
    require(SHA256.fullmatch(str(result["node_artifact_sha256"])) is not None, "candidate.node_artifact_sha256:invalid")
    require(SHA256.fullmatch(str(result["genesis_sha256"])) is not None, "candidate.genesis_sha256:invalid")
    require(AMI.fullmatch(str(result["ami_id"])) is not None, "candidate.ami_id:invalid")
    require(SHA256.fullmatch(str(result["request_sha256"])) is not None, "candidate.request_sha256:invalid")
    return result  # type: ignore[return-value]


def verify_candidate(candidate: Mapping[str, Any], expected_source_commit: str) -> dict[str, str]:
    require(candidate.get("schema_version") == "junca-validator-ami-build/v1", "candidate.schema_version:mismatch")
    require(candidate.get("state") == "AMI_VERIFIED", "candidate.state:not_verified")
    require(candidate.get("network") == "Public Testnet", "candidate.network:mismatch")
    require(candidate.get("notice") == "Public Testnet / No Monetary Value", "candidate.notice:mismatch")
    require(candidate.get("terraform_state_changed") is False, "candidate.terraform_state_changed:not_false")
    for field in BOUNDARY:
        require(candidate.get(field) is False, f"candidate.{field}:not_false")
    binding = candidate_binding(candidate)
    require(binding["source_commit"] == expected_source_commit, "candidate.source_commit:unexpected")
    return binding


def verify_image(image: Mapping[str, Any], binding: Mapping[str, str]) -> dict[str, str]:
    require(image.get("ImageId") == binding["ami_id"], "candidate_image.ami_id:mismatch")
    require(image.get("State") == "available", "candidate_image.state:not_available")
    require(image.get("OwnerId") == ACCOUNT_ID, "candidate_image.owner:mismatch")
    image_tags = tags(image)
    required = {
        "Network": "Public Testnet",
        "Governance": "JAIOS Institutional Governance",
        "SourceCommit": binding["source_commit"],
        "NodeArtifactSHA256": binding["node_artifact_sha256"],
        "GenesisSHA256": binding["genesis_sha256"],
        "MainnetChanged": "false",
        "AssetsMoved": "false",
        "BridgeActivated": "false",
    }
    for name, value in required.items():
        require(image_tags.get(name) == value, f"candidate_image.tags.{name}:mismatch")
    return {
        "State": "available",
        "OwnerId": ACCOUNT_ID,
        "Region": REGION,
        **{name: required[name] for name in required if name not in ("Network", "Governance")},
    }


def verify_terraform(
    bootstrap: Mapping[str, Any], public: Mapping[str, Any]
) -> tuple[list[dict[str, str]], dict[str, str], list[str], list[Mapping[str, Any]]]:
    require(output_value(bootstrap, "aws_account_id") == ACCOUNT_ID, "bootstrap.account:mismatch")
    require(output_value(bootstrap, "aws_region") == REGION, "bootstrap.region:mismatch")
    signer_arns = output_value(bootstrap, "validator_signer_arns")
    require(
        isinstance(signer_arns, list)
        and len(signer_arns) == 3
        and len(set(signer_arns)) == 3,
        "bootstrap.signers:not_exact_three",
    )
    prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    require(all(isinstance(arn, str) and arn.startswith(prefix) for arn in signer_arns), "bootstrap.signers:invalid")
    signers = [
        {"validator_id": validator_id, "resource_arn": arn}
        for validator_id, arn in zip(VALIDATOR_IDS, signer_arns, strict=True)
    ]

    require(output_value(public, "aws_account_id") == ACCOUNT_ID, "runtime.account:mismatch")
    require(output_value(public, "region") == REGION, "runtime.region:mismatch")
    boundary = output_value(public, "runtime_boundary")
    require(isinstance(boundary, Mapping), "runtime.boundary:missing")
    for field in BOUNDARY:
        require(boundary.get(field) is False, f"runtime.boundary.{field}:not_false")

    previous = output_value(public, "approved_node_ami_readback")
    require(isinstance(previous, Mapping), "runtime.previous_ami:missing")
    previous_binding = {
        "source_commit": previous.get("source_commit"),
        "node_artifact_sha256": previous.get("node_sha256"),
        "genesis_sha256": previous.get("genesis_sha256"),
        "ami_id": previous.get("id"),
    }
    require(COMMIT.fullmatch(str(previous_binding["source_commit"])) is not None, "runtime.previous.source_commit:invalid")
    require(SHA256.fullmatch(str(previous_binding["node_artifact_sha256"])) is not None, "runtime.previous.node_sha256:invalid")
    require(SHA256.fullmatch(str(previous_binding["genesis_sha256"])) is not None, "runtime.previous.genesis_sha256:invalid")
    require(AMI.fullmatch(str(previous_binding["ami_id"])) is not None, "runtime.previous.ami_id:invalid")
    require(previous.get("owner_id") == ACCOUNT_ID, "runtime.previous.owner:mismatch")

    instance_ids = output_value(public, "validator_instance_ids")
    require(
        isinstance(instance_ids, list)
        and len(instance_ids) == 3
        and len(set(instance_ids)) == 3
        and all(INSTANCE.fullmatch(str(value)) for value in instance_ids),
        "runtime.instances:not_exact_three",
    )
    state_volumes = output_value(public, "validator_state_volume_readback")
    require(
        isinstance(state_volumes, list)
        and len(state_volumes) == 3
        and all(isinstance(value, Mapping) for value in state_volumes),
        "runtime.state_volumes:not_exact_three",
    )
    return signers, previous_binding, instance_ids, state_volumes  # type: ignore[return-value]


def verify_instances(
    response: Mapping[str, Any], instance_ids: Sequence[str], previous_ami_id: str
) -> None:
    reservations = response.get("Reservations")
    require(isinstance(reservations, list), "aws.instances:missing")
    instances: list[Mapping[str, Any]] = []
    for reservation in reservations:
        require(isinstance(reservation, Mapping), "aws.instances:invalid")
        values = reservation.get("Instances")
        require(isinstance(values, list), "aws.instances:invalid")
        require(all(isinstance(item, Mapping) for item in values), "aws.instances:invalid")
        instances.extend(values)
    by_id = {item.get("InstanceId"): item for item in instances}
    require(set(by_id) == set(instance_ids), "aws.instances:identity_mismatch")
    for instance_id in instance_ids:
        instance = by_id[instance_id]
        state = instance.get("State")
        require(isinstance(state, Mapping) and state.get("Name") == "running", f"aws.instances.{instance_id}:not_running")
        require(instance.get("ImageId") == previous_ami_id, f"aws.instances.{instance_id}:unexpected_current_ami")


def verify_volumes(
    response: Mapping[str, Any],
    state_outputs: Sequence[Mapping[str, Any]],
    instance_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    volumes = exact_items(response, "Volumes", 3)
    output_by_id = {item.get("volume_id"): item for item in state_outputs}
    require(len(output_by_id) == 3, "runtime.state_volumes:duplicate")
    by_id = {item.get("VolumeId"): item for item in volumes}
    require(set(by_id) == set(output_by_id), "aws.volumes:identity_mismatch")
    accepted: list[dict[str, Any]] = []
    snapshot_ids: list[str] = []
    for validator_id, instance_id, output in zip(
        VALIDATOR_IDS, instance_ids, state_outputs, strict=True
    ):
        volume_id = output.get("volume_id")
        require(output.get("validator_id") == validator_id, f"runtime.volumes.{validator_id}:identity_mismatch")
        require(VOLUME.fullmatch(str(volume_id)) is not None, f"runtime.volumes.{validator_id}:invalid_id")
        volume = by_id[volume_id]
        require(volume.get("Encrypted") is True, f"aws.volumes.{validator_id}:not_encrypted")
        require(volume.get("VolumeType") == "gp3", f"aws.volumes.{validator_id}:not_gp3")
        attachments = volume.get("Attachments")
        require(isinstance(attachments, list) and len(attachments) == 1, f"aws.volumes.{validator_id}:attachment_mismatch")
        attachment = attachments[0]
        require(
            isinstance(attachment, Mapping)
            and attachment.get("InstanceId") == instance_id
            and attachment.get("State") == "attached",
            f"aws.volumes.{validator_id}:attachment_mismatch",
        )
        volume_tags = tags(volume)
        required_tags = {
            "StatePath": "/var/lib/junca",
            "MigrationRequired": "false",
            "JuncaMigrationState": "VERIFIED_PASS",
            "JuncaFilesystemVerified": "true",
            "JuncaStateStoreIntegrity": "true",
            "JuncaFinalityCertificateRecovered": "true",
            "PublicTestnetOnly": "true",
        }
        for name, value in required_tags.items():
            require(volume_tags.get(name) == value, f"aws.volumes.{validator_id}.tags.{name}:mismatch")
        snapshot_id = volume_tags.get("JuncaRollbackSnapshotId")
        require(SNAPSHOT.fullmatch(str(snapshot_id)) is not None, f"aws.volumes.{validator_id}.rollback_snapshot:invalid")
        snapshot_ids.append(snapshot_id)  # type: ignore[arg-type]
        accepted.append(
            {
                "validator_id": validator_id,
                "volume_id": volume_id,
                "rollback_snapshot_id": snapshot_id,
                "encrypted": True,
                "volume_type": "gp3",
                "mount_path": "/var/lib/junca",
                "filesystem_verified": True,
                "state_store_integrity": True,
                "finality_certificate_recovered": True,
            }
        )
    require(len(set(snapshot_ids)) == 3, "aws.volumes.rollback_snapshots:not_distinct")
    return accepted, snapshot_ids


def verify_snapshots(response: Mapping[str, Any], expected_ids: Sequence[str]) -> None:
    snapshots = exact_items(response, "Snapshots", 3)
    by_id = {item.get("SnapshotId"): item for item in snapshots}
    require(set(by_id) == set(expected_ids), "aws.snapshots:identity_mismatch")
    for snapshot_id in expected_ids:
        snapshot = by_id[snapshot_id]
        require(snapshot.get("State") == "completed", f"aws.snapshots.{snapshot_id}:not_completed")
        require(snapshot.get("OwnerId") == ACCOUNT_ID, f"aws.snapshots.{snapshot_id}:owner_mismatch")
        require(snapshot.get("Encrypted") is True, f"aws.snapshots.{snapshot_id}:not_encrypted")


def verify_endpoint_acceptance(report: Mapping[str, Any]) -> dict[str, Any]:
    require(report.get("status") == "PASS", "endpoints.status:not_pass")
    require(report.get("scope") == "Public Testnet Runtime Acceptance / Read-only", "endpoints.scope:mismatch")
    checks = report.get("checks")
    require(isinstance(checks, Mapping), "endpoints.checks:missing")
    health = checks.get("health")
    explorer = checks.get("explorer")
    safe = checks.get("safe_rpc")
    unsafe = checks.get("unsafe_rpc_rejection")
    require(health == "PASS", "endpoints.health:not_pass")
    require(isinstance(explorer, Mapping) and explorer.get("result") == "PASS", "endpoints.explorer:not_pass")
    require(
        explorer.get("signed_power") == 3 and explorer.get("total_power") == 3,
        "endpoints.explorer:quorum_not_exact_three",
    )
    require(isinstance(safe, Mapping) and safe.get("result") == "PASS", "endpoints.safe_rpc:not_pass")
    require(isinstance(unsafe, Mapping) and unsafe.get("result") == "PASS", "endpoints.unsafe_rpc:not_rejected")
    return {
        "observed_at": report.get("observed_at"),
        "finalized_head": report.get("finalized_head"),
        "checks": checks,
    }


def collect(
    *,
    candidate: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    public: Mapping[str, Any],
    images: Mapping[str, Any],
    instances: Mapping[str, Any],
    volumes: Mapping[str, Any],
    snapshots: Mapping[str, Any],
    endpoints: Mapping[str, Any],
    expected_source_commit: str,
    output_dir: str | Path,
) -> tuple[Path, Path, Path]:
    require(COMMIT.fullmatch(expected_source_commit) is not None, "expected_source_commit:invalid")
    binding = verify_candidate(candidate, expected_source_commit)
    image_items = exact_items(images, "Images", 1)
    provenance = verify_image(image_items[0], binding)
    signers, previous, instance_ids, state_outputs = verify_terraform(bootstrap, public)
    require(previous != binding, "runtime.previous:equals_candidate")
    verify_instances(instances, instance_ids, previous["ami_id"])
    validator_volumes, snapshot_ids = verify_volumes(volumes, state_outputs, instance_ids)
    verify_snapshots(snapshots, snapshot_ids)
    endpoint_readback = verify_endpoint_acceptance(endpoints)

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    require(not any(target.iterdir()), "output_dir:not_empty")

    explorer = {
        "schema_version": "junca-public-explorer-pre-rollout-baseline/v1",
        "candidate_accepted": False,
        "status": "BASELINE_VERIFIED",
        "finalized_only": True,
        "read_only": True,
        "unsafe_rpc_rejection": True,
        **binding,
        "observed_runtime": previous,
        "readback": endpoint_readback,
        "release_boundary": dict(BOUNDARY),
    }
    ebs = {
        "schema_version": "junca-validator-ebs-pre-rollout-baseline/v1",
        "candidate_accepted": False,
        "state": "BASELINE_VERIFIED",
        "migration_complete": True,
        "data_loss": False,
        **binding,
        "observed_runtime": previous,
        "validator_volumes": validator_volumes,
        "release_boundary": dict(BOUNDARY),
    }
    explorer_path = target / "junca-public-explorer-pre-rollout-baseline.json"
    ebs_path = target / "junca-validator-ebs-pre-rollout-baseline.json"
    explorer_path.write_text(json.dumps(explorer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ebs_path.write_text(json.dumps(ebs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "junca-runtime-pre-rollout-baseline/v1",
        "state": "PRE_ROLLOUT_BASELINE_VERIFIED",
        "network": "Public Testnet",
        "notice": "Public Testnet / No Monetary Value",
        **binding,
        "ami_provenance": provenance,
        "signer_bindings": signers,
        "previous_runtime": previous,
        "explorer_baseline_sha256": digest(explorer_path),
        "ebs_baseline_sha256": digest(ebs_path),
        "release_boundary": dict(BOUNDARY),
    }
    manifest_path = target / "junca-runtime-pre-rollout-baseline.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    require(len(list(target.iterdir())) == 3, "output_dir:not_exact_three")
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
    parser.add_argument("--endpoint-acceptance", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        paths = collect(
            candidate=read_object(args.candidate_ami),
            bootstrap=read_object(args.bootstrap_outputs),
            public=read_object(args.public_testnet_outputs),
            images=read_object(args.images),
            instances=read_object(args.instances),
            volumes=read_object(args.volumes),
            snapshots=read_object(args.snapshots),
            endpoints=read_object(args.endpoint_acceptance),
            expected_source_commit=args.expected_source_commit,
            output_dir=args.output_dir,
        )
    except EvidenceError as exc:
        print(json.dumps({"state": "EVIDENCE_REJECTED", "reason": str(exc)}))
        return 1
    print(json.dumps({"state": "EVIDENCE_VERIFIED", "files": [str(path) for path in paths]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
