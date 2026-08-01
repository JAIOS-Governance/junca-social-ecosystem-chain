#!/usr/bin/env python3
"""Evaluate evidence-bound state during a serial validator rollout.

The canonical rolling gate assumes every non-target validator shares one previous
runtime and AMI. Emergency in-place recovery can leave a healthy validator on a
different, fully observed runtime before the next immutable rollout. This module
binds every validator to its own captured baseline and permits only an exact,
ordered transition from that baseline to the immutable target.

Two modes are exposed:

* ``live-prefix`` recovers at most one completed-but-uncommitted replacement
  before any runtime configuration mutation.
* ``rolling`` governs the full serial replacement and finality activation
  lifecycle from the captured baseline.

Neither mode changes Terraform, AWS resources, durable state, keys, Mainnet,
assets, or the bridge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import rolling_compatibility as canonical


class EvidenceBoundPrefixError(ValueError):
    """Raised when an evidence-bound rollout observation cannot advance."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceBoundPrefixError(message)


def _text(value: object, field: str) -> str:
    _require(
        isinstance(value, str) and bool(value.strip()),
        f"{field} is required",
    )
    return value.strip()


def _finality_tuple(
    item: Mapping[str, Any], label: str
) -> tuple[bool, int, int | None]:
    enabled = item.get("automatic_finality_enabled")
    interval = item.get("block_interval_seconds")
    epoch = item.get("slot_epoch_seconds")
    _require(
        isinstance(enabled, bool),
        f"{label} finality enabled state is invalid",
    )
    _require(
        isinstance(interval, int) and not isinstance(interval, bool),
        f"{label} block interval is invalid",
    )
    _require(
        epoch is None
        or (isinstance(epoch, int) and not isinstance(epoch, bool)),
        f"{label} slot epoch is invalid",
    )
    if enabled:
        _require(
            interval == 30,
            f"{label} enabled finality requires 30 seconds",
        )
        _require(
            isinstance(epoch, int) and epoch > 0,
            f"{label} enabled finality requires an epoch",
        )
    else:
        _require(
            interval == 0,
            f"{label} disabled finality requires zero interval",
        )
        _require(
            epoch in (None, 0) or (isinstance(epoch, int) and epoch > 0),
            f"{label} disabled finality epoch is invalid",
        )
    return enabled, interval, epoch


def _target_finality_phase(
    item: Mapping[str, Any],
    requested_epoch: int,
    label: str,
) -> str:
    state = _finality_tuple(item, label)
    if state[0] is False and state[1] == 0 and state[2] in (None, 0):
        return "QUIESCED"
    if state == (False, 0, requested_epoch):
        return "EPOCH_CONFIGURED"
    if state == (True, 30, requested_epoch):
        return "ENABLED"
    raise EvidenceBoundPrefixError(
        f"{label} target finality state is outside the canonical lifecycle"
    )


