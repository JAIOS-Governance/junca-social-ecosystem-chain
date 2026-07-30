#!/usr/bin/env python3
"""Fail-closed promotion gate for a JUNCA immutable validator runtime."""

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


ACCOUNT_ID = "595710543956"
REGION = "us-east-1"
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")
MAX_PUBLIC_FINALIZED_HEAD_AGE_SECONDS = 120
CANDIDATE_FIELDS = {
    "source_commit",
    "node_artifact_sha256",
    "genesis_sha256",
    "ami_id",
}
DRIFT_FIELDS = {
    "observed_runtime_ami_state",
    "observed_validator_runtimes",
    "observed_runtime_ami_ids",
    "runtime_ami_drift_detected",
    "candidate_ami_preexisting",
    "migration_lineage_state",
    "migration_retained_state_lineage_verified",
    "migration_instance_rotation_detected",
    "migration_root_volume_rotation_detected",
    "migration_original_validator_mappings",
    "migration_current_validator_mappings",
    "migration_retained_state_volume_ids",
    "migration_retained_rollback_snapshot_ids",
    "migration_retained_signer_arns",
}
MANIFEST_FIELDS = CANDIDATE_FIELDS | {
    "schema_version",
    "state",
    "network",
    "notice",
    "request_sha256",
    "migration_evidence_sha256",
    "baseline_mode",
    "public_services_enabled",
    "public_endpoint_acceptance",
    "public_endpoint_outage",
    "ami_provenance",
    "signer_bindings",
    "previous_runtime",
    "explorer_baseline_sha256",
    "ebs_baseline_sha256",
    "release_boundary",
} | DRIFT_FIELDS
EXPLORER_FIELDS = CANDIDATE_FIELDS | {
    "schema_version",
    "baseline_mode",
    "candidate_accepted",
    "status",
    "request_sha256",
    "public_services_enabled",
    "public_endpoint_acceptance",
    "public_endpoint_outage",
    "observed_runtime",
    "finalized_only",
    "read_only",
    "unsafe_rpc_rejection",
    "readback",
    "release_boundary",
} | DRIFT_FIELDS
EBS_FIELDS = CANDIDATE_FIELDS | {
    "schema_version",
    "candidate_accepted",
    "state",
    "request_sha256",
    "migration_evidence_sha256",
    "migration_execution_binding",
    "migration_validator_mappings",
    "migration_finalized_head",
    "immutable_runtime_certificate_activation_pending",
    "observed_runtime",
    "migration_complete",
    "data_loss",
    "validator_volumes",
    "release_boundary",
} | DRIFT_FIELDS
AMI_PROVENANCE_FIELDS = {
    "State",
    "OwnerId",
    "Region",
    "SourceCommit",
    "NodeArtifactSHA256",
    "GenesisSHA256",
    "RequestDigest",
    "RequestSchema",
    "ImageBuilderArn",
    "ParentAMIId",
    "ParentAMIOwnerId",
    "ParentAMIName",
    "ComponentSourceSHA256",
    "DependencyLockSHA256",
    "SupplyChainPolicySHA256",
    "DnfReleasever",
    "Boto3NEVRA",
    "BotocoreNEVRA",
    "MainnetChanged",
    "AssetsMoved",
    "BridgeActivated",
}
AMI_SUPPLY_CHAIN_PROVENANCE = {
    "request_schema": "RequestSchema",
    "image_builder_arn": "ImageBuilderArn",
    "parent_ami_id": "ParentAMIId",
    "parent_ami_owner_id": "ParentAMIOwnerId",
    "parent_ami_name": "ParentAMIName",
    "component_source_sha256": "ComponentSourceSHA256",
    "dependency_lock_sha256": "DependencyLockSHA256",
    "supply_chain_policy_sha256": "SupplyChainPolicySHA256",
    "dnf_releasever": "DnfReleasever",
    "python3_boto3_nevra": "Boto3NEVRA",
    "python3_botocore_nevra": "BotocoreNEVRA",
}
IMAGE_BUILDER_ARN = re.compile(
    r"^arn:aws:imagebuilder:us-east-1:595710543956:"
    r"image/[a-zA-Z0-9_-]+/[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$"
)
PARENT_AMI_NAME = re.compile(
    r"^al2023-ami-2023\.[0-9]+\.[0-9]{8}\.[0-9]+-kernel-"
    r"[0-9]+\.[0-9]+-x86_64$"
)
DNF_RELEASEVER = re.compile(r"^2023\.[0-9]+\.[0-9]{8}$")
RPM_NEVRA = re.compile(
    r"^[a-z0-9][a-z0-9+_.-]*-[0-9]+:"
    r"[A-Za-z0-9][A-Za-z0-9+_.~^%-]*-"
    r"[A-Za-z0-9][A-Za-z0-9+_.~^%-]*\.[a-z0-9_]+$"
)
SIGNER_FIELDS = {"validator_id", "resource_arn"}
VOLUME_FIELDS = {
    "validator_id",
    "volume_id",
    "rollback_snapshot_id",
    "encrypted",
    "volume_type",
    "mount_path",
    "filesystem_verified",
    "state_store_integrity",
    "finality_certificate_recovered",
}
MIGRATION_EXECUTION_FIELDS = {
    "repository",
    "run_id",
    "head_sha",
    "migration_request_sha256",
}
MIGRATION_MAPPING_FIELDS = {
    "validator_id",
    "instance_id",
    "signer_arn",
    "state_volume_id",
    "rollback_snapshot_id",
    "root_volume_id",
}
MIGRATION_HEAD_FIELDS = {"height", "hash", "certificate_hash"}
OBSERVED_RUNTIME_FIELDS = {
    "validator_id",
    "instance_id",
    "image_id",
    "state",
    "terraform_approved_ami",
    "candidate_ami",
    "root_volume_id",
}
PUBLIC_FINALIZED_HEAD_FIELDS = {
    "height",
    "hash",
    "timestamp",
    "state_root",
    "certificate_hash",
}
PUBLIC_EXPLORER_CHECK_FIELDS = {
    "result",
    "finalized_height",
    "finalized_hash",
    "signed_power",
    "total_power",
    "certificate_hash",
    "peer_count",
}
PRIVATE_READBACK_FIELDS = {
    "mode",
    "scope",
    "observed_at",
    "validator_count",
    "chain_id",
    "validators",
    "finalized_head",
    "immutable_runtime_certificate_activation_pending",
    "runtime_certificate_states",
    "durable_certificate_binding",
    "quorum",
}
PRIVATE_VALIDATOR_FIELDS = {
    "validator_id",
    "instance_id",
    "signer_resource_digest",
    "peer_count",
    "durable_timestamp_state",
    "timestamp_schema_tables",
    "runtime_certificate_state",
    "durable_certificate_hash",
}
PRIVATE_FINALIZED_HEAD_FIELDS = {
    "height",
    "hash",
    "timestamp",
    "timestamp_state",
    "certificate_hash",
}
PRIVATE_DURABLE_BINDING_FIELDS = {
    "height",
    "hash",
    "certificate_hash",
    "validator_count",
}
PRIVATE_QUORUM_FIELDS = {
    "signed_power",
    "total_power",
    "validator_ids",
}
SAFE_RPC_METHODS = (
    "eth_blockNumber",
    "eth_chainId",
    "eth_getBlockByNumber",
    "net_peerCount",
    "web3_clientVersion",
)
UNSAFE_RPC_METHODS = (
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "admin_peers",
    "debug_traceBlock",
    "personal_unlockAccount",
    "miner_start",
    "junca_health",
    "junca_propose",
    "junca_submitVote",
    "junca_broadcastVote",
)
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
INSTANCE = re.compile(r"i-[0-9a-f]{8,17}")
VOLUME = re.compile(r"vol-[0-9a-f]{8,17}")
SNAPSHOT = re.compile(r"snap-[0-9a-f]{8,17}")
HASH = re.compile(r"0x[0-9a-f]{64}")
HEX_QUANTITY = re.compile(r"0x[0-9a-f]+")


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


