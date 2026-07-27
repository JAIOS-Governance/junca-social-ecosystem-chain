"""Fail-closed compatibility gate for three-validator runtime rollouts."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


SHA256 = re.compile(r"[0-9a-f]{64}")
BOUNDARIES = ("mainnet_changed", "assets_moved", "bridge_activated")


class RollingCompatibilityError(ValueError):
    """Raised when a rollout observation cannot safely advance."""


def evaluate_rolling_compatibility(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    target = _text(evidence.get("target_version"), "target_version")
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

    rollback = evidence.get("rollback")
    if not isinstance(rollback, Mapping):
        raise RollingCompatibilityError("rollback evidence is required")
    previous = _text(rollback.get("target_version"), "rollback.target_version")
    if previous == target:
        raise RollingCompatibilityError("rollback target must precede target version")
    if not SHA256.fullmatch(str(rollback.get("artifact_sha256", ""))):
        raise RollingCompatibilityError("rollback artifact digest is invalid")
    if (
        rollback.get("rehearsal_passed") is not True
        or rollback.get("automatic_finality_disabled") is not True
    ):
        raise RollingCompatibilityError("rollback is not fail-closed")

    enabled = [item.get("automatic_finality_enabled") for item in validators]
    if any(value not in (True, False) for value in enabled):
        raise RollingCompatibilityError("automatic finality readback is invalid")
    if any(enabled) and not all(enabled):
        raise RollingCompatibilityError("mixed automatic finality state is prohibited")

    healthy = [item for item in validators if item.get("healthy") is True]
    if len(healthy) < 2:
        raise RollingCompatibilityError("validator quorum is unavailable")
    heads = {(item.get("head_height"), item.get("head_hash")) for item in healthy}
    if len(heads) != 1:
        raise RollingCompatibilityError("healthy validators disagree on finalized head")

    versions = [by_id[validator_id].get("runtime_version") for validator_id in order]
    if any(not isinstance(version, str) or not version for version in versions):
        raise RollingCompatibilityError("runtime version readback is incomplete")
    updated = [version == target for version in versions]
    if updated != sorted(updated, reverse=True):
        raise RollingCompatibilityError("validator update order is not contiguous")
    if any(version not in (previous, target) for version in versions):
        raise RollingCompatibilityError("unexpected runtime version detected")

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

    configured = [item.get("slot_epoch_seconds") for item in validators]
    updated_count = sum(updated)
    if updated_count < 3:
        if any(enabled) or any(value is not None for value in configured):
            raise RollingCompatibilityError(
                "finality and slot epoch must remain disabled during rolling update"
            )
        return _decision(
            "READY_FOR_NEXT_VALIDATOR",
            next_validator=order[updated_count],
            updated_count=updated_count,
        )

    if len(healthy) != 3:
        raise RollingCompatibilityError(
            "all validators must be healthy after version rollout"
        )
    if len(set(versions)) != 1:
        raise RollingCompatibilityError("validator runtime versions do not match")
    if all(value is None for value in configured):
        if any(enabled):
            raise RollingCompatibilityError("finality enabled before slot epoch")
        return _decision("READY_FOR_SLOT_EPOCH", updated_count=3)
    if any(value != requested_epoch for value in configured):
        raise RollingCompatibilityError("slot epoch readback mismatch")
    if not all(enabled):
        return _decision("READY_FOR_FINALITY_ENABLE", updated_count=3)
    return _decision("ACCEPTED", updated_count=3)


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