def _ordered(
    value: object,
    order: tuple[str, str, str],
    field: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise EvidenceBoundPrefixError(
            f"{field} must contain exactly three validators"
        )
    by_id = {item.get("validator_id"): item for item in value}
    _require(
        set(by_id) == set(order) and len(by_id) == 3,
        f"{field} identity/order mismatch",
    )
    return by_id[order[0]], by_id[order[1]], by_id[order[2]]


def _common(
    evidence: Mapping[str, Any],
) -> tuple[
    str,
    str,
    str,
    str,
    tuple[str, str, str],
    tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
    int,
    int,
]:
    target = _text(evidence.get("target_version"), "target_version")
    target_ami = _text(evidence.get("target_ami_id"), "target_ami_id")
    previous = _text(evidence.get("previous_version"), "previous_version")
    previous_ami = _text(evidence.get("previous_ami_id"), "previous_ami_id")
    _require(
        canonical.SHA256.fullmatch(target) is not None,
        "target runtime digest is invalid",
    )
    _require(
        canonical.SHA256.fullmatch(previous) is not None,
        "previous runtime digest is invalid",
    )
    _require(
        target != previous,
        "target and previous runtime versions must differ",
    )
    _require(
        canonical.AMI.fullmatch(target_ami) is not None,
        "target AMI is invalid",
    )
    _require(
        canonical.AMI.fullmatch(previous_ami) is not None,
        "previous AMI is invalid",
    )
    _require(
        target_ami != previous_ami,
        "target and previous AMIs must differ",
    )

    _, rollback_previous, rollback_ami, rollback_by_id = canonical._rollback(
        evidence.get("rollback"), target, target_ami
    )
    _require(
        rollback_previous == previous and rollback_ami == previous_ami,
        "rollback runtime and AMI differ from previous binding",
    )

    order = canonical._three_unique(
        evidence.get("update_order"), "update_order"
    )
    current_validators = _ordered(
        evidence.get("validators"), order, "validators"
    )
    baseline_validators = _ordered(
        evidence.get("evidence_validators"),
        order,
        "evidence_validators",
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
    return (
        target,
        target_ami,
        previous,
        previous_ami,
        order,
        current_validators,
        baseline_validators,
        rollback_by_id,
        evidence_count,
        requested_epoch,
    )


def _baseline_binding(
    *,
    index: int,
    validator_id: str,
    baseline: Mapping[str, Any],
    rollback: Mapping[str, Any],
    target: str,
    target_ami: str,
    evidence_count: int,
    requested_epoch: int,
) -> dict[str, Any]:
    baseline_instance = str(baseline.get("instance_id", ""))
    _require(
        canonical.INSTANCE.fullmatch(baseline_instance) is not None,
        f"{validator_id} evidence instance id is invalid",
    )
    _require(
        baseline.get("volume_id") == rollback.get("volume_id"),
        f"{validator_id} evidence rollback volume binding mismatch",
    )
    canonical._validator_health(baseline, rollback)

    baseline_runtime = _text(
        baseline.get("runtime_version"),
        f"{validator_id}.baseline_runtime_version",
    )
    baseline_ami = _text(
        baseline.get("ami_id"),
        f"{validator_id}.baseline_ami_id",
    )
    _require(
        canonical.SHA256.fullmatch(baseline_runtime) is not None,
        f"{validator_id} baseline runtime digest is invalid",
    )
    _require(
        canonical.AMI.fullmatch(baseline_ami) is not None,
        f"{validator_id} baseline AMI is invalid",
    )
    # A runtime repaired in place can already carry the candidate artifact on
    # an older, fully observed AMI. It is still part of the evidence-bound
    # baseline: only the exact runtime+AMI pair proves an immutable candidate
    # replacement and advances the committed prefix.
    baseline_is_target = (
        baseline_runtime == target and baseline_ami == target_ami
    )
    _require(
        baseline_is_target == (index < evidence_count),
        f"{validator_id} evidence prefix does not match updated count",
    )
    if baseline_is_target:
        _require(
            baseline_ami == target_ami,
            f"{validator_id} target baseline AMI mismatch",
        )
        phase = _target_finality_phase(
            baseline,
            requested_epoch,
            f"{validator_id} baseline",
        )
        canonical._finality_provenance(baseline, target_runtime=True)
    else:
        _require(
            baseline_ami != target_ami,
            f"{validator_id} non-target baseline uses candidate AMI",
        )
        _finality_tuple(baseline, f"{validator_id} baseline")
        canonical._finality_provenance(baseline, target_runtime=False)
        phase = "BASELINE"
    return {
        "validator_id": validator_id,
        "runtime_version": baseline_runtime,
        "ami_id": baseline_ami,
        "instance_id": baseline_instance,
        "volume_id": baseline.get("volume_id"),
        "target_runtime": baseline_is_target,
        "automatic_finality_enabled": baseline.get(
            "automatic_finality_enabled"
        ),
        "block_interval_seconds": baseline.get("block_interval_seconds"),
        "slot_epoch_seconds": baseline.get("slot_epoch_seconds"),
        "finality_phase": phase,
    }


def evaluate_live_rollout_prefix_v2(
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    (
        target,
        target_ami,
        _previous,
        _previous_ami,
        order,
        current_validators,
        baseline_validators,
        rollback_by_id,
        evidence_count,
        requested_epoch,
    ) = _common(evidence)

    updated: list[bool] = []
    current_heads: set[tuple[int, str, str]] = set()
    baseline_bindings: list[dict[str, Any]] = []
    promoted_bindings: list[dict[str, Any]] = []

    for index, validator_id in enumerate(order):
        current = current_validators[index]
        baseline = baseline_validators[index]
        rollback = rollback_by_id[validator_id]
        binding = _baseline_binding(
            index=index,
            validator_id=validator_id,
            baseline=baseline,
            rollback=rollback,
            target=target,
            target_ami=target_ami,
            evidence_count=evidence_count,
            requested_epoch=requested_epoch,
        )
        baseline_bindings.append(binding)

        current_instance = str(current.get("instance_id", ""))
        _require(
            canonical.INSTANCE.fullmatch(current_instance) is not None,
            f"{validator_id} live instance id is invalid",
        )
        _require(
            current.get("volume_id") == rollback.get("volume_id"),
            f"{validator_id} live rollback volume binding mismatch",
        )
        canonical._validator_health(current, rollback)
        current_heads.add(canonical._head(current))

        current_runtime = _text(
            current.get("runtime_version"),
            f"{validator_id}.runtime_version",
        )
        current_ami = _text(
            current.get("ami_id"),
            f"{validator_id}.ami_id",
        )
        _require(
            canonical.SHA256.fullmatch(current_runtime) is not None,
            f"{validator_id} live runtime digest is invalid",
        )
        _require(
            canonical.AMI.fullmatch(current_ami) is not None,
            f"{validator_id} live AMI is invalid",
        )
        _require(
            current_runtime in (binding["runtime_version"], target),
            f"{validator_id} has an unexpected runtime version",
        )
        # Count only the immutable candidate pair. A target runtime repaired
        # in place on its evidence-bound AMI must remain a non-updated baseline
        # until the serial instance replacement proves the target AMI too.
        is_target = current_runtime == target and current_ami == target_ami
        if is_target:
            _require(
                current_ami == target_ami,
                f"{validator_id} target AMI mismatch",
            )
            _target_finality_phase(current, requested_epoch, validator_id)
            canonical._finality_provenance(current, target_runtime=True)
            if binding["target_runtime"]:
                _require(
                    current_instance == binding["instance_id"],
                    f"{validator_id} committed target instance changed",
                )
                _require(
                    _finality_tuple(current, validator_id)
                    == (
                        binding["automatic_finality_enabled"],
                        binding["block_interval_seconds"],
                        binding["slot_epoch_seconds"],
                    ),
                    f"{validator_id} committed target finality state drifted",
                )
            else:
                _require(
                    current_instance != binding["instance_id"],
                    f"{validator_id} target runtime did not replace its "
                    "evidence-bound instance",
                )
            current_phase = _target_finality_phase(
                current, requested_epoch, validator_id
            )
        else:
            _require(
                binding["target_runtime"] is False,
                f"{validator_id} committed target reverted to baseline runtime",
            )
            _require(
                current_runtime == binding["runtime_version"],
                f"{validator_id} runtime drifted from evidence",
            )
            _require(
                current_ami == binding["ami_id"],
                f"{validator_id} runtime and evidence AMI binding mismatch",
            )
            _require(
                current_instance == binding["instance_id"],
                f"{validator_id} changed outside the recoverable live prefix",
            )
            _require(
                _finality_tuple(current, validator_id)
                == (
                    binding["automatic_finality_enabled"],
                    binding["block_interval_seconds"],
                    binding["slot_epoch_seconds"],
                ),
                f"{validator_id} non-target finality state drifted from evidence",
            )
            canonical._finality_provenance(current, target_runtime=False)
            current_phase = "BASELINE"
        updated.append(is_target)
        promoted_bindings.append(
            {
                "validator_id": validator_id,
                "runtime_version": current_runtime,
                "ami_id": current_ami,
                "instance_id": current_instance,
                "volume_id": current.get("volume_id"),
                "target_runtime": is_target,
                "automatic_finality_enabled": current.get(
                    "automatic_finality_enabled"
                ),
                "block_interval_seconds": current.get(
                    "block_interval_seconds"
                ),
                "slot_epoch_seconds": current.get("slot_epoch_seconds"),
                "finality_phase": current_phase,
            }
        )

    _require(
        len(current_heads) == 1,
        "validators disagree on finalized head or certificate",
    )
    _require(
        updated == sorted(updated, reverse=True),
        "validator update order is not contiguous",
    )
    live_count = sum(updated)
    _require(
        evidence_count <= live_count <= min(evidence_count + 1, 3),
        "live prefix must equal the evidence prefix or its one next validator",
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
        "promoted_bindings": promoted_bindings,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def evaluate_evidence_bound_rolling_compatibility(
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    (
        target,
        target_ami,
        _previous,
        _previous_ami,
        order,
        current_validators,
        baseline_validators,
        rollback_by_id,
        evidence_count,
        requested_epoch,
    ) = _common(evidence)
    _require(
        evidence.get("fallback_active") is False,
        "fallback must remain inactive",
    )

    updated: list[bool] = []
    finality_states: list[tuple[bool, int, int | None]] = []
    current_heads: set[tuple[int, str, str]] = set()
    baseline_bindings: list[dict[str, Any]] = []

    for index, validator_id in enumerate(order):
        current = current_validators[index]
        baseline = baseline_validators[index]
        rollback = rollback_by_id[validator_id]
        binding = _baseline_binding(
            index=index,
            validator_id=validator_id,
            baseline=baseline,
            rollback=rollback,
            target=target,
            target_ami=target_ami,
            evidence_count=evidence_count,
            requested_epoch=requested_epoch,
        )
        baseline_bindings.append(binding)

        current_instance = str(current.get("instance_id", ""))
        _require(
            canonical.INSTANCE.fullmatch(current_instance) is not None,
            f"{validator_id} live instance id is invalid",
        )
        _require(
            current.get("volume_id") == rollback.get("volume_id"),
            f"{validator_id} live rollback volume binding mismatch",
        )
        canonical._validator_health(current, rollback)
        current_heads.add(canonical._head(current))

        current_runtime = _text(
            current.get("runtime_version"),
            f"{validator_id}.runtime_version",
        )
        current_ami = _text(
            current.get("ami_id"),
            f"{validator_id}.ami_id",
        )
        _require(
            canonical.SHA256.fullmatch(current_runtime) is not None,
            f"{validator_id} live runtime digest is invalid",
        )
        _require(
            canonical.AMI.fullmatch(current_ami) is not None,
            f"{validator_id} live AMI is invalid",
        )
        is_target = current_runtime == target and current_ami == target_ami
        if is_target:
            _require(
                current_ami == target_ami,
                f"{validator_id} target AMI mismatch",
            )
            _target_finality_phase(current, requested_epoch, validator_id)
            canonical._finality_provenance(current, target_runtime=True)
            if binding["target_runtime"]:
                _require(
                    current_instance == binding["instance_id"],
                    f"{validator_id} committed target instance changed",
                )
            else:
                _require(
                    current_instance != binding["instance_id"],
                    f"{validator_id} target runtime did not replace its "
                    "evidence-bound instance",
                )
        else:
            _require(
                binding["target_runtime"] is False,
                f"{validator_id} committed target reverted to baseline runtime",
            )
            _require(
                current_runtime == binding["runtime_version"],
                f"{validator_id} runtime drifted from evidence",
            )
            _require(
                current_ami == binding["ami_id"],
                f"{validator_id} runtime and evidence AMI binding mismatch",
            )
            _require(
                current_instance == binding["instance_id"],
                f"{validator_id} non-target instance drifted from evidence",
            )
            canonical._finality_provenance(current, target_runtime=False)
        updated.append(is_target)
        finality_states.append(_finality_tuple(current, validator_id))

    _require(
        len(current_heads) == 1,
        "validators disagree on finalized head or certificate",
    )
    _require(
        updated == sorted(updated, reverse=True),
        "validator update order is not contiguous",
    )
    updated_count = sum(updated)
    _require(
        updated_count >= evidence_count,
        "live target prefix is behind the evidence-bound prefix",
    )

    if updated_count < 3:
        _require(
            all(
                state[0] is False
                and state[1] == 0
                and state[2] in (None, 0)
                for state in finality_states
            ),
            "finality and slot epoch must remain quiesced during rolling update",
        )
        state = "READY_FOR_NEXT_VALIDATOR"
        next_validator: str | None = order[updated_count]
    elif all(
        value[0] is False
        and value[1] == 0
        and value[2] in (None, 0)
        for value in finality_states
    ):
        state = "READY_FOR_SLOT_EPOCH"
        next_validator = None
    elif all(
        value == (False, 0, requested_epoch) for value in finality_states
    ):
        state = "READY_FOR_FINALITY_ENABLE"
        next_validator = None
    elif all(
        value == (True, 30, requested_epoch) for value in finality_states
    ):
        state = "ACCEPTED"
        next_validator = None
    else:
        raise EvidenceBoundPrefixError(
            "three target validators have a mixed or non-canonical finality state"
        )

    return {
        "schema_version": "junca-validator-rolling-compatibility/v1",
        "state": state,
        "updated_count": updated_count,
        "next_validator": next_validator,
        "baseline_updated_count": evidence_count,
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
    parser.add_argument(
        "--mode",
        choices=("live-prefix", "rolling"),
        default="live-prefix",
    )
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        evidence = _read(args.evidence)
        if args.mode == "rolling":
            decision = evaluate_evidence_bound_rolling_compatibility(evidence)
        else:
            decision = evaluate_live_rollout_prefix_v2(evidence)
    except (
        OSError,
        json.JSONDecodeError,
        EvidenceBoundPrefixError,
        canonical.RollingCompatibilityError,
    ) as exc:
        result = {
            "schema_version": (
                "junca-validator-rolling-compatibility/v1"
                if args.mode == "rolling"
                else "junca-validator-live-prefix/v2"
            ),
            "state": (
                "EVIDENCE_BOUND_ROLLING_REJECTED"
                if args.mode == "rolling"
                else "EVIDENCE_BOUND_PREFIX_REJECTED"
            ),
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