def _exact_keys(
    source: Mapping[str, Any],
    expected: set[str],
    label: str,
    failures: list[str],
) -> None:
    if set(source) != expected:
        failures.append(f"{label}.keys:not_exact")


def _boundary(source: Mapping[str, Any], name: str, failures: list[str]) -> None:
    boundary = source.get("release_boundary")
    if not isinstance(boundary, Mapping):
        failures.append(f"{name}.release_boundary:missing")
        return
    _exact_keys(
        boundary,
        set(BOUNDARY_FIELDS),
        f"{name}.release_boundary",
        failures,
    )
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


def _valid_utc_observed_at(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _utc_observed_epoch(value: Any) -> int | None:
    if not _valid_utc_observed_at(value):
        return None
    assert isinstance(value, str)
    return int(
        datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).timestamp()
    )


def _public_endpoint_baseline(
    explorer: Mapping[str, Any], failures: list[str]
) -> None:
    readback = explorer.get("readback")
    if not isinstance(readback, Mapping):
        failures.append("public_endpoints.readback:missing")
        return
    _exact_keys(
        readback,
        {"mode", "observed_at", "finalized_head", "checks"},
        "public_endpoints.readback",
        failures,
    )
    if (
        readback.get("mode") != "public_endpoints"
        or not _valid_utc_observed_at(readback.get("observed_at"))
    ):
        failures.append("public_endpoints.readback:invalid")

    finalized = readback.get("finalized_head")
    if not isinstance(finalized, Mapping):
        failures.append("public_endpoints.finalized_head:missing")
    else:
        _exact_keys(
            finalized,
            PUBLIC_FINALIZED_HEAD_FIELDS,
            "public_endpoints.finalized_head",
            failures,
        )
        if (
            not isinstance(finalized.get("height"), int)
            or isinstance(finalized.get("height"), bool)
            or finalized.get("height", 0) < 1
            or HASH.fullmatch(str(finalized.get("hash"))) is None
            or HEX_QUANTITY.fullmatch(
                str(finalized.get("timestamp"))
            )
            is None
            or int(str(finalized.get("timestamp")), 16) <= 0
            or HASH.fullmatch(str(finalized.get("state_root"))) is None
            or HASH.fullmatch(str(finalized.get("certificate_hash"))) is None
        ):
            failures.append("public_endpoints.finalized_head:invalid")
        else:
            observed_epoch = _utc_observed_epoch(
                readback.get("observed_at")
            )
            finalized_epoch = int(
                str(finalized.get("timestamp")),
                16,
            )
            if (
                observed_epoch is None
                or not 0
                <= observed_epoch - finalized_epoch
                <= MAX_PUBLIC_FINALIZED_HEAD_AGE_SECONDS
            ):
                failures.append(
                    "public_endpoints.finalized_head:stale_or_future"
                )

    checks = readback.get("checks")
    if not isinstance(checks, Mapping):
        failures.append("public_endpoints.checks:missing")
        return
    _exact_keys(
        checks,
        {"health", "explorer", "safe_rpc", "unsafe_rpc_rejection"},
        "public_endpoints.checks",
        failures,
    )
    if checks.get("health") != "PASS":
        failures.append("public_endpoints.health:not_pass")

    explorer_check = checks.get("explorer")
    if not isinstance(explorer_check, Mapping):
        failures.append("public_endpoints.explorer_check:missing")
    else:
        _exact_keys(
            explorer_check,
            PUBLIC_EXPLORER_CHECK_FIELDS,
            "public_endpoints.explorer_check",
            failures,
        )
        if (
            explorer_check.get("result") != "PASS"
            or explorer_check.get("signed_power") != 3
            or explorer_check.get("total_power") != 3
            or not isinstance(explorer_check.get("peer_count"), int)
            or isinstance(explorer_check.get("peer_count"), bool)
            or explorer_check.get("peer_count") != 2
            or not isinstance(finalized, Mapping)
            or explorer_check.get("finalized_height")
            != finalized.get("height")
            or explorer_check.get("finalized_hash") != finalized.get("hash")
            or explorer_check.get("certificate_hash")
            != finalized.get("certificate_hash")
        ):
            failures.append("public_endpoints.explorer_check:invalid")

    for field, methods in (
        ("safe_rpc", list(SAFE_RPC_METHODS)),
        ("unsafe_rpc_rejection", list(UNSAFE_RPC_METHODS)),
    ):
        check = checks.get(field)
        if not isinstance(check, Mapping):
            failures.append(f"public_endpoints.{field}:missing")
            continue
        _exact_keys(
            check,
            {"result", "methods"},
            f"public_endpoints.{field}",
            failures,
        )
        if check.get("result") != "PASS" or check.get("methods") != methods:
            failures.append(f"public_endpoints.{field}:invalid")


