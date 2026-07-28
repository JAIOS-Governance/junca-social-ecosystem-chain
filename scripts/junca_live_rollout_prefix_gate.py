#!/usr/bin/env python3
"""Evaluate an evidence-bound live prefix before a serial validator rollout.

The canonical rolling gate historically assumed that every non-target validator
must share one Terraform previous runtime and AMI. Emergency in-place recovery
can leave a healthy validator on a different, fully observed runtime before the
next immutable rollout. This gate binds each validator to its own captured
baseline and permits only an exact transition from that baseline to the target.
It does not alter Terraform, AWS resources, state, keys, Mainnet, assets, or the
bridge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jaios.social_ecosystem_chain import rolling_compatibility as canonical


class EvidenceBoundPrefixError(ValueError):
    """Raised when a live prefix cannot safely advance."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceBoundPrefixError(message)


def _text(value: object, field: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{field} is required")
    return value.strip()


def _finality_tuple(item: Mapping[str, Any], label: str) -> tuple[bool, int, int | None]:
    enabled = item.get("automatic_finality_enabled")
    interval = item.get("block_interval_seconds")
    epoch = item.get("slot_epoch_seconds")
    _require(isinstance(enabled, bool), f"{label} finality enabled state is invalid")
    _require(
        isinstance(interval, int) and not isinstance(interval, bool),
        f"{label} block interval is invalid",
    )
    _require(
        epoch is None or (isinstance(epoch, int) and not isinstance(epoch, bool)),
        f"{label} slot epoch is invalid",
    )
    if enabled:
        _require(interval == 30, f"{label} enabled finality requires 30 seconds")
        _require(isinstance(epoch, int) and epoch > 0, f"{label} enabled finality requires an epoch")
    else:
        _require(interval == 0, f"{label} disabled finality requires zero interval")
        _require(epoch in (None, 0), f"{label} disabled finality requires zero epoch")
    return enabled, interval, epoch


def _ordered(
    value: object, order: tuple[str, str, str], field: str
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise EvidenceBoundPrefixError(f"{field} must contain exactly three validators")
    by_id = {item.get("validator_id"): item for item in value}
    _require(set(by_id) == set(order) and len(by_id) == 3, f"{field} identity/order mismatch")
    return by_id[order[0]], by_id[order[1]], by_id[order[2]]


def evaluate_live_rollout_prefix_v2(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    target = _text(evidence.get("target_version"), "target_version")
    target_ami = _text(evidence.get("target_ami_id"), "target_ami_id")
    previous = _text(evidence.get("previous_version"), "previous_version")
    previous_ami = _text(evidence.get("previous_ami_id"), "previous_ami_id")
    _require(target != previous, "target and previous runtime versions must differ")
    _require(canonical.AMI.fullmatch(target_ami) is not None, "target AMI is invalid")
    _require(canonical.AMI.fullmatch(previous_ami) is not None, "previous AMI is invalid")
    _require(target_ami != previous_ami, "target and previous AMIs must differ")

    _, rollback_previous, rollback_ami, rollback_by_id = canonical._rollback(
        evidence.get("rollback"), target, target_ami
    )
    _require(
        rollback_previous == previous and rollback_ami == previous_ami,
        "rollback runtime and AMI differ from previous binding",
    )

    order = canonical._three_unique(evidence.get("update_order"), "update_order")
    current_validators = _ordered(evidence.get("validators"), order, "validators")
    baseline_validators = _ordered(
        evidence.get("evidence_validators"), order, "evidence_validators"
    )

    evidence_count = evidence.get("evidence_updated_count")
    _require(
        isinstance(evidence_count, int)
        and not isinstance(evidence_count, bool)
        and 0 <= evidence_count <= 3,
        "evidence_updated_count must be between zero and three",
    )
    for boundary in canonical.BOUNDARIES:
        _require(evidence.get(boundary) is False, f"{boundary} must be false")

    requested_epoch = evidence.get("requested_slot_epoch_seconds")
    observed_time = evidence.get("observed_unix_time")
    _require(
        isinstance(requested_epoch, int)
        and not isinstance(requested_epoch, bool)
        and isinstance(observed_time, int)
        and not isinstance(observed_time, bool)
        and requested_epoch > observed_time,
        "future canonical slot epoch is required",
    )
    remaining = requested_epoch - observed_time
    _require(
        canonical.MINIMUM_SLOT_EPOCH_REMAINING_SECONDS
        <= remaining
        <= canonical.MAXIMUM_SLOT_EPOCH_REMAINING_SECONDS,
        "canonical slot epoch is outside the bounded safety window",
    )

    updated: list[bool] = []
    current_heads: set[tuple[int, str, str]] = set()
    baseline_bindings: list[dict[str, Any]] = []

    for index, validator_id in enumerate(order):
        current = current_validators[index]
        baseline = baseline_validators[index]
        rollback = rollback_by_id[validator_id]

        current_instance = str(current.get("instance_id", ""))
        baseline_instance = str(baseline.get("instance_id", ""))
        _require(
            canonical.INSTANCE.fullmatch(current_instance) is not None,
            f"{validator_id} live instance id is invalid",
        )
        _require(
            canonical.INSTANCE.fullmatch(baseline_instance) is not None,
            f"{validator_id} evidence instance id is invalid",
        )
        _require(
            current.get("volume_id") == rollback.get("volume_id"),
            f"{validator_id} live rollback volume binding mismatch",
        )
        _require(
            baseline.get("volume_id") == rollback.get("volume_id"),
            f"{validator_id} evidence rollback volume binding mismatch",
        )

        canonical._validator_health(baseline, rollback)
        canonical._validator_health(current, rollback)
        canonical._finality_provenance(baseline, target_runtime=False)
        current_heads.add(canonical._head(current))

        baseline_runtime = _text(
            baseline.get("runtime_version"),
            f"{validator_id}.baseline_runtime_version",
        )
        baseline_ami = _text(
            baseline.get("ami_id"), f"{validator_id}.baseline_ami_id"
        )
        _require(
            canonical.SHA256.fullmatch(baseline_runtime) is not None,
            f"{validator_id} baseline runtime digest is invalid",
        )
        _require(
            canonical.AMI.fullmatch(baseline_ami) is not None,
            f"{validator_id} baseline AMI is invalid",
        )
        baseline_is_target = baseline_runtime == target
        _require(
            baseline_is_target == (index < evidence_count),
            f"{validator_id} evidence prefix does not match updated count",
        )
        if baseline_is_target:
            _require(
                baseline_ami == target_ami,
                f"{validator_id} target baseline AMI mismatch",
            )
            _require(
                _finality_tuple(baseline, f"{validator_id} baseline")
                == (True, 30, requested_epoch),
                f"{validator_id} target baseline epoch mismatch",
            )
            canonical._finality_provenance(baseline, target_runtime=True)
        else:
            _require(
                baseline_ami != target_ami,
                f"{validator_id} non-target baseline uses candidate AMI",
            )
            _finality_tuple(baseline, f"{validator_id} baseline")

        current_runtime = _text(
            current.get("runtime_version"), f"{validator_id}.runtime_version"
        )
        current_ami = _text(current.get("ami_id"), f"{validator_id}.ami_id")
        _require(
            canonical.SHA256.fullmatch(current_runtime) is not None,
            f"{validator_id} live runtime digest is invalid",
        )
        _require(
            canonical.AMI.fullmatch(current_ami) is not None,
            f"{validator_id} live AMI is invalid",
        )
        _require(
            current_runtime in (baseline_runtime, target),
            f"{validator_id} has an unexpected runtime version",
        )
        is_target = current_runtime == target
        if is_target:
            _require(current_ami == target_ami, f"{validator_id} target AMI mismatch")
            _require(
                _finality_tuple(current, validator_id)
                == (True, 30, requested_epoch),
                f"{validator_id} candidate finality epoch drifted",
            )
            canonical._finality_provenance(current, target_runtime=True)
        else:
            _require(
                current_ami == baseline_ami,
                f"{validator_id} runtime and evidence AMI binding mismatch",
            )
            _require(
                _finality_tuple(current, validator_id)
                == _finality_tuple(baseline, f"{validator_id} baseline"),
                f"{validator_id} non-target finality state drifted from evidence",
            )
            canonical._finality_provenance(current, target_runtime=False)
        updated.append(is_target)
        baseline_bindings.append(
            {
                "validator_id": validator_id,
                "runtime_version": baseline_runtime,
                "ami_id": baseline_ami,
                "instance_id": baseline_instance,
                "volume_id": baseline.get("volume_id"),
                "target_runtime": baseline_is_target,
            }
        )

    _require(
        len(current_heads) == 1,
        "validators disagree on finalized head or certificate",
    )
    _require(updated == sorted(updated, reverse=True), "validator update order is not contiguous")
    live_count = sum(updated)
    _require(
        evidence_count <= live_count <= min(evidence_count + 1, 3),
        "live prefix must equal the evidence prefix or its one next validator",
    )

    for index, validator_id in enumerate(order):
        current_id = str(current_validators[index].get("instance_id"))
        baseline_id = str(baseline_validators[index].get("instance_id"))
        if index < evidence_count or index >= live_count:
            _require(
                current_id == baseline_id,
                f"{validator_id} changed outside the recoverable live prefix",
            )
        else:
            _require(
                current_id != baseline_id,
                f"{validator_id} target runtime did not replace its evidence-bound instance",
            )

    return {
        "schema_version": "junca-validator-live-prefix/v2",
        "state": "EVIDENCE_BOUND_PREFIX_ACCEPTED",
        "evidence_updated_count": evidence_count,
        "live_updated_count": live_count,
        "recovered_uncommitted_count": live_count - evidence_count,
        "updated_validator_ids": list(order[:live_count]),
        "next_validator": order[live_count] if live_count < 3 else None,
        "baseline_bindings": baseline_bindings,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceBoundPrefixError("evidence must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        decision = evaluate_live_rollout_prefix_v2(_read(args.evidence))
    except (OSError, json.JSONDecodeError, EvidenceBoundPrefixError, canonical.RollingCompatibilityError) as exc:
        result = {
            "schema_version": "junca-validator-live-prefix/v2",
            "state": "EVIDENCE_BOUND_PREFIX_REJECTED",
            "reason": str(exc),
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, sort_keys=True))
        return 1
    Path(args.output).write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
