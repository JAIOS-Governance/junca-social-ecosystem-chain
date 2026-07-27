"""Fail-closed compatibility gate for three-validator runtime rollouts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"0x[0-9a-f]{64}")
VOLUME = re.compile(r"vol-[0-9a-f]{8,17}")
SNAPSHOT = re.compile(r"snap-[0-9a-f]{8,17}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
INSTANCE = re.compile(r"i-[0-9a-f]{8,17}")
BOUNDARIES = ("mainnet_changed", "assets_moved", "bridge_activated")
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
CHAIN_ID = 20260723
NETWORK_LABEL = "Public Testnet / No Monetary Value"
MINIMUM_SLOT_EPOCH_REMAINING_SECONDS = 900
MAXIMUM_SLOT_EPOCH_REMAINING_SECONDS = 7230
RECOVERY_FILE_ALLOWLIST = frozenset(
    {
        ".github/workflows/junca-validator-foundation-release.yml",
        ".github/workflows/junca-validator-public-testnet-orchestrator.yml",
        "config/junca_validator_ami_build_request.json",
        "jaios/social_ecosystem_chain/rolling_compatibility.py",
        "scripts/junca_public_testnet_foundation.sh",
        "scripts/junca_validator_ami_build_request.py",
        "tests/test_junca_social_ecosystem_chain_aws_foundation.py",
        "tests/test_junca_validator_ami_workflow.py",
        "tests/test_junca_validator_rolling_compatibility.py",
    }
)


class RollingCompatibilityError(ValueError):
    """Raised when a rollout observation cannot safely advance."""


def evaluate_recovery_head_compare(
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Prove a workflow-only recovery head is a narrowly changed descendant."""

    expected_base = _text(evidence.get("expected_base"), "expected_base")
    expected_head = _text(evidence.get("expected_head"), "expected_head")
    if not COMMIT.fullmatch(expected_base) or not COMMIT.fullmatch(expected_head):
        raise RollingCompatibilityError("expected compare heads are invalid")
    comparison = evidence.get("comparison")
    if not isinstance(comparison, Mapping):
        raise RollingCompatibilityError("GitHub comparison evidence is required")
    status = comparison.get("status")
    if status not in ("ahead", "identical"):
        raise RollingCompatibilityError(
            "current workflow head must be ahead of or identical to candidate"
        )
    if comparison.get("base_commit", {}).get("sha") != expected_base:
        raise RollingCompatibilityError("comparison base commit differs")
    if comparison.get("merge_base_commit", {}).get("sha") != expected_base:
        raise RollingCompatibilityError(
            "candidate is not the exact merge base of current workflow head"
        )
    ahead_by = comparison.get("ahead_by")
    behind_by = comparison.get("behind_by")
    total_commits = comparison.get("total_commits")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (ahead_by, behind_by, total_commits)
    ):
        raise RollingCompatibilityError("comparison commit counts are invalid")
    if behind_by != 0 or total_commits != ahead_by:
        raise RollingCompatibilityError(
            "current workflow head is behind or diverged from candidate"
        )
    commits = comparison.get("commits")
    if not isinstance(commits, Sequence) or isinstance(
        commits, (str, bytes)
    ):
        raise RollingCompatibilityError("ordered comparison commits are required")
    commit_shas = [
        item.get("sha") for item in commits if isinstance(item, Mapping)
    ]
    if (
        len(commit_shas) != len(commits)
        or any(not COMMIT.fullmatch(str(sha)) for sha in commit_shas)
        or len(set(commit_shas)) != len(commit_shas)
    ):
        raise RollingCompatibilityError(
            "ordered comparison commits are invalid or duplicated"
        )
    files = comparison.get("files")
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise RollingCompatibilityError("comparison file list is required")
    filenames = [item.get("filename") for item in files if isinstance(item, Mapping)]
    if (
        len(filenames) != len(files)
        or len(set(filenames)) != len(filenames)
        or any(name not in RECOVERY_FILE_ALLOWLIST for name in filenames)
        or any(
            item.get("status") != "modified"
            or item.get("previous_filename") is not None
            for item in files
        )
    ):
        raise RollingCompatibilityError(
            "cross-head recovery contains a file outside the recovery allowlist"
        )
    if status == "identical":
        if (
            ahead_by != 0
            or commit_shas
            or filenames
            or expected_base != expected_head
        ):
            raise RollingCompatibilityError(
                "identical recovery comparison contains unexpected changes"
            )
    else:
        if (
            ahead_by < 1
            or len(commit_shas) != ahead_by
            or commit_shas[-1] != expected_head
        ):
            raise RollingCompatibilityError(
                "ordered comparison commits do not reach expected head"
            )
        if not filenames or expected_base == expected_head:
            raise RollingCompatibilityError(
                "ahead recovery comparison must contain an allowlisted change"
            )
    return {
        "schema_version": "junca-validator-recovery-head/v1",
        "state": "RECOVERY_HEAD_ACCEPTED",
        "candidate_head": expected_base,
        "current_head": expected_head,
        "changed_files": sorted(filenames),
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def evaluate_live_rollout_prefix(
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Recover one fully observable but not-yet-checkpointed replacement.

    A failed targeted Terraform apply can replace exactly one validator before
    the rolling resume artifact is rewritten.  The artifact count is therefore
    a committed lower bound, not a statement that the live prefix is unchanged.
    This read-only gate accepts at most the one next contiguous replacement and
    requires every unaffected instance to retain its evidence-bound identity.
    """

    target = _text(evidence.get("target_version"), "target_version")
    previous = _text(evidence.get("previous_version"), "previous_version")
    if target == previous:
        raise RollingCompatibilityError(
            "target and previous runtime versions must differ"
        )
    target_ami = _text(evidence.get("target_ami_id"), "target_ami_id")
    previous_ami = _text(evidence.get("previous_ami_id"), "previous_ami_id")
    if (
        not AMI.fullmatch(target_ami)
        or not AMI.fullmatch(previous_ami)
        or target_ami == previous_ami
    ):
        raise RollingCompatibilityError("target/previous AMI binding is invalid")
    _, rollback_previous, rollback_ami, rollback_by_id = _rollback(
        evidence.get("rollback"), target, target_ami
    )
    if rollback_previous != previous or rollback_ami != previous_ami:
        raise RollingCompatibilityError(
            "rollback runtime and AMI differ from previous binding"
        )
    order = _three_unique(evidence.get("update_order"), "update_order")
    validators = _ordered_validators(evidence.get("validators"), order)
    baseline = _ordered_validators(
        evidence.get("evidence_validators"), order
    )
    evidence_count = evidence.get("evidence_updated_count")
    if (
        isinstance(evidence_count, bool)
        or not isinstance(evidence_count, int)
        or evidence_count < 0
        or evidence_count > 3
    ):
        raise RollingCompatibilityError(
            "evidence_updated_count must be between zero and three"
        )
    for boundary in BOUNDARIES:
        if evidence.get(boundary) is not False:
            raise RollingCompatibilityError(f"{boundary} must be false")

    requested_epoch = evidence.get("requested_slot_epoch_seconds")
    now = evidence.get("observed_unix_time")
    if (
        isinstance(requested_epoch, bool)
        or not isinstance(requested_epoch, int)
        or isinstance(now, bool)
        or not isinstance(now, int)
        or requested_epoch <= now
    ):
        raise RollingCompatibilityError("future canonical slot epoch is required")
    remaining = requested_epoch - now
    if (
        remaining < MINIMUM_SLOT_EPOCH_REMAINING_SECONDS
        or remaining > MAXIMUM_SLOT_EPOCH_REMAINING_SECONDS
    ):
        raise RollingCompatibilityError(
            "canonical slot epoch is outside the bounded safety window"
        )

    updated: list[bool] = []
    heads: set[tuple[int, str, str]] = set()
    for index, validator_id in enumerate(order):
        current = validators[index]
        prior = baseline[index]
        if not INSTANCE.fullmatch(str(current.get("instance_id", ""))):
            raise RollingCompatibilityError(
                f"{validator_id} live instance id is invalid"
            )
        if not INSTANCE.fullmatch(str(prior.get("instance_id", ""))):
            raise RollingCompatibilityError(
                f"{validator_id} evidence instance id is invalid"
            )
        _validator_health(current, rollback_by_id[validator_id])
        if current.get("volume_id") != rollback_by_id[validator_id].get(
            "volume_id"
        ):
            raise RollingCompatibilityError(
                f"{validator_id} rollback volume binding mismatch"
            )
        heads.add(_head(current))
        runtime = current.get("runtime_version")
        if runtime not in (previous, target):
            raise RollingCompatibilityError(
                f"{validator_id} has an unexpected runtime version"
            )
        is_target = runtime == target
        expected_ami = target_ami if is_target else previous_ami
        if current.get("ami_id") != expected_ami:
            raise RollingCompatibilityError(
                f"{validator_id} runtime and AMI binding mismatch"
            )
        _finality_provenance(current, target_runtime=is_target)
        if is_target and current.get("automatic_finality_enabled") is True:
            if (
                current.get("block_interval_seconds") != 30
                or current.get("slot_epoch_seconds") != requested_epoch
            ):
                raise RollingCompatibilityError(
                    f"{validator_id} candidate finality epoch drifted"
                )
        elif (
            current.get("automatic_finality_enabled") is not False
            or current.get("block_interval_seconds") != 0
            or current.get("slot_epoch_seconds") not in (None, 0)
        ):
            raise RollingCompatibilityError(
                f"{validator_id} is not fail-closed before recovery"
            )
        updated.append(is_target)

    if len(heads) != 1:
        raise RollingCompatibilityError(
            "validators disagree on finalized head or certificate"
        )
    if updated != sorted(updated, reverse=True):
        raise RollingCompatibilityError("validator update order is not contiguous")
    live_count = sum(updated)
    if live_count < evidence_count or live_count > min(evidence_count + 1, 3):
        raise RollingCompatibilityError(
            "live prefix must equal the evidence prefix or its one next validator"
        )

    for index, validator_id in enumerate(order):
        current_id = validators[index]["instance_id"]
        prior_id = baseline[index]["instance_id"]
        if index < evidence_count or index >= live_count:
            if current_id != prior_id:
                raise RollingCompatibilityError(
                    f"{validator_id} changed outside the recoverable live prefix"
                )
        elif current_id == prior_id:
            raise RollingCompatibilityError(
                f"{validator_id} target runtime did not replace its bound instance"
            )

    return {
        "schema_version": "junca-validator-live-prefix/v1",
        "evidence_updated_count": evidence_count,
        "live_updated_count": live_count,
        "recovered_uncommitted_count": live_count - evidence_count,
        "updated_validator_ids": list(order[:live_count]),
        "next_validator": order[live_count] if live_count < 3 else None,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def evaluate_rolling_compatibility(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    target = _text(evidence.get("target_version"), "target_version")
    target_ami = _text(evidence.get("target_ami_id"), "target_ami_id")
    if not AMI.fullmatch(target_ami):
        raise RollingCompatibilityError("target AMI is invalid")
    order = _three_unique(evidence.get("update_order"), "update_order")
    validators = evidence.get("validators")
    if not isinstance(validators, Sequence) or isinstance(validators, (str, bytes)):
        raise RollingCompatibilityError("validators must contain exactly three entries")
    if len(validators) != 3 or any(not isinstance(item, Mapping) for item in validators):
        raise RollingCompatibilityError("validators must contain exactly three entries")
    by_id = {item.get("validator_id"): item for item in validators}
    if set(by_id) != set(order) or len(by_id) != 3:
        raise RollingCompatibilityError("validator identity/order mismatch")

    for boundary in BOUNDARIES:
        if evidence.get(boundary) is not False:
            raise RollingCompatibilityError(f"{boundary} must be false")
    if evidence.get("fallback_active") is not False:
        raise RollingCompatibilityError("fallback must remain inactive")

    rollback, previous, previous_ami, rollback_by_id = _rollback(
        evidence.get("rollback"), target, target_ami
    )

    enabled = [item.get("automatic_finality_enabled") for item in validators]
    if any(value not in (True, False) for value in enabled):
        raise RollingCompatibilityError("automatic finality readback is invalid")
    if any(enabled) and not all(enabled):
        raise RollingCompatibilityError("mixed automatic finality state is prohibited")
    intervals = [item.get("block_interval_seconds") for item in validators]
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in intervals
    ):
        raise RollingCompatibilityError("block interval readback is invalid")
    expected_interval = 30 if all(enabled) else 0
    if any(value != expected_interval for value in intervals):
        raise RollingCompatibilityError(
            "block interval does not match automatic finality state"
        )

    for validator_id in order:
        _validator_health(by_id[validator_id], rollback_by_id[validator_id])

    heads = {
        (
            item.get("head_height"),
            item.get("head_hash"),
            item.get("certificate_hash"),
        )
        for item in validators
    }
    if len(heads) != 1:
        raise RollingCompatibilityError(
            "validators disagree on finalized head or certificate"
        )

    versions = [by_id[validator_id].get("runtime_version") for validator_id in order]
    if any(not isinstance(version, str) or not version for version in versions):
        raise RollingCompatibilityError("runtime version readback is incomplete")
    updated = [version == target for version in versions]
    if updated != sorted(updated, reverse=True):
        raise RollingCompatibilityError("validator update order is not contiguous")
    if any(version not in (previous, target) for version in versions):
        raise RollingCompatibilityError("unexpected runtime version detected")
    for validator_id, is_updated in zip(order, updated, strict=True):
        expected_ami = target_ami if is_updated else previous_ami
        if by_id[validator_id].get("ami_id") != expected_ami:
            raise RollingCompatibilityError(
                f"{validator_id} runtime and AMI binding mismatch"
            )
        _finality_provenance(
            by_id[validator_id], target_runtime=is_updated
        )

    requested_epoch = evidence.get("requested_slot_epoch_seconds")
    now = evidence.get("observed_unix_time")
    if (
        isinstance(requested_epoch, bool)
        or not isinstance(requested_epoch, int)
        or isinstance(now, bool)
        or not isinstance(now, int)
        or requested_epoch <= now
    ):
        raise RollingCompatibilityError("future canonical slot epoch is required")
    remaining = requested_epoch - now
    if (
        remaining < MINIMUM_SLOT_EPOCH_REMAINING_SECONDS
        or remaining > MAXIMUM_SLOT_EPOCH_REMAINING_SECONDS
    ):
        raise RollingCompatibilityError(
            "canonical slot epoch is outside the bounded safety window"
        )

    configured = [item.get("slot_epoch_seconds") for item in validators]
    updated_count = sum(updated)
    if updated_count < 3:
        if any(enabled) or any(value not in (None, 0) for value in configured):
            raise RollingCompatibilityError(
                "finality and slot epoch must remain disabled during rolling update"
            )
        return _decision(
            "READY_FOR_NEXT_VALIDATOR",
            next_validator=order[updated_count],
            updated_count=updated_count,
        )

    if len(set(versions)) != 1:
        raise RollingCompatibilityError("validator runtime versions do not match")
    if all(value in (None, 0) for value in configured):
        if any(enabled):
            raise RollingCompatibilityError("finality enabled before slot epoch")
        return _decision("READY_FOR_SLOT_EPOCH", updated_count=3)
    if any(value != requested_epoch for value in configured):
        raise RollingCompatibilityError("slot epoch readback mismatch")
    if not all(enabled):
        return _decision("READY_FOR_FINALITY_ENABLE", updated_count=3)
    return _decision("ACCEPTED", updated_count=3)


def _rollback(
    value: object, target: str, target_ami: str
) -> tuple[
    Mapping[str, Any], str, str, Mapping[str, Mapping[str, Any]]
]:
    if not isinstance(value, Mapping):
        raise RollingCompatibilityError("rollback evidence is required")
    previous = _text(value.get("target_version"), "rollback.target_version")
    if previous == target:
        raise RollingCompatibilityError("rollback target must precede target version")
    if not SHA256.fullmatch(str(value.get("artifact_sha256", ""))):
        raise RollingCompatibilityError("rollback artifact digest is invalid")
    previous_ami = _text(value.get("ami_id"), "rollback.ami_id")
    if not AMI.fullmatch(previous_ami) or previous_ami == target_ami:
        raise RollingCompatibilityError("rollback AMI is invalid")
    if (
        value.get("rehearsal_passed") is not True
        or value.get("automatic_finality_disabled") is not True
        or value.get("no_state_rewind") is not True
        or value.get("durable_volume_reused") is not True
        or value.get("snapshot_restore_performed") is not False
    ):
        raise RollingCompatibilityError("rollback is not fail-closed")
    observations = value.get("validators")
    if (
        not isinstance(observations, Sequence)
        or isinstance(observations, (str, bytes))
        or len(observations) != 3
        or any(not isinstance(item, Mapping) for item in observations)
    ):
        raise RollingCompatibilityError(
            "rollback must bind three durable validator heads"
        )
    by_id = {item.get("validator_id"): item for item in observations}
    if set(by_id) != set(VALIDATOR_IDS) or len(by_id) != 3:
        raise RollingCompatibilityError("rollback validator identity mismatch")
    volumes: set[str] = set()
    snapshots: set[str] = set()
    for validator_id in VALIDATOR_IDS:
        item = by_id[validator_id]
        volume = str(item.get("volume_id", ""))
        snapshot = str(item.get("rollback_snapshot_id", ""))
        if not VOLUME.fullmatch(volume) or not SNAPSHOT.fullmatch(snapshot):
            raise RollingCompatibilityError(
                "rollback durable volume or snapshot binding is invalid"
            )
        volumes.add(volume)
        snapshots.add(snapshot)
        if item.get("state_rewind_permitted") is not False:
            raise RollingCompatibilityError("rollback state rewind is prohibited")
        _head(item, prefix="rollback.")
    if len(volumes) != 3 or len(snapshots) != 3:
        raise RollingCompatibilityError(
            "rollback volumes and snapshots must be distinct"
        )
    return value, previous, previous_ami, by_id


def _validator_health(
    item: Mapping[str, Any], rollback: Mapping[str, Any]
) -> None:
    validator_id = item.get("validator_id")
    for field in (
        "ssm_online",
        "service_active",
        "durable_mount_verified",
        "state_store_integrity",
    ):
        if item.get(field) is not True:
            raise RollingCompatibilityError(
                f"{validator_id}.{field} must be true"
            )
    if item.get("healthy") is not True or item.get("health_status") != "healthy":
        raise RollingCompatibilityError(f"{validator_id} is not healthy")
    if item.get("network") != NETWORK_LABEL or item.get("chain_id") != CHAIN_ID:
        raise RollingCompatibilityError(
            f"{validator_id} Public Testnet binding is invalid"
        )
    for boundary in BOUNDARIES:
        if item.get(boundary) is not False:
            raise RollingCompatibilityError(f"{validator_id}.{boundary} drifted")
    height, head_hash, certificate_hash = _head(item)
    if item.get("durable_certificate_hash") != certificate_hash:
        raise RollingCompatibilityError(
            f"{validator_id} live and durable certificate hashes differ"
        )
    floor_height, floor_hash, floor_certificate = _head(
        rollback, prefix="rollback."
    )
    if height < floor_height:
        raise RollingCompatibilityError(
            f"{validator_id} durable state rewind detected"
        )
    if height == floor_height and (
        head_hash != floor_hash or certificate_hash != floor_certificate
    ):
        raise RollingCompatibilityError(
            f"{validator_id} durable head changed at rollback floor"
        )


def _finality_provenance(
    item: Mapping[str, Any], *, target_runtime: bool
) -> None:
    validator_id = item.get("validator_id")
    readback = item.get("finality_readback")
    if not isinstance(readback, Mapping):
        raise RollingCompatibilityError(
            f"{validator_id} finality readback provenance is required"
        )
    runtime_env = readback.get("runtime_env")
    health = readback.get("health")
    if not isinstance(runtime_env, Mapping) or not isinstance(health, Mapping):
        raise RollingCompatibilityError(
            f"{validator_id} finality readback provenance is invalid"
        )
    fields = (
        "automatic_finality_enabled",
        "block_interval_seconds",
        "slot_epoch_seconds",
    )
    observed = {field: item.get(field) for field in fields}
    if any(runtime_env.get(field) != observed[field] for field in fields):
        raise RollingCompatibilityError(
            f"{validator_id} runtime.env finality provenance differs"
        )
    health_supported = readback.get("health_supported")
    if health_supported is True:
        if any(health.get(field) != observed[field] for field in fields):
            raise RollingCompatibilityError(
                f"{validator_id} health finality provenance differs"
            )
    elif health_supported is False:
        if any(health.get(field) is not None for field in fields):
            raise RollingCompatibilityError(
                f"{validator_id} legacy health provenance is invalid"
            )
        if target_runtime:
            raise RollingCompatibilityError(
                f"{validator_id} target runtime finality health readback is required"
            )
    else:
        raise RollingCompatibilityError(
            f"{validator_id} finality health support is invalid"
        )


def _ordered_validators(
    value: object, order: tuple[str, str, str]
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise RollingCompatibilityError(
            "validators must contain exactly three entries"
        )
    by_id = {item.get("validator_id"): item for item in value}
    if set(by_id) != set(order) or len(by_id) != 3:
        raise RollingCompatibilityError("validator identity/order mismatch")
    return by_id[order[0]], by_id[order[1]], by_id[order[2]]


def _head(
    item: Mapping[str, Any], *, prefix: str = ""
) -> tuple[int, str, str]:
    height = item.get("head_height")
    head_hash = item.get("head_hash")
    certificate_hash = item.get("certificate_hash")
    certificate_height = item.get("certificate_height")
    certificate_block_hash = item.get("certificate_block_hash")
    validator_ids = item.get("certificate_validator_ids")
    vote_hashes = item.get("certificate_vote_hashes")
    if isinstance(height, bool) or not isinstance(height, int) or height < 1:
        raise RollingCompatibilityError(f"{prefix}head height is invalid")
    if not HASH.fullmatch(str(head_hash)) or not HASH.fullmatch(
        str(certificate_hash)
    ):
        raise RollingCompatibilityError(f"{prefix}head certificate is invalid")
    if (
        certificate_height != height
        or certificate_block_hash != head_hash
        or item.get("certificate_finality_status") != "FINALIZED"
    ):
        raise RollingCompatibilityError(
            f"{prefix}certificate does not bind the durable head"
        )
    if (
        item.get("certificate_signed_power") != 3
        or item.get("certificate_total_power") != 3
        or validator_ids != list(VALIDATOR_IDS)
        or not isinstance(vote_hashes, list)
        or len(vote_hashes) != 3
        or len(set(vote_hashes)) != 3
        or any(not HASH.fullmatch(str(value)) for value in vote_hashes)
    ):
        raise RollingCompatibilityError(
            f"{prefix}certificate quorum proof is invalid"
        )
    return height, str(head_hash), str(certificate_hash)


def _decision(
    state: str, *, updated_count: int, next_validator: str | None = None
) -> Mapping[str, Any]:
    return {
        "schema_version": "junca-validator-rolling-compatibility/v1",
        "state": state,
        "updated_count": updated_count,
        "next_validator": next_validator,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RollingCompatibilityError(f"{field} is required")
    return value.strip()


def _three_unique(value: object, field: str) -> tuple[str, str, str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != 3
    ):
        raise RollingCompatibilityError(f"{field} must contain three unique ids")
    return value[0], value[1], value[2]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mode",
        choices=("compatibility", "live-prefix", "recovery-head"),
        default="compatibility",
    )
    args = parser.parse_args(argv)
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    if not isinstance(evidence, Mapping):
        raise RollingCompatibilityError("evidence must be an object")
    if args.mode == "live-prefix":
        decision = evaluate_live_rollout_prefix(evidence)
    elif args.mode == "recovery-head":
        decision = evaluate_recovery_head_compare(evidence)
    else:
        decision = evaluate_rolling_compatibility(evidence)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