def _drift_and_lineage(
    manifest: Mapping[str, Any],
    explorer: Mapping[str, Any],
    ebs: Mapping[str, Any],
    expected: tuple[Any, Any, Any, Any],
    failures: list[str],
) -> None:
    for field in DRIFT_FIELDS:
        if explorer.get(field) != manifest.get(field):
            failures.append(f"explorer.{field}:mismatch")
        if ebs.get(field) != manifest.get(field):
            failures.append(f"ebs.{field}:mismatch")

    if (
        manifest.get("observed_runtime_ami_state")
        != "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE"
    ):
        failures.append("drift.observed_runtime_ami_state:invalid")
    if manifest.get("candidate_ami_preexisting") is not False:
        failures.append("drift.candidate_ami_preexisting:not_false")

    runtimes = manifest.get("observed_validator_runtimes")
    if (
        not isinstance(runtimes, list)
        or len(runtimes) != 3
        or any(not isinstance(item, Mapping) for item in runtimes)
    ):
        failures.append("drift.observed_validator_runtimes:not_exact_three")
        runtimes = []
    else:
        for item in runtimes:
            _exact_keys(
                item,
                OBSERVED_RUNTIME_FIELDS,
                "drift.observed_validator_runtime",
                failures,
            )
        validator_ids = [item.get("validator_id") for item in runtimes]
        instance_ids = [item.get("instance_id") for item in runtimes]
        image_ids = [item.get("image_id") for item in runtimes]
        root_volume_ids = [item.get("root_volume_id") for item in runtimes]
        if (
            validator_ids != list(VALIDATOR_IDS)
            or len(set(instance_ids)) != 3
            or any(
                INSTANCE.fullmatch(str(value)) is None
                for value in instance_ids
            )
            or any(AMI.fullmatch(str(value)) is None for value in image_ids)
            or expected[3] in image_ids
            or len(set(root_volume_ids)) != 3
            or any(
                VOLUME.fullmatch(str(value)) is None
                for value in root_volume_ids
            )
            or any(item.get("state") != "running" for item in runtimes)
            or any(
                not isinstance(item.get("terraform_approved_ami"), bool)
                for item in runtimes
            )
            or any(item.get("candidate_ami") is not False for item in runtimes)
            or any(
                item.get("terraform_approved_ami")
                is not (
                    item.get("image_id")
                    == manifest.get("previous_runtime", {}).get("ami_id")
                )
                for item in runtimes
            )
        ):
            failures.append("drift.observed_validator_runtimes:invalid")
        if manifest.get("observed_runtime_ami_ids") != sorted(set(image_ids)):
            failures.append("drift.observed_runtime_ami_ids:mismatch")
        if manifest.get("runtime_ami_drift_detected") is not any(
            item.get("terraform_approved_ami") is False for item in runtimes
        ):
            failures.append("drift.runtime_ami_drift_detected:mismatch")

    if (
        manifest.get("migration_lineage_state")
        != "RETAINED_STATE_LINEAGE_VERIFIED"
        or manifest.get("migration_retained_state_lineage_verified") is not True
    ):
        failures.append("lineage.state:not_verified")

    original = manifest.get("migration_original_validator_mappings")
    current = manifest.get("migration_current_validator_mappings")
    mappings: list[tuple[str, list[Mapping[str, Any]]]] = []
    for label, value in (("original", original), ("current", current)):
        if (
            not isinstance(value, list)
            or len(value) != 3
            or any(not isinstance(item, Mapping) for item in value)
        ):
            failures.append(f"lineage.{label}:not_exact_three")
            continue
        normalized = list(value)
        mappings.append((label, normalized))
        for item in normalized:
            _exact_keys(
                item,
                MIGRATION_MAPPING_FIELDS,
                f"lineage.{label}.mapping",
                failures,
            )
        validator_ids = [item.get("validator_id") for item in normalized]
        instance_ids = [item.get("instance_id") for item in normalized]
        signer_arns = [item.get("signer_arn") for item in normalized]
        state_volume_ids = [
            item.get("state_volume_id") for item in normalized
        ]
        snapshots = [
            item.get("rollback_snapshot_id") for item in normalized
        ]
        root_volume_ids = [item.get("root_volume_id") for item in normalized]
        signer_prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
        if (
            validator_ids != list(VALIDATOR_IDS)
            or len(set(instance_ids)) != 3
            or any(
                INSTANCE.fullmatch(str(value)) is None
                for value in instance_ids
            )
            or len(set(signer_arns)) != 3
            or any(
                not isinstance(value, str)
                or not value.startswith(signer_prefix)
                for value in signer_arns
            )
            or len(set(state_volume_ids)) != 3
            or any(
                VOLUME.fullmatch(str(value)) is None
                for value in state_volume_ids
            )
            or len(set(snapshots)) != 3
            or any(
                SNAPSHOT.fullmatch(str(value)) is None for value in snapshots
            )
            or len(set(root_volume_ids)) != 3
            or any(
                VOLUME.fullmatch(str(value)) is None
                for value in root_volume_ids
            )
        ):
            failures.append(f"lineage.{label}:invalid")

    if len(mappings) != 2:
        return
    original_items = mappings[0][1]
    current_items = mappings[1][1]
    retained_fields = (
        "validator_id",
        "signer_arn",
        "state_volume_id",
        "rollback_snapshot_id",
    )
    if any(
        any(
            old.get(field) != new.get(field) for field in retained_fields
        )
        for old, new in zip(original_items, current_items, strict=True)
    ):
        failures.append("lineage.retained_identity:mismatch")
    instance_rotation = any(
        old.get("instance_id") != new.get("instance_id")
        for old, new in zip(original_items, current_items, strict=True)
    )
    root_rotation = any(
        old.get("root_volume_id") != new.get("root_volume_id")
        for old, new in zip(original_items, current_items, strict=True)
    )
    if manifest.get("migration_instance_rotation_detected") is not (
        instance_rotation
    ):
        failures.append("lineage.instance_rotation:mismatch")
    if manifest.get("migration_root_volume_rotation_detected") is not (
        root_rotation
    ):
        failures.append("lineage.root_volume_rotation:mismatch")

    retained_state = [item.get("state_volume_id") for item in current_items]
    retained_snapshots = [
        item.get("rollback_snapshot_id") for item in current_items
    ]
    retained_signers = [item.get("signer_arn") for item in current_items]
    if manifest.get("migration_retained_state_volume_ids") != retained_state:
        failures.append("lineage.retained_state_volume_ids:mismatch")
    if (
        manifest.get("migration_retained_rollback_snapshot_ids")
        != retained_snapshots
    ):
        failures.append("lineage.retained_rollback_snapshot_ids:mismatch")
    if manifest.get("migration_retained_signer_arns") != retained_signers:
        failures.append("lineage.retained_signer_arns:mismatch")
    if runtimes and (
        [item.get("instance_id") for item in current_items]
        != [item.get("instance_id") for item in runtimes]
        or [item.get("root_volume_id") for item in current_items]
        != [item.get("root_volume_id") for item in runtimes]
    ):
        failures.append("lineage.observed_runtime:mismatch")
    migration_mappings = ebs.get("migration_validator_mappings")
    if migration_mappings != current_items:
        failures.append("lineage.ebs_migration_mappings:mismatch")

    signers = manifest.get("signer_bindings")
    if isinstance(signers, list):
        signer_values = [
            item.get("resource_arn")
            for item in signers
            if isinstance(item, Mapping)
        ]
        if retained_signers != signer_values:
            failures.append("lineage.signer_bindings:mismatch")
    volumes = ebs.get("validator_volumes")
    if isinstance(volumes, list):
        state_values = [
            item.get("volume_id")
            for item in volumes
            if isinstance(item, Mapping)
        ]
        snapshot_values = [
            item.get("rollback_snapshot_id")
            for item in volumes
            if isinstance(item, Mapping)
        ]
        if retained_state != state_values:
            failures.append("lineage.validator_state_volumes:mismatch")
        if retained_snapshots != snapshot_values:
            failures.append("lineage.validator_snapshots:mismatch")


