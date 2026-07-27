#!/usr/bin/env python3
"""Build fail-closed Public Testnet release evidence from read-only readbacks.

The collector never invents identifiers or acceptance results.  It accepts an
immutable AMI build artifact, canonical Terraform outputs, AWS describe API
responses, and either the existing live endpoint acceptance report or exact
three-validator private SSM health readback.  Missing durable state migration
markers or mismatched runtime identity reject collection.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


ACCOUNT_ID = "595710543956"
REGION = "us-east-1"
CHAIN_ID = 20260723
NETWORK_NOTICE = "Public Testnet / No Monetary Value"
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
HASH = re.compile(r"0x[0-9a-f]{64}")
RUN_ID = re.compile(r"[1-9][0-9]*")
MIGRATION_TOKEN = re.compile(r"[0-9]+-[1-9][0-9]*")
REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain"
CERTIFICATE_FIELDS = {
    "schema_version",
    "chain_id",
    "height",
    "round",
    "block_hash",
    "signed_power",
    "total_power",
    "validator_ids",
    "vote_hashes",
    "certificate_hash",
    "finality_status",
    "mainnet_changed",
    "assets_moved",
    "bridge_activated",
}


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


def canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceError("finality_certificate:invalid_json") from exc


def verify_finality_certificate(
    value: Any,
    *,
    height: int,
    head_hash: str,
    certificate_hash: str,
    label: str,
) -> str:
    require(
        isinstance(value, Mapping) and set(value) == CERTIFICATE_FIELDS,
        f"{label}:invalid_fields",
    )
    certificate = dict(value)
    require(
        certificate.get("schema_version")
        == "junca-finality-certificate/v1",
        f"{label}.schema_version:mismatch",
    )
    require(
        certificate.get("chain_id") == CHAIN_ID
        and certificate.get("height") == height
        and certificate.get("block_hash") == head_hash
        and certificate.get("certificate_hash") == certificate_hash,
        f"{label}.head_binding:mismatch",
    )
    for field in (
        "chain_id",
        "height",
        "round",
        "signed_power",
        "total_power",
    ):
        require(
            isinstance(certificate.get(field), int)
            and not isinstance(certificate.get(field), bool),
            f"{label}.{field}:invalid",
        )
    require(
        certificate.get("finality_status") == "FINALIZED"
        and certificate.get("signed_power") == 3
        and certificate.get("total_power") == 3
        and certificate.get("validator_ids") == list(VALIDATOR_IDS),
        f"{label}.quorum:invalid",
    )
    round_number = certificate.get("round")
    require(
        isinstance(round_number, int)
        and not isinstance(round_number, bool)
        and round_number >= 0,
        f"{label}.round:invalid",
    )
    vote_hashes = certificate.get("vote_hashes")
    require(
        isinstance(vote_hashes, list)
        and len(vote_hashes) == 3
        and len(set(vote_hashes)) == 3
        and all(HASH.fullmatch(str(item)) is not None for item in vote_hashes),
        f"{label}.vote_hashes:invalid",
    )
    for field in BOUNDARY:
        require(
            certificate.get(field) is False,
            f"{label}.{field}:not_false",
        )
    body = {
        "block_hash": head_hash,
        "chain_id": CHAIN_ID,
        "height": height,
        "round": round_number,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": list(VALIDATOR_IDS),
        "vote_hashes": vote_hashes,
    }
    expected_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + canonical_json(body).encode("utf-8")
    ).hexdigest()
    require(
        certificate_hash == expected_hash,
        f"{label}.certificate_hash:mismatch",
    )
    return canonical_json(certificate)


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
        "RequestDigest": binding["request_sha256"],
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
) -> tuple[
    list[dict[str, str]],
    dict[str, str],
    list[str],
    list[Mapping[str, Any]],
    bool,
]:
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
    public_services = output_value(public, "public_services_acceptance_readback")
    require(
        isinstance(public_services, Mapping)
        and isinstance(public_services.get("enabled"), bool),
        "runtime.public_services:missing",
    )
    return (  # type: ignore[return-value]
        signers,
        previous_binding,
        instance_ids,
        state_volumes,
        public_services["enabled"],
    )


def verify_instances(
    response: Mapping[str, Any], instance_ids: Sequence[str], previous_ami_id: str
) -> dict[str, str]:
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
    root_volumes: dict[str, str] = {}
    for instance_id in instance_ids:
        instance = by_id[instance_id]
        state = instance.get("State")
        require(isinstance(state, Mapping) and state.get("Name") == "running", f"aws.instances.{instance_id}:not_running")
        require(instance.get("ImageId") == previous_ami_id, f"aws.instances.{instance_id}:unexpected_current_ami")
        root_device = instance.get("RootDeviceName")
        mappings = instance.get("BlockDeviceMappings")
        require(
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
        require(
            len(matches) == 1,
            f"aws.instances.{instance_id}.root_volume:not_exact_one",
        )
        root_volume_id = matches[0]["Ebs"].get("VolumeId")
        require(
            VOLUME.fullmatch(str(root_volume_id)) is not None,
            f"aws.instances.{instance_id}.root_volume:invalid",
        )
        root_volumes[instance_id] = root_volume_id
    require(
        len(set(root_volumes.values())) == 3,
        "aws.instances.root_volumes:not_distinct",
    )
    return root_volumes


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
            "JuncaFinalityCertificateBackfilled": "true",
            "PublicTestnetOnly": "true",
        }
        for name, value in required_tags.items():
            require(volume_tags.get(name) == value, f"aws.volumes.{validator_id}.tags.{name}:mismatch")
        snapshot_id = volume_tags.get("JuncaRollbackSnapshotId")
        require(SNAPSHOT.fullmatch(str(snapshot_id)) is not None, f"aws.volumes.{validator_id}.rollback_snapshot:invalid")
        require(
            output.get("rollback_snapshot_id") == snapshot_id
            and output.get("migration_required") is False
            and output.get("migration_accepted") is True,
            f"runtime.volumes.{validator_id}.migration_acceptance:mismatch",
        )
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


def verify_snapshots(
    response: Mapping[str, Any], expected_ids: Sequence[str]
) -> dict[str, str]:
    snapshots = exact_items(response, "Snapshots", 3)
    by_id = {item.get("SnapshotId"): item for item in snapshots}
    require(set(by_id) == set(expected_ids), "aws.snapshots:identity_mismatch")
    root_volumes: dict[str, str] = {}
    for snapshot_id in expected_ids:
        snapshot = by_id[snapshot_id]
        require(snapshot.get("State") == "completed", f"aws.snapshots.{snapshot_id}:not_completed")
        require(snapshot.get("OwnerId") == ACCOUNT_ID, f"aws.snapshots.{snapshot_id}:owner_mismatch")
        require(snapshot.get("Encrypted") is True, f"aws.snapshots.{snapshot_id}:not_encrypted")
        root_volume_id = snapshot.get("VolumeId")
        require(
            VOLUME.fullmatch(str(root_volume_id)) is not None,
            f"aws.snapshots.{snapshot_id}.root_volume:invalid",
        )
        root_volumes[snapshot_id] = root_volume_id
    require(
        len(set(root_volumes.values())) == 3,
        "aws.snapshots.root_volumes:not_distinct",
    )
    return root_volumes


def verify_migration_evidence(
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
    require(RUN_ID.fullmatch(expected_run_id) is not None, "migration.expected_run_id:invalid")
    require(COMMIT.fullmatch(expected_head_sha) is not None, "migration.expected_head_sha:invalid")
    require(
        SHA256.fullmatch(expected_request_sha256) is not None,
        "migration.expected_request_sha256:invalid",
    )
    require(
        evidence.get("schema_version") == "junca-validator-state-migration/v1"
        and evidence.get("state") == "VERIFIED_PASS"
        and evidence.get("network") == "Public Testnet",
        "migration.evidence:invalid",
    )
    require(
        evidence.get("migration_run_id") == expected_run_id
        and evidence.get("migration_run_head_sha") == expected_head_sha
        and evidence.get("migration_request_sha256")
        == expected_request_sha256,
        "migration.top_level_binding:mismatch",
    )
    execution = evidence.get("execution_binding")
    require(isinstance(execution, Mapping), "migration.execution_binding:missing")
    require(
        execution.get("repository") == REPOSITORY
        and execution.get("run_id") == expected_run_id
        and isinstance(execution.get("run_attempt"), int)
        and not isinstance(execution.get("run_attempt"), bool)
        and execution.get("run_attempt", 0) >= 1
        and execution.get("head_sha") == expected_head_sha
        and execution.get("migration_request_sha256")
        == expected_request_sha256
        and SHA256.fullmatch(str(execution.get("github_event_sha256")))
        is not None
        and MIGRATION_TOKEN.fullmatch(str(execution.get("migration_token")))
        is not None,
        "migration.execution_binding:mismatch",
    )
    require(
        evidence.get("runtime_mount_verified") is True,
        "migration.runtime_mount_verified:not_true",
    )
    require(
        evidence.get("immutable_runtime_mount_activation_pending") is True,
        "migration.immutable_runtime_mount_activation_pending:not_true",
    )
    certificate_activation_pending = evidence.get(
        "immutable_runtime_certificate_activation_pending"
    )
    require(
        isinstance(certificate_activation_pending, bool),
        "migration.immutable_runtime_certificate_activation_pending:not_bool",
    )
    require(
        evidence.get("bootstrap_changed") is False,
        "migration.bootstrap_changed:not_false",
    )
    for field in BOUNDARY:
        require(
            evidence.get(field) is False,
            f"migration.{field}:not_false",
        )
    finalized_head = evidence.get("finalized_head")
    require(
        isinstance(finalized_head, Mapping)
        and set(finalized_head)
        == {"height", "hash", "certificate_hash"},
        "migration.finalized_head:invalid",
    )
    finalized_height = finalized_head.get("height")
    finalized_hash = finalized_head.get("hash")
    finalized_certificate_hash = finalized_head.get("certificate_hash")
    require(
        isinstance(finalized_height, int)
        and not isinstance(finalized_height, bool)
        and finalized_height >= 1,
        "migration.finalized_head.height:invalid",
    )
    require(
        HASH.fullmatch(str(finalized_hash)) is not None,
        "migration.finalized_head.hash:invalid",
    )
    require(
        HASH.fullmatch(str(finalized_certificate_hash)) is not None,
        "migration.finalized_head.certificate_hash:invalid",
    )

    expected_state_volume_ids = [
        item.get("volume_id") for item in state_outputs
    ]
    expected_snapshot_ids = [
        item.get("rollback_snapshot_id") for item in state_outputs
    ]
    for name, expected_values in (
        ("instance_ids", list(instance_ids)),
        ("state_volume_ids", expected_state_volume_ids),
        ("rollback_snapshot_ids", expected_snapshot_ids),
    ):
        actual_values = evidence.get(name)
        require(
            isinstance(actual_values, list)
            and actual_values == expected_values,
            f"migration.{name}:mismatch",
        )
    require(
        [item.get("volume_id") for item in validator_volumes]
        == expected_state_volume_ids,
        "migration.live_state_volume_ids:mismatch",
    )
    require(
        [item.get("rollback_snapshot_id") for item in validator_volumes]
        == expected_snapshot_ids,
        "migration.live_rollback_snapshot_ids:mismatch",
    )

    mappings = evidence.get("validator_mappings")
    require(
        isinstance(mappings, list)
        and len(mappings) == 3
        and all(isinstance(item, Mapping) for item in mappings),
        "migration.validator_mappings:not_exact_three",
    )
    normalized: list[dict[str, str]] = []
    for index, (validator_id, instance_id, signer, state_output) in enumerate(
        zip(
            VALIDATOR_IDS,
            instance_ids,
            signers,
            state_outputs,
            strict=True,
        )
    ):
        mapping = mappings[index]
        state_volume_id = state_output.get("volume_id")
        rollback_snapshot_id = state_output.get("rollback_snapshot_id")
        root_volume_id = instance_root_volumes.get(instance_id)
        require(
            isinstance(state_volume_id, str)
            and VOLUME.fullmatch(state_volume_id) is not None
            and isinstance(rollback_snapshot_id, str)
            and SNAPSHOT.fullmatch(rollback_snapshot_id) is not None
            and isinstance(root_volume_id, str)
            and VOLUME.fullmatch(root_volume_id) is not None,
            f"migration.validator_mappings.{validator_id}:invalid_live_binding",
        )
        expected = {
            "validator_id": validator_id,
            "instance_id": instance_id,
            "signer_arn": signer.get("resource_arn"),
            "state_volume_id": state_volume_id,
            "rollback_snapshot_id": rollback_snapshot_id,
            "root_volume_id": root_volume_id,
        }
        require(
            all(mapping.get(field) == value for field, value in expected.items()),
            f"migration.validator_mappings.{validator_id}:mismatch",
        )
        require(
            snapshot_root_volumes.get(str(rollback_snapshot_id))
            == root_volume_id,
            f"migration.validator_mappings.{validator_id}.snapshot_root:mismatch",
        )
        normalized.append(expected)  # type: ignore[arg-type]
    require(
        len({item["root_volume_id"] for item in normalized}) == 3,
        "migration.validator_mappings.root_volumes:not_distinct",
    )
    return normalized, {
        "height": finalized_height,
        "hash": finalized_hash,
        "certificate_hash": finalized_certificate_hash,
        "immutable_runtime_certificate_activation_pending":
            certificate_activation_pending,
    }


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
        "mode": "public_endpoints",
        "observed_at": report.get("observed_at"),
        "finalized_head": report.get("finalized_head"),
        "checks": checks,
    }


def verify_public_endpoint_outage(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    require(
        report.get("schema_version")
        == "junca-public-endpoint-outage/v1",
        "public_outage.schema_version:mismatch",
    )
    require(
        report.get("status") == "PUBLIC_ENDPOINTS_UNAVAILABLE"
        and report.get("public_services_enabled") is True
        and report.get("public_endpoint_acceptance") is False,
        "public_outage.status:invalid",
    )
    require(
        isinstance(report.get("observed_at"), str)
        and bool(report["observed_at"]),
        "public_outage.observed_at:invalid",
    )
    exit_code = report.get("endpoint_test_exit_code")
    endpoint_test = report.get("endpoint_test")
    require(
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and 1 <= exit_code <= 255
        and isinstance(endpoint_test, Mapping)
        and endpoint_test.get("status") == "FAIL"
        and isinstance(endpoint_test.get("error"), str)
        and bool(endpoint_test["error"]),
        "public_outage.endpoint_test:invalid",
    )
    observations = report.get("observations")
    expected = (
        (
            "health",
            "GET",
            "https://health.jaios-governance.org/health",
        ),
        (
            "explorer",
            "GET",
            "https://explorer.jaios-governance.org/explorer.json",
        ),
        ("rpc", "POST", "https://rpc.jaios-governance.org/"),
    )
    require(
        isinstance(observations, list)
        and len(observations) == 3
        and all(isinstance(item, Mapping) for item in observations),
        "public_outage.observations:not_exact_three",
    )
    failures = 0
    normalized: list[dict[str, Any]] = []
    for item, (name, method, url) in zip(
        observations, expected, strict=True
    ):
        require(
            item.get("name") == name
            and item.get("method") == method
            and item.get("url") == url,
            f"public_outage.{name}:identity_mismatch",
        )
        curl_exit = item.get("curl_exit_code")
        http_status = item.get("http_status")
        body_sha256 = item.get("body_sha256")
        body_base64 = item.get("body_base64")
        stderr = item.get("stderr")
        require(
            isinstance(curl_exit, int)
            and not isinstance(curl_exit, bool)
            and 0 <= curl_exit <= 255
            and isinstance(http_status, int)
            and not isinstance(http_status, bool)
            and 0 <= http_status <= 599
            and SHA256.fullmatch(str(body_sha256)) is not None
            and isinstance(body_base64, str)
            and isinstance(stderr, str),
            f"public_outage.{name}:observation_invalid",
        )
        try:
            body = base64.b64decode(body_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise EvidenceError(
                f"public_outage.{name}:body_base64_invalid"
            ) from exc
        require(
            len(body) <= 65536
            and hashlib.sha256(body).hexdigest() == body_sha256,
            f"public_outage.{name}:body_digest_mismatch",
        )
        if curl_exit != 0 or http_status != 200:
            failures += 1
        normalized.append(dict(item))
    require(failures >= 1, "public_outage:no_failed_observation")
    for field in BOUNDARY:
        require(
            report.get(field) is False,
            f"public_outage.{field}:not_false",
        )
    return {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "public_services_enabled": True,
        "public_endpoint_acceptance": False,
        "observed_at": report["observed_at"],
        "endpoint_test_exit_code": exit_code,
        "endpoint_test": dict(endpoint_test),
        "observations": normalized,
        **BOUNDARY,
    }


def verify_private_validator_health(
    report: Mapping[str, Any],
    instance_ids: Sequence[str],
    signers: Sequence[Mapping[str, str]],
    migration_finality: Mapping[str, Any],
) -> dict[str, Any]:
    require(
        report.get("schema_version")
        == "junca-private-ssm-validator-baseline/v1",
        "private_ssm.schema_version:mismatch",
    )
    require(report.get("status") == "PASS", "private_ssm.status:not_pass")
    require(
        report.get("scope")
        == "Public Testnet Pre-rollout Baseline / Private SSM Read-only",
        "private_ssm.scope:mismatch",
    )
    validators = report.get("validators")
    require(
        isinstance(validators, list)
        and len(validators) == 3
        and all(isinstance(item, Mapping) for item in validators),
        "private_ssm.validators:not_exact_three",
    )
    expected_signer_digests = {
        item["validator_id"]: hashlib.sha256(
            item["resource_arn"].encode("utf-8")
        ).hexdigest()
        for item in signers
    }
    normalized: list[dict[str, Any]] = []
    heads: list[tuple[Any, Any, Any]] = []
    certificates: list[str] = []
    chain_ids: list[Any] = []
    runtime_certificate_states: list[str] = []
    migration_height = migration_finality.get("height")
    migration_hash = migration_finality.get("hash")
    migration_certificate_hash = migration_finality.get("certificate_hash")
    activation_pending = migration_finality.get(
        "immutable_runtime_certificate_activation_pending"
    )
    for validator_id, instance_id, item in zip(
        VALIDATOR_IDS, instance_ids, validators, strict=True
    ):
        require(
            item.get("validator_id") == validator_id
            and item.get("instance_id") == instance_id,
            f"private_ssm.{validator_id}:identity_mismatch",
        )
        health = item.get("health")
        require(
            isinstance(health, Mapping),
            f"private_ssm.{validator_id}.health:missing",
        )
        require(
            health.get("status") == "healthy",
            f"private_ssm.{validator_id}.health:not_healthy",
        )
        require(
            health.get("network") == NETWORK_NOTICE,
            f"private_ssm.{validator_id}.network:mismatch",
        )
        require(
            health.get("validator_id") == validator_id,
            f"private_ssm.{validator_id}.runtime_identity:mismatch",
        )
        height = health.get("head_height")
        head_hash = health.get("head_hash")
        require(
            isinstance(height, int)
            and not isinstance(height, bool)
            and height >= 1,
            f"private_ssm.{validator_id}.head_height:invalid",
        )
        require(
            HASH.fullmatch(str(head_hash)) is not None,
            f"private_ssm.{validator_id}.head_hash:invalid",
        )
        head_timestamp = health.get("head_timestamp")
        require(
            isinstance(head_timestamp, int)
            and not isinstance(head_timestamp, bool)
            and head_timestamp >= 0,
            f"private_ssm.{validator_id}.head_timestamp:invalid",
        )
        require(
            height == migration_height and head_hash == migration_hash,
            f"private_ssm.{validator_id}.migration_head:mismatch",
        )
        require(
            health.get("signer_resource_digest")
            == expected_signer_digests[validator_id],
            f"private_ssm.{validator_id}.signer:mismatch",
        )
        require(
            health.get("private_key_material_accepted") is False,
            f"private_ssm.{validator_id}.private_key_material:not_false",
        )
        for field in BOUNDARY:
            require(
                health.get(field) is False,
                f"private_ssm.{validator_id}.{field}:not_false",
            )

        consensus = health.get("consensus")
        require(
            isinstance(consensus, Mapping)
            and consensus.get("schema_version")
            == "junca-public-testnet-consensus-runtime/v1",
            f"private_ssm.{validator_id}.consensus:missing",
        )
        require(
            consensus.get("head_height") == height
            and consensus.get("required_vote_count") == 3
            and consensus.get("private_key_material_accepted") is False,
            f"private_ssm.{validator_id}.consensus:invalid",
        )
        for field in BOUNDARY:
            require(
                consensus.get(field) is False,
                f"private_ssm.{validator_id}.consensus.{field}:not_false",
            )
        certificate_hash = consensus.get("last_certificate_hash")
        certificate = consensus.get("last_certificate")
        authenticated_vote_count = consensus.get(
            "authenticated_vote_count"
        )
        if certificate is None or certificate_hash is None:
            require(
                certificate is None
                and certificate_hash is None
                and isinstance(authenticated_vote_count, int)
                and not isinstance(authenticated_vote_count, bool)
                and authenticated_vote_count == 0,
                f"private_ssm.{validator_id}.certificate:partial_null",
            )
            require(
                activation_pending is True,
                f"private_ssm.{validator_id}.certificate:"
                "activation_not_pending",
            )
            runtime_certificate_states.append("ACTIVATION_PENDING")
        else:
            require(
                certificate_hash == migration_certificate_hash
                and isinstance(authenticated_vote_count, int)
                and not isinstance(authenticated_vote_count, bool)
                and authenticated_vote_count == 3,
                f"private_ssm.{validator_id}.certificate:binding_mismatch",
            )
            runtime_certificate_states.append("LIVE")
        chain_id = health.get("chain_id")
        require(
            chain_id == CHAIN_ID
            and consensus.get("chain_id") == chain_id,
            f"private_ssm.{validator_id}.chain_id:invalid",
        )
        durable_state = item.get("durable_state")
        require(
            isinstance(durable_state, Mapping)
            and durable_state.get("quick_check") == "ok",
            f"private_ssm.{validator_id}.durable_state:invalid",
        )
        durable_head = durable_state.get("head")
        require(
            isinstance(durable_head, Mapping)
            and durable_head.get("height") == height
            and durable_head.get("block_hash") == head_hash
            and isinstance(durable_head.get("finalized"), int)
            and not isinstance(durable_head.get("finalized"), bool)
            and durable_head.get("finalized") == 1
            and durable_head.get("certificate_hash")
            == migration_certificate_hash,
            f"private_ssm.{validator_id}.durable_head:mismatch",
        )
        serialized_certificate = verify_finality_certificate(
            durable_state.get("certificate"),
            height=height,
            head_hash=head_hash,
            certificate_hash=str(migration_certificate_hash),
            label=f"private_ssm.{validator_id}.durable_certificate",
        )
        if certificate is not None:
            live_serialized = verify_finality_certificate(
                certificate,
                height=height,
                head_hash=head_hash,
                certificate_hash=str(migration_certificate_hash),
                label=f"private_ssm.{validator_id}.certificate",
            )
            require(
                live_serialized == serialized_certificate,
                f"private_ssm.{validator_id}.certificate:"
                "durable_mismatch",
            )
        chain_ids.append(chain_id)
        certificates.append(serialized_certificate)
        heads.append((height, head_hash, head_timestamp))
        normalized.append(
            {
                "validator_id": validator_id,
                "instance_id": instance_id,
                "signer_resource_digest": health.get("signer_resource_digest"),
                "runtime_certificate_state":
                    runtime_certificate_states[-1],
                "durable_certificate_hash":
                    migration_certificate_hash,
            }
        )

    require(len(set(chain_ids)) == 1, "private_ssm.chain_id:mismatch")
    require(len(set(heads)) == 1, "private_ssm.finalized_head:mismatch")
    require(
        len(set(certificates)) == 1,
        "private_ssm.finality_certificate:mismatch",
    )
    height, head_hash, head_timestamp = heads[0]
    return {
        "mode": "private_ssm",
        "scope": report.get("scope"),
        "validator_count": 3,
        "validators": normalized,
        "chain_id": chain_ids[0],
        "finalized_head": {
            "height": height,
            "hash": head_hash,
            "timestamp": head_timestamp,
            "certificate_hash": migration_certificate_hash,
        },
        "immutable_runtime_certificate_activation_pending":
            activation_pending,
        "runtime_certificate_states": runtime_certificate_states,
        "durable_certificate_binding": {
            "height": height,
            "hash": head_hash,
            "certificate_hash": migration_certificate_hash,
            "validator_count": 3,
        },
        "quorum": {
            "signed_power": 3,
            "total_power": 3,
            "validator_ids": list(VALIDATOR_IDS),
        },
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
    endpoints: Mapping[str, Any] | None,
    private_validator_health: Mapping[str, Any] | None,
    public_endpoint_outage: Mapping[str, Any] | None,
    migration_evidence: Mapping[str, Any],
    migration_evidence_sha256: str,
    expected_migration_run_id: str,
    expected_migration_head_sha: str,
    expected_migration_request_sha256: str,
    expected_source_commit: str,
    output_dir: str | Path,
) -> tuple[Path, Path, Path]:
    require(COMMIT.fullmatch(expected_source_commit) is not None, "expected_source_commit:invalid")
    require(
        SHA256.fullmatch(migration_evidence_sha256) is not None,
        "migration_evidence_sha256:invalid",
    )
    binding = verify_candidate(candidate, expected_source_commit)
    image_items = exact_items(images, "Images", 1)
    provenance = verify_image(image_items[0], binding)
    (
        signers,
        previous,
        instance_ids,
        state_outputs,
        public_services_enabled,
    ) = verify_terraform(bootstrap, public)
    require(previous != binding, "runtime.previous:equals_candidate")
    instance_root_volumes = verify_instances(
        instances, instance_ids, previous["ami_id"]
    )
    validator_volumes, snapshot_ids = verify_volumes(volumes, state_outputs, instance_ids)
    snapshot_root_volumes = verify_snapshots(snapshots, snapshot_ids)
    migration_mappings, migration_finality = verify_migration_evidence(
        migration_evidence,
        expected_run_id=expected_migration_run_id,
        expected_head_sha=expected_migration_head_sha,
        expected_request_sha256=expected_migration_request_sha256,
        instance_ids=instance_ids,
        signers=signers,
        state_outputs=state_outputs,
        validator_volumes=validator_volumes,
        instance_root_volumes=instance_root_volumes,
        snapshot_root_volumes=snapshot_root_volumes,
    )
    if public_services_enabled:
        if isinstance(endpoints, Mapping):
            require(
                private_validator_health is None
                and public_endpoint_outage is None,
                "endpoints:conflicting_runtime_readback",
            )
            endpoint_readback = verify_endpoint_acceptance(endpoints)
            baseline_mode = "public_endpoints"
            baseline_schema = (
                "junca-public-explorer-pre-rollout-baseline/v1"
            )
            unsafe_rpc_rejection: bool | str = True
            endpoint_outage = None
            public_endpoint_acceptance = True
        else:
            require(
                isinstance(private_validator_health, Mapping),
                "private_ssm:required_for_public_endpoint_outage",
            )
            require(
                isinstance(public_endpoint_outage, Mapping),
                "public_outage:required_for_private_fallback",
            )
            endpoint_readback = verify_private_validator_health(
                private_validator_health,
                instance_ids,
                signers,
                migration_finality,
            )
            endpoint_outage = verify_public_endpoint_outage(
                public_endpoint_outage
            )
            baseline_mode = "private_ssm"
            baseline_schema = (
                "junca-private-ssm-pre-rollout-baseline/v1"
            )
            unsafe_rpc_rejection = "NOT_APPLICABLE_PRIVATE_SSM"
            public_endpoint_acceptance = False
    else:
        require(
            endpoints is None and public_endpoint_outage is None,
            "private_ssm:unexpected_public_endpoint_evidence",
        )
        require(
            isinstance(private_validator_health, Mapping),
            "private_ssm:required_when_public_services_disabled",
        )
        endpoint_readback = verify_private_validator_health(
            private_validator_health,
            instance_ids,
            signers,
            migration_finality,
        )
        baseline_mode = "private_ssm"
        baseline_schema = "junca-private-ssm-pre-rollout-baseline/v1"
        unsafe_rpc_rejection = "NOT_APPLICABLE_PRIVATE_SSM"
        endpoint_outage = None
        public_endpoint_acceptance = False

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    require(not any(target.iterdir()), "output_dir:not_empty")

    explorer = {
        "schema_version": baseline_schema,
        "baseline_mode": baseline_mode,
        "candidate_accepted": False,
        "status": "BASELINE_VERIFIED",
        "finalized_only": True,
        "read_only": True,
        "unsafe_rpc_rejection": unsafe_rpc_rejection,
        "public_services_enabled": public_services_enabled,
        "public_endpoint_acceptance": public_endpoint_acceptance,
        "public_endpoint_outage": endpoint_outage,
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
        "migration_evidence_sha256": migration_evidence_sha256,
        "migration_execution_binding": {
            "repository": REPOSITORY,
            "run_id": expected_migration_run_id,
            "head_sha": expected_migration_head_sha,
            "migration_request_sha256":
                expected_migration_request_sha256,
        },
        "migration_validator_mappings": migration_mappings,
        "migration_finalized_head": {
            "height": migration_finality["height"],
            "hash": migration_finality["hash"],
            "certificate_hash":
                migration_finality["certificate_hash"],
        },
        "immutable_runtime_certificate_activation_pending":
            migration_finality[
                "immutable_runtime_certificate_activation_pending"
            ],
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
        "baseline_mode": baseline_mode,
        "public_services_enabled": public_services_enabled,
        "public_endpoint_acceptance": public_endpoint_acceptance,
        "public_endpoint_outage": endpoint_outage,
        **binding,
        "ami_provenance": provenance,
        "signer_bindings": signers,
        "previous_runtime": previous,
        "explorer_baseline_sha256": digest(explorer_path),
        "ebs_baseline_sha256": digest(ebs_path),
        "migration_evidence_sha256": migration_evidence_sha256,
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
        paths = collect(
            candidate=read_object(args.candidate_ami),
            bootstrap=read_object(args.bootstrap_outputs),
            public=read_object(args.public_testnet_outputs),
            images=read_object(args.images),
            instances=read_object(args.instances),
            volumes=read_object(args.volumes),
            snapshots=read_object(args.snapshots),
            endpoints=(
                read_object(args.endpoint_acceptance)
                if args.endpoint_acceptance
                else None
            ),
            private_validator_health=(
                read_object(args.private_validator_health)
                if args.private_validator_health
                else None
            ),
            public_endpoint_outage=(
                read_object(args.public_endpoint_outage)
                if args.public_endpoint_outage
                else None
            ),
            migration_evidence=read_object(args.migration_evidence),
            migration_evidence_sha256=digest(args.migration_evidence),
            expected_migration_run_id=args.expected_migration_run_id,
            expected_migration_head_sha=args.expected_migration_head_sha,
            expected_migration_request_sha256=(
                args.expected_migration_request_sha256
            ),
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
