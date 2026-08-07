#!/usr/bin/env python3
"""Run continuity from independent Health and Explorer public surfaces.

The Health endpoint is the operational anchor for finalized height/hash and
safety flags. Explorer supplies the public network identity, authenticated peer
count, finalized timestamp and certificate projection. Existing values are
never silently overwritten when the two surfaces disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import public_testnet_continuity_entrypoint as compatibility

continuity = compatibility.continuity
_compat_normalize_snapshot = continuity.normalize_snapshot


def _health_value(payload: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        found = compatibility._published_path(payload, path)
        if found is not None:
            return found
    return None


def _explorer_payload() -> Mapping[str, Any]:
    if compatibility._cached_explorer_payload is not None:
        return compatibility._cached_explorer_payload
    payload = compatibility._original_fetch(compatibility._EXPLORER_URL, timeout=15)
    compatibility._cached_explorer_payload = payload
    return payload


def _require_health_contract(
    payload: Mapping[str, Any], explorer_payload: Mapping[str, Any]
) -> tuple[int, str]:
    status = compatibility._published_path(payload, "status")
    if status != "healthy":
        raise continuity.ContinuityError("operational health status must be healthy")
    if compatibility._published_path(payload, "read_only") is not True:
        raise continuity.ContinuityError("operational health must be read-only")

    height_raw = _health_value(payload, "head_height", "validator.head_height")
    hash_raw = _health_value(payload, "head_hash", "validator.head_hash")
    if height_raw is None or hash_raw is None:
        raise continuity.ContinuityError(
            "operational health must independently publish finalized height and hash"
        )
    height = continuity._integer(
        height_raw, "operational health finalized_height"
    )
    if not isinstance(hash_raw, str) or not hash_raw:
        raise continuity.ContinuityError("operational health hash must be a string")

    for key in ("mainnet_changed", "assets_moved", "bridge_activated"):
        health_value = compatibility._published_path(payload, key)
        if health_value is not False:
            raise continuity.ContinuityError(f"operational health {key} must be false")
        explorer_value = compatibility._published_path(explorer_payload, key)
        if explorer_value is not None and explorer_value != health_value:
            raise continuity.ContinuityError(
                f"operational health and Explorer {key} diverge"
            )
    return height, hash_raw


def _health_projection_normalize_snapshot(
    payload: Mapping[str, Any], *, source: str, require_safety: bool
):
    if source != "operational_api":
        return _compat_normalize_snapshot(
            payload, source=source, require_safety=require_safety
        )

    explorer_payload = _explorer_payload()
    explorer = _compat_normalize_snapshot(
        explorer_payload, source="explorer_json", require_safety=False
    )
    health_height, health_hash = _require_health_contract(payload, explorer_payload)
    if health_height != explorer.finalized_height:
        raise continuity.ContinuityError(
            "operational health and Explorer finalized heights diverge"
        )
    if health_hash != explorer.finalized_hash:
        raise continuity.ContinuityError(
            "operational health and Explorer finalized hashes diverge"
        )

    projected = dict(payload)
    projected.update(
        {
            "chain_id": explorer.chain_id,
            "head_height": health_height,
            "authenticated_peer_count": explorer.authenticated_peer_count,
            "last_block_timestamp": explorer.finalized_timestamp,
            "head_hash": health_hash,
            "certificate_hash": explorer.certificate_hash,
            "signed_power": explorer.signed_power,
            "total_power": explorer.total_power,
        }
    )
    return _compat_normalize_snapshot(
        projected, source=source, require_safety=require_safety
    )


continuity.normalize_snapshot = _health_projection_normalize_snapshot


if __name__ == "__main__":
    raise SystemExit(continuity.main())