def _private_ssm_baseline(
    manifest: Mapping[str, Any],
    explorer: Mapping[str, Any],
    failures: list[str],
) -> None:
    readback = explorer.get("readback")
    if not isinstance(readback, Mapping):
        failures.append("private_ssm.readback:missing")
        return
    _exact_keys(
        readback,
        PRIVATE_READBACK_FIELDS,
        "private_ssm.readback",
        failures,
    )
    if (
        readback.get("mode") != "private_ssm"
        or readback.get("scope")
        != "Public Testnet Pre-rollout Baseline / Private SSM Read-only"
        or not _valid_utc_observed_at(readback.get("observed_at"))
        or readback.get("validator_count") != 3
        or readback.get("chain_id") != 20260723
        or readback.get(
            "immutable_runtime_certificate_activation_pending"
        )
        is not True
        or readback.get("runtime_certificate_states")
        != ["ACTIVATION_PENDING"] * 3
    ):
        failures.append("private_ssm.readback:invalid")
    validators = readback.get("validators")
    timestamp_states: list[Any] = []
    timestamp_schema_tables: list[Any] = []
    runtime_certificate_states: list[Any] = []
    durable_certificate_hashes: list[Any] = []
    if not isinstance(validators, list):
        failures.append("private_ssm.validators:missing")
    else:
        for item in validators:
            if isinstance(item, Mapping):
                _exact_keys(
                    item,
                    PRIVATE_VALIDATOR_FIELDS,
                    "private_ssm.validator",
                    failures,
                )
        identities = [
            item.get("validator_id")
            for item in validators
            if isinstance(item, Mapping)
        ]
        instance_ids = [
            item.get("instance_id")
            for item in validators
            if isinstance(item, Mapping)
        ]
        signer_digests = [
            item.get("signer_resource_digest")
            for item in validators
            if isinstance(item, Mapping)
        ]
        peer_counts = [
            item.get("peer_count")
            for item in validators
            if isinstance(item, Mapping)
        ]
        signer_bindings = manifest.get("signer_bindings")
        signer_by_validator = (
            {
                item.get("validator_id"): item.get("resource_arn")
                for item in signer_bindings
                if isinstance(item, Mapping)
            }
            if isinstance(signer_bindings, list)
            else {}
        )
        expected_signer_digests = [
            hashlib.sha256(signer_by_validator[validator_id].encode()).hexdigest()
            for validator_id in VALIDATOR_IDS
            if isinstance(signer_by_validator.get(validator_id), str)
        ]
        timestamp_states = [
            item.get("durable_timestamp_state")
            for item in validators
            if isinstance(item, Mapping)
        ]
        timestamp_schema_tables = [
            item.get("timestamp_schema_tables")
            for item in validators
            if isinstance(item, Mapping)
        ]
        runtime_certificate_states = [
            item.get("runtime_certificate_state")
            for item in validators
            if isinstance(item, Mapping)
        ]
        durable_certificate_hashes = [
            item.get("durable_certificate_hash")
            for item in validators
            if isinstance(item, Mapping)
        ]
        if (
            len(validators) != 3
            or identities != list(VALIDATOR_IDS)
            or len(set(instance_ids)) != 3
            or any(
                INSTANCE.fullmatch(str(instance_id)) is None
                for instance_id in instance_ids
            )
            or len(set(signer_digests)) != 3
            or any(
                SHA256.fullmatch(str(signer_digest)) is None
                for signer_digest in signer_digests
            )
            or runtime_certificate_states != ["ACTIVATION_PENDING"] * 3
        ):
            failures.append("private_ssm.validators:not_exact_three")
        if signer_digests != expected_signer_digests:
            failures.append(
                "private_ssm.validators.signer_resource_digest:mismatch"
            )
        if (
            len(peer_counts) != 3
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value != 2
                for value in peer_counts
            )
        ):
            failures.append("private_ssm.peer_count:not_exact_two")
    finalized = readback.get("finalized_head")
    if not isinstance(finalized, Mapping):
        failures.append("private_ssm.finalized_head:missing")
    else:
        _exact_keys(
            finalized,
            PRIVATE_FINALIZED_HEAD_FIELDS,
            "private_ssm.finalized_head",
            failures,
        )
        if (
            not isinstance(finalized.get("height"), int)
            or isinstance(finalized.get("height"), bool)
            or finalized.get("height", 0) < 1
            or HASH.fullmatch(str(finalized.get("hash"))) is None
            or HASH.fullmatch(str(finalized.get("certificate_hash"))) is None
        ):
            failures.append("private_ssm.finalized_head:invalid")
        if durable_certificate_hashes != [
            finalized.get("certificate_hash")
        ] * 3:
            failures.append(
                "private_ssm.validators.durable_certificate_hash:mismatch"
            )
        timestamp_state = finalized.get("timestamp_state")
        timestamp = finalized.get("timestamp")
        expected_tables: list[str] | None
        if timestamp_state == "DURABLE_PERSISTED":
            expected_tables = [
                "block_timestamps",
                "blocks",
                "finality_certificates",
                "metadata",
            ]
            if (
                not isinstance(timestamp, int)
                or isinstance(timestamp, bool)
                or timestamp <= 0
            ):
                failures.append(
                    "private_ssm.finalized_head.timestamp:invalid"
                )
            observed_epoch = _utc_observed_epoch(
                readback.get("observed_at")
            )
            if (
                observed_epoch is None
                or not isinstance(timestamp, int)
                or isinstance(timestamp, bool)
                or not 0
                <= observed_epoch - timestamp
                <= MAX_PUBLIC_FINALIZED_HEAD_AGE_SECONDS
            ):
                failures.append(
                    "private_ssm.finalized_head:stale_or_future"
                )
        elif timestamp_state == "LEGACY_NOT_PERSISTED":
            expected_tables = [
                "blocks",
                "finality_certificates",
                "metadata",
            ]
            if timestamp is not None:
                failures.append(
                    "private_ssm.finalized_head.legacy_timestamp:not_null"
                )
            failures.append(
                "private_ssm.finalized_head:freshness_unverifiable"
            )
        else:
            expected_tables = None
            failures.append(
                "private_ssm.finalized_head.timestamp_state:invalid"
            )
        if (
            expected_tables is not None
            and (
                timestamp_states != [timestamp_state] * 3
                or timestamp_schema_tables != [expected_tables] * 3
            )
        ):
            failures.append(
                "private_ssm.validators.timestamp_schema:not_exact_three"
            )
    quorum = readback.get("quorum")
    if not isinstance(quorum, Mapping):
        failures.append("private_ssm.quorum:missing")
    else:
        _exact_keys(
            quorum,
            PRIVATE_QUORUM_FIELDS,
            "private_ssm.quorum",
            failures,
        )
        if (
            quorum.get("signed_power") != 3
            or quorum.get("total_power") != 3
            or quorum.get("validator_ids") != list(VALIDATOR_IDS)
        ):
            failures.append("private_ssm.quorum:not_exact_three")

    durable_binding = readback.get("durable_certificate_binding")
    if not isinstance(durable_binding, Mapping):
        failures.append("private_ssm.durable_certificate_binding:missing")
    else:
        _exact_keys(
            durable_binding,
            PRIVATE_DURABLE_BINDING_FIELDS,
            "private_ssm.durable_certificate_binding",
            failures,
        )
        if (
            not isinstance(finalized, Mapping)
            or durable_binding.get("height") != finalized.get("height")
            or durable_binding.get("hash") != finalized.get("hash")
            or durable_binding.get("certificate_hash")
            != finalized.get("certificate_hash")
            or durable_binding.get("validator_count") != 3
        ):
            failures.append(
                "private_ssm.durable_certificate_binding:mismatch"
            )


def _public_endpoint_outage(
    outage: Mapping[str, Any], failures: list[str]
) -> None:
    _exact_keys(
        outage,
        {
            "schema_version",
            "status",
            "public_services_enabled",
            "public_endpoint_acceptance",
            "observed_at",
            "endpoint_test_exit_code",
            "endpoint_test",
            "observations",
            *BOUNDARY_FIELDS,
        },
        "public_outage",
        failures,
    )
    if (
        outage.get("schema_version")
        != "junca-public-endpoint-outage/v1"
        or outage.get("status") != "PUBLIC_ENDPOINTS_UNAVAILABLE"
        or outage.get("public_services_enabled") is not True
        or outage.get("public_endpoint_acceptance") is not False
    ):
        failures.append("public_outage.status:invalid")
    endpoint_test = outage.get("endpoint_test")
    exit_code = outage.get("endpoint_test_exit_code")
    if (
        not isinstance(outage.get("observed_at"), str)
        or not outage.get("observed_at")
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or not 1 <= exit_code <= 255
        or not isinstance(endpoint_test, Mapping)
        or endpoint_test.get("status") != "FAIL"
        or not isinstance(endpoint_test.get("error"), str)
        or not endpoint_test.get("error")
    ):
        failures.append("public_outage.endpoint_test:invalid")
    if isinstance(endpoint_test, Mapping):
        _exact_keys(
            endpoint_test,
            {"status", "error"},
            "public_outage.endpoint_test",
            failures,
        )
    observations = outage.get("observations")
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
    if (
        not isinstance(observations, list)
        or len(observations) != 3
        or any(not isinstance(item, Mapping) for item in observations)
    ):
        failures.append("public_outage.observations:not_exact_three")
    else:
        failed = 0
        for item, (name, method, url) in zip(
            observations, expected, strict=True
        ):
            _exact_keys(
                item,
                {
                    "name",
                    "method",
                    "url",
                    "curl_exit_code",
                    "http_status",
                    "body_sha256",
                    "body_base64",
                    "stderr",
                },
                f"public_outage.{name}",
                failures,
            )
            curl_exit = item.get("curl_exit_code")
            http_status = item.get("http_status")
            body_sha256 = item.get("body_sha256")
            body_base64 = item.get("body_base64")
            if (
                item.get("name") != name
                or item.get("method") != method
                or item.get("url") != url
                or not isinstance(curl_exit, int)
                or isinstance(curl_exit, bool)
                or not 0 <= curl_exit <= 255
                or not isinstance(http_status, int)
                or isinstance(http_status, bool)
                or not 0 <= http_status <= 599
                or SHA256.fullmatch(str(body_sha256)) is None
                or not isinstance(body_base64, str)
                or not isinstance(item.get("stderr"), str)
            ):
                failures.append(f"public_outage.{name}:invalid")
                continue
            try:
                body = base64.b64decode(body_base64, validate=True)
            except (ValueError, binascii.Error):
                failures.append(f"public_outage.{name}:body_base64_invalid")
                continue
            if (
                len(body) > 65536
                or hashlib.sha256(body).hexdigest() != body_sha256
            ):
                failures.append(f"public_outage.{name}:body_digest_mismatch")
                continue
            if curl_exit != 0 or http_status != 200:
                failed += 1
        if failed < 1:
            failures.append("public_outage:no_failed_observation")
    for field in BOUNDARY_FIELDS:
        if outage.get(field) is not False:
            failures.append(f"public_outage.{field}:not_false")


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
    _exact_keys(manifest, MANIFEST_FIELDS, "manifest", failures)
    _exact_keys(explorer, EXPLORER_FIELDS, "explorer", failures)
    _exact_keys(ebs, EBS_FIELDS, "ebs", failures)
    expected = (
        expected_source_commit,
        expected_artifact_sha256,
        expected_genesis_sha256,
        manifest.get("ami_id"),
    )
    request_sha256 = manifest.get("request_sha256")
    migration_evidence_sha256 = manifest.get("migration_evidence_sha256")
    baseline_mode = manifest.get("baseline_mode")
    public_services_enabled = manifest.get("public_services_enabled")
    public_endpoint_acceptance = manifest.get(
        "public_endpoint_acceptance"
    )
    public_endpoint_outage = manifest.get("public_endpoint_outage")
    if not SHA256.fullmatch(str(request_sha256)):
        failures.append("manifest.request_sha256:invalid")
    if explorer.get("request_sha256") != request_sha256:
        failures.append("explorer.request_sha256:mismatch")
    if ebs.get("request_sha256") != request_sha256:
        failures.append("ebs.request_sha256:mismatch")
    if not SHA256.fullmatch(str(migration_evidence_sha256)):
        failures.append("manifest.migration_evidence_sha256:invalid")
    if ebs.get("migration_evidence_sha256") != migration_evidence_sha256:
        failures.append("ebs.migration_evidence_sha256:mismatch")

    if (
        manifest.get("schema_version")
        != "junca-runtime-pre-rollout-baseline/v1"
    ):
        failures.append("manifest.schema_version:mismatch")
    if manifest.get("state") != "PRE_ROLLOUT_BASELINE_VERIFIED":
        failures.append("manifest.state:not_baseline_verified")
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
        _exact_keys(
            provenance,
            AMI_PROVENANCE_FIELDS,
            "manifest.ami_provenance",
            failures,
        )
        required_tags = {
            "State": "available",
            "OwnerId": ACCOUNT_ID,
            "Region": REGION,
            "SourceCommit": expected_source_commit,
            "NodeArtifactSHA256": expected_artifact_sha256,
            "GenesisSHA256": expected_genesis_sha256,
            "RequestDigest": request_sha256,
            "RequestSchema":
                "junca-validator-ami-build-request/v2",
            "MainnetChanged": "false",
            "AssetsMoved": "false",
            "BridgeActivated": "false",
        }
        for field, value in required_tags.items():
            if provenance.get(field) != value:
                failures.append(f"manifest.ami_provenance.{field}:mismatch")
        if not IMAGE_BUILDER_ARN.fullmatch(
            str(provenance.get("ImageBuilderArn", ""))
        ):
            failures.append(
                "manifest.ami_provenance.ImageBuilderArn:invalid"
            )
        if not AMI.fullmatch(
            str(provenance.get("ParentAMIId", ""))
        ):
            failures.append(
                "manifest.ami_provenance.ParentAMIId:invalid"
            )
        if provenance.get("ParentAMIOwnerId") != "137112412989":
            failures.append(
                "manifest.ami_provenance.ParentAMIOwnerId:mismatch"
            )
        parent_ami_name = str(provenance.get("ParentAMIName", ""))
        dnf_releasever = str(provenance.get("DnfReleasever", ""))
        if not PARENT_AMI_NAME.fullmatch(parent_ami_name):
            failures.append(
                "manifest.ami_provenance.ParentAMIName:invalid"
            )
        if (
            not DNF_RELEASEVER.fullmatch(dnf_releasever)
            or not parent_ami_name.startswith(
                f"al2023-ami-{dnf_releasever}."
            )
        ):
            failures.append(
                "manifest.ami_provenance.DnfReleasever:mismatch"
            )
        for field in (
            "ComponentSourceSHA256",
            "DependencyLockSHA256",
            "SupplyChainPolicySHA256",
        ):
            if not SHA256.fullmatch(str(provenance.get(field, ""))):
                failures.append(
                    f"manifest.ami_provenance.{field}:invalid"
                )
        for field, package in (
            ("Boto3NEVRA", "python3-boto3"),
            ("BotocoreNEVRA", "python3-botocore"),
        ):
            value = str(provenance.get(field, ""))
            if (
                not RPM_NEVRA.fullmatch(value)
                or not value.startswith(f"{package}-")
            ):
                failures.append(
                    f"manifest.ami_provenance.{field}:invalid"
                )

    signers = manifest.get("signer_bindings")
    signer_prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    if not isinstance(signers, list):
        failures.append("manifest.signer_bindings:missing")
    else:
        for item in signers:
            if isinstance(item, Mapping):
                _exact_keys(
                    item,
                    SIGNER_FIELDS,
                    "manifest.signer_binding",
                    failures,
                )
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
        _exact_keys(
            previous,
            CANDIDATE_FIELDS,
            "manifest.previous_runtime",
            failures,
        )
        previous_binding = _candidate_binding(previous)
        if previous_binding == expected:
            failures.append("manifest.previous_runtime:equals_candidate")
        if (
            COMMIT.fullmatch(str(previous.get("source_commit"))) is None
            or SHA256.fullmatch(
                str(previous.get("node_artifact_sha256"))
            )
            is None
            or SHA256.fullmatch(str(previous.get("genesis_sha256"))) is None
            or AMI.fullmatch(str(previous.get("ami_id"))) is None
        ):
            failures.append("manifest.previous_runtime:incomplete")

    if manifest.get("explorer_baseline_sha256") != explorer_evidence_sha256:
        failures.append("manifest.explorer_baseline_sha256:mismatch")
    if manifest.get("ebs_baseline_sha256") != ebs_evidence_sha256:
        failures.append("manifest.ebs_baseline_sha256:mismatch")

    if baseline_mode not in ("public_endpoints", "private_ssm"):
        failures.append("manifest.baseline_mode:invalid")
    if explorer.get("baseline_mode") != baseline_mode:
        failures.append("explorer.baseline_mode:mismatch")
    if explorer.get("public_services_enabled") is not public_services_enabled:
        failures.append("explorer.public_services_enabled:mismatch")
    if (
        explorer.get("public_endpoint_acceptance")
        is not public_endpoint_acceptance
    ):
        failures.append("explorer.public_endpoint_acceptance:mismatch")
    if explorer.get("public_endpoint_outage") != public_endpoint_outage:
        failures.append("explorer.public_endpoint_outage:mismatch")
    expected_explorer_schema = (
        "junca-public-explorer-pre-rollout-baseline/v1"
        if baseline_mode == "public_endpoints"
        else "junca-private-ssm-pre-rollout-baseline/v1"
    )
    if explorer.get("schema_version") != expected_explorer_schema:
        failures.append("explorer.schema_version:not_pre_rollout_baseline")
    if (
        explorer.get("candidate_accepted") is not False
        or explorer.get("status") != "BASELINE_VERIFIED"
    ):
        failures.append("explorer.baseline:not_verified")
    if explorer.get("finalized_only") is not True:
        failures.append("explorer.finalized_only:not_true")
    if explorer.get("read_only") is not True:
        failures.append("explorer.read_only:not_true")
    if baseline_mode == "public_endpoints":
        if (
            public_services_enabled is not True
            or public_endpoint_acceptance is not True
            or public_endpoint_outage is not None
        ):
            failures.append("public_endpoints.acceptance_binding:invalid")
        if explorer.get("unsafe_rpc_rejection") is not True:
            failures.append("explorer.unsafe_rpc_rejection:not_true")
        _public_endpoint_baseline(explorer, failures)
    elif baseline_mode == "private_ssm":
        if public_endpoint_acceptance is not False:
            failures.append("private_ssm.public_endpoint_acceptance:not_false")
        if public_services_enabled is True:
            if isinstance(public_endpoint_outage, Mapping):
                _public_endpoint_outage(public_endpoint_outage, failures)
            else:
                failures.append("private_ssm.public_outage:missing")
        elif public_services_enabled is False:
            if public_endpoint_outage is not None:
                failures.append("private_ssm.public_outage:unexpected")
        else:
            failures.append("private_ssm.public_services_enabled:invalid")
        if (
            explorer.get("unsafe_rpc_rejection")
            != "NOT_APPLICABLE_PRIVATE_SSM"
        ):
            failures.append("private_ssm.unsafe_rpc_rejection:invalid")
        _private_ssm_baseline(manifest, explorer, failures)
    if _candidate_binding(explorer) != expected:
        failures.append("explorer.candidate_binding:mismatch")
    observed_explorer = explorer.get("observed_runtime")
    if (
        not isinstance(observed_explorer, Mapping)
        or not all(_candidate_binding(observed_explorer))
        or _candidate_binding(observed_explorer) == expected
    ):
        failures.append("explorer.observed_runtime:not_distinct_baseline")
    elif isinstance(observed_explorer, Mapping):
        _exact_keys(
            observed_explorer,
            CANDIDATE_FIELDS,
            "explorer.observed_runtime",
            failures,
        )
        if observed_explorer != previous:
            failures.append("explorer.observed_runtime:mismatch")

    if (
        ebs.get("schema_version")
        != "junca-validator-ebs-pre-rollout-baseline/v1"
    ):
        failures.append("ebs.schema_version:mismatch")
    if (
        ebs.get("candidate_accepted") is not False
        or ebs.get("state") != "BASELINE_VERIFIED"
    ):
        failures.append("ebs.state:not_baseline_verified")
    if ebs.get("migration_complete") is not True:
        failures.append("ebs.migration_complete:not_true")
    if ebs.get("data_loss") is not False:
        failures.append("ebs.data_loss:not_false")
    if _candidate_binding(ebs) != expected:
        failures.append("ebs.candidate_binding:mismatch")
    observed_ebs = ebs.get("observed_runtime")
    if (
        not isinstance(observed_ebs, Mapping)
        or not all(_candidate_binding(observed_ebs))
        or _candidate_binding(observed_ebs) == expected
    ):
        failures.append("ebs.observed_runtime:not_distinct_baseline")
    elif isinstance(observed_ebs, Mapping):
        _exact_keys(
            observed_ebs,
            CANDIDATE_FIELDS,
            "ebs.observed_runtime",
            failures,
        )
        if observed_ebs != previous:
            failures.append("ebs.observed_runtime:mismatch")
    migration_execution = ebs.get("migration_execution_binding")
    if not isinstance(migration_execution, Mapping):
        failures.append("ebs.migration_execution_binding:missing")
    else:
        _exact_keys(
            migration_execution,
            MIGRATION_EXECUTION_FIELDS,
            "ebs.migration_execution_binding",
            failures,
        )
        if (
            not isinstance(migration_execution.get("repository"), str)
            or migration_execution.get("repository")
            != "JAIOS-Governance/junca-social-ecosystem-chain"
            or not isinstance(migration_execution.get("run_id"), str)
            or re.fullmatch(
                r"[1-9][0-9]*", migration_execution.get("run_id", "")
            )
            is None
            or not isinstance(migration_execution.get("head_sha"), str)
            or COMMIT.fullmatch(
                migration_execution.get("head_sha", "")
            )
            is None
            or not isinstance(
                migration_execution.get("migration_request_sha256"), str
            )
            or SHA256.fullmatch(
                migration_execution.get("migration_request_sha256", "")
            )
            is None
        ):
            failures.append("ebs.migration_execution_binding:invalid")
    migration_mappings = ebs.get("migration_validator_mappings")
    if (
        not isinstance(migration_mappings, list)
        or len(migration_mappings) != 3
        or any(not isinstance(item, Mapping) for item in migration_mappings)
    ):
        failures.append("ebs.migration_validator_mappings:not_exact_three")
    else:
        mapping_validator_ids: list[Any] = []
        mapping_instance_ids: list[Any] = []
        mapping_signers: list[Any] = []
        mapping_state_volumes: list[Any] = []
        mapping_snapshots: list[Any] = []
        mapping_root_volumes: list[Any] = []
        for item in migration_mappings:
            _exact_keys(
                item,
                MIGRATION_MAPPING_FIELDS,
                "ebs.migration_validator_mapping",
                failures,
            )
            mapping_validator_ids.append(item.get("validator_id"))
            mapping_instance_ids.append(item.get("instance_id"))
            mapping_signers.append(item.get("signer_arn"))
            mapping_state_volumes.append(item.get("state_volume_id"))
            mapping_snapshots.append(item.get("rollback_snapshot_id"))
            mapping_root_volumes.append(item.get("root_volume_id"))
        signer_prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
        if (
            mapping_validator_ids != list(VALIDATOR_IDS)
            or len(set(mapping_instance_ids)) != 3
            or any(
                INSTANCE.fullmatch(str(value)) is None
                for value in mapping_instance_ids
            )
            or len(set(mapping_signers)) != 3
            or any(
                not isinstance(value, str)
                or not value.startswith(signer_prefix)
                for value in mapping_signers
            )
            or len(set(mapping_state_volumes)) != 3
            or any(
                VOLUME.fullmatch(str(value)) is None
                for value in mapping_state_volumes
            )
            or len(set(mapping_snapshots)) != 3
            or any(
                SNAPSHOT.fullmatch(str(value)) is None
                for value in mapping_snapshots
            )
            or len(set(mapping_root_volumes)) != 3
            or any(
                VOLUME.fullmatch(str(value)) is None
                for value in mapping_root_volumes
            )
        ):
            failures.append("ebs.migration_validator_mappings:invalid")
    migration_head = ebs.get("migration_finalized_head")
    if not isinstance(migration_head, Mapping):
        failures.append("ebs.migration_finalized_head:missing")
    else:
        _exact_keys(
            migration_head,
            MIGRATION_HEAD_FIELDS,
            "ebs.migration_finalized_head",
            failures,
        )
        if (
            not isinstance(migration_head.get("height"), int)
            or isinstance(migration_head.get("height"), bool)
            or migration_head.get("height", 0) < 1
            or HASH.fullmatch(str(migration_head.get("hash"))) is None
            or HASH.fullmatch(
                str(migration_head.get("certificate_hash"))
            )
            is None
        ):
            failures.append("ebs.migration_finalized_head:invalid")
    if (
        ebs.get("immutable_runtime_certificate_activation_pending")
        is not True
    ):
        failures.append(
            "ebs.immutable_runtime_certificate_activation_pending:not_true"
        )
    if baseline_mode == "private_ssm":
        private_readback = explorer.get("readback")
        private_head = (
            private_readback.get("finalized_head")
            if isinstance(private_readback, Mapping)
            else None
        )
        if not isinstance(private_head, Mapping) or not isinstance(
            migration_head, Mapping
        ) or any(
            private_head.get(field) != migration_head.get(field)
            for field in ("height", "hash", "certificate_hash")
        ):
            failures.append(
                "private_ssm.migration_finalized_head:mismatch"
            )
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
            _exact_keys(
                item,
                VOLUME_FIELDS,
                "ebs.validator_volume",
                failures,
            )
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
        if (
            isinstance(migration_mappings, list)
            and len(migration_mappings) == 3
            and isinstance(signers, list)
        ):
            if [
                item.get("signer_arn")
                for item in migration_mappings
                if isinstance(item, Mapping)
            ] != [
                item.get("resource_arn")
                for item in signers
                if isinstance(item, Mapping)
            ]:
                failures.append(
                    "ebs.migration_validator_mappings.signers:mismatch"
                )
            if [
                item.get("state_volume_id")
                for item in migration_mappings
                if isinstance(item, Mapping)
            ] != volume_ids:
                failures.append(
                    "ebs.migration_validator_mappings.volumes:mismatch"
                )
            if [
                item.get("rollback_snapshot_id")
                for item in migration_mappings
                if isinstance(item, Mapping)
            ] != snapshots:
                failures.append(
                    "ebs.migration_validator_mappings.snapshots:mismatch"
                )

    _drift_and_lineage(manifest, explorer, ebs, expected, failures)

    for name, source in (
        ("manifest", manifest),
        ("explorer", explorer),
        ("ebs", ebs),
    ):
        _boundary(source, name, failures)

    failures = sorted(set(failures))
    ami_supply_chain = {
        field: (
            provenance.get(tag)
            if isinstance(provenance, Mapping)
            else None
        )
        for field, tag in AMI_SUPPLY_CHAIN_PROVENANCE.items()
    }
    return {
        "schema_version": "junca-runtime-release-manifest-decision/v1",
        "decision": "PROMOTION_GATE_PASS" if not failures else "PROMOTION_GATE_REJECTED",
        "accepted": not failures,
        "phase": "PREDEPLOYMENT_READINESS",
        "baseline_mode": baseline_mode,
        "public_services_enabled": public_services_enabled,
        "public_endpoint_acceptance": public_endpoint_acceptance,
        "public_endpoint_outage_status": (
            public_endpoint_outage.get("status")
            if isinstance(public_endpoint_outage, Mapping)
            else None
        ),
        "candidate": {
            "source_commit": expected_source_commit,
            "node_artifact_sha256": expected_artifact_sha256,
            "genesis_sha256": expected_genesis_sha256,
            "ami_id": manifest.get("ami_id"),
            "request_sha256": request_sha256,
            "migration_evidence_sha256": migration_evidence_sha256,
            "ami_supply_chain": ami_supply_chain,
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
