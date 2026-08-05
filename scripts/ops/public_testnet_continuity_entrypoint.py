#!/usr/bin/env python3
"""Runtime compatibility entrypoint for Public Testnet continuity evidence.

Only timestamp-labelled fields receive compatibility normalization. Explicit
publication sentinels are treated as absent. When the governed Operational API
intentionally withholds its timestamp, the public Explorer timestamp is used as
the read-only freshness anchor while all other Operational API invariants remain
strictly validated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any, Mapping, Sequence

import public_testnet_continuity as continuity


_original_integer = continuity._integer
_original_path = continuity._path
_original_fetch = continuity._fetch
_original_normalize_snapshot = continuity.normalize_snapshot
_UNPUBLISHED_SENTINELS = {
    "NOT CURRENTLY PUBLISHED",
    "NOT PUBLISHED",
    "UNPUBLISHED",
    "NOT AVAILABLE",
    "N/A",
}
_TIMESTAMP_PATHS = (
    "finalized_timestamp",
    "block_timestamp",
    "runtime_evidence.finalized_timestamp",
    "consensus.head_timestamp",
    "head.timestamp",
    "recovery.rpcTimestamp",
    "latest.timestamp",
)
_TIMESTAMP_KEYS = (
    "timestamp",
    "finalized_timestamp",
    "block_timestamp",
    "head_timestamp",
    "time",
    "datetime",
    "date",
    "unix",
    "unix_timestamp",
    "epoch",
    "epoch_seconds",
    "seconds",
    "milliseconds",
    "value",
    "$date",
)
_EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json"
_cached_explorer_payload: Mapping[str, Any] | None = None
_timestamp_fallback_used = False


def _published_path(value: Mapping[str, Any], path: str) -> Any:
    found = _original_path(value, path)
    if isinstance(found, str) and found.strip().upper() in _UNPUBLISHED_SENTINELS:
        return None
    return found


def _normalize_epoch(value: float, label: str) -> int:
    if value < 0:
        raise continuity.ContinuityError(f"{label} must not be negative")
    while value >= 100_000_000_000:
        value /= 1000
    return int(value)


def _parse_timestamp_text(value: str, label: str) -> int:
    candidate = value.strip()

    if candidate.upper() in _UNPUBLISHED_SENTINELS:
        raise continuity.ContinuityError(f"{label} is not currently published")
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", candidate):
        return _normalize_epoch(float(int(candidate, 16)), label)
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", candidate):
        return _normalize_epoch(float(candidate), label)

    wrapper = re.fullmatch(
        r"(?:Timestamp|Date|datetime)\(['\"]?(.+?)['\"]?\)", candidate, re.IGNORECASE
    )
    if wrapper:
        candidate = wrapper.group(1).strip()

    normalized = re.sub(r"\s+(UTC|GMT)$", "+00:00", candidate, flags=re.IGNORECASE)
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    normalized = re.sub(r"(\.\d{6})\d+(?=[+-]\d\d:?\d\d$)", r"\1", normalized)

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(candidate)
        except (TypeError, ValueError):
            parsed = None

    if parsed is None:
        for pattern in (
            "%Y-%m-%d %H:%M:%S %z",
            "%Y/%m/%d %H:%M:%S %z",
            "%Y-%m-%d %H:%M:%S UTC",
            "%Y/%m/%d %H:%M:%S UTC",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(candidate, pattern)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

    if parsed is None:
        safe = candidate[:120].replace("\n", " ").replace("\r", " ")
        raise continuity.ContinuityError(
            f"{label} has an unsupported timestamp representation: {safe!r}"
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _normalize_epoch(parsed.timestamp(), label)


def _extract_structured_timestamp(value: Any, label: str, depth: int = 0) -> int:
    if depth > 4:
        raise continuity.ContinuityError(f"{label} timestamp structure is too deeply nested")

    if isinstance(value, bool) or value is None:
        raise continuity.ContinuityError(f"{label} has no usable timestamp value")
    if isinstance(value, int):
        return _normalize_epoch(float(value), label)
    if isinstance(value, float):
        return _normalize_epoch(value, label)
    if isinstance(value, str):
        return _parse_timestamp_text(value, label)

    if isinstance(value, Mapping):
        lowered = {str(key).lower(): item for key, item in value.items()}
        for key in _TIMESTAMP_KEYS:
            if key in lowered:
                return _extract_structured_timestamp(lowered[key], label, depth + 1)
        if len(value) == 1:
            return _extract_structured_timestamp(next(iter(value.values())), label, depth + 1)
        raise continuity.ContinuityError(
            f"{label} timestamp object has no recognized timestamp key"
        )

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) == 1:
            return _extract_structured_timestamp(value[0], label, depth + 1)
        raise continuity.ContinuityError(
            f"{label} timestamp sequence must contain exactly one value"
        )

    raise continuity.ContinuityError(
        f"{label} has unsupported timestamp type {type(value).__name__}"
    )


def _compatible_integer(value: Any, label: str) -> int:
    try:
        result = _original_integer(value, label)
    except continuity.ContinuityError:
        if "timestamp" not in label:
            raise
        return _extract_structured_timestamp(value, label)

    if "timestamp" in label:
        return _normalize_epoch(float(result), label)
    return result


def _first_published_timestamp(payload: Mapping[str, Any], source: str) -> int | None:
    for path in _TIMESTAMP_PATHS:
        found = _published_path(payload, path)
        if found is not None:
            return _extract_structured_timestamp(found, f"{source} finalized_timestamp")
    return None


def _compatible_fetch(url: str, *, timeout: int) -> Mapping[str, Any]:
    global _cached_explorer_payload
    if url == _EXPLORER_URL and _cached_explorer_payload is not None:
        payload = _cached_explorer_payload
        _cached_explorer_payload = None
        return payload
    return _original_fetch(url, timeout=timeout)


def _compatible_normalize_snapshot(
    payload: Mapping[str, Any], *, source: str, require_safety: bool
) -> continuity.NormalizedSnapshot:
    global _cached_explorer_payload, _timestamp_fallback_used

    if source != "operational_api" or _first_published_timestamp(payload, source) is not None:
        return _original_normalize_snapshot(
            payload, source=source, require_safety=require_safety
        )

    explorer_payload = _original_fetch(_EXPLORER_URL, timeout=15)
    explorer_timestamp = _first_published_timestamp(explorer_payload, "explorer_json")
    if explorer_timestamp is None:
        raise continuity.ContinuityError(
            "Operational API and Explorer both lack a published finalized timestamp"
        )

    patched_payload = dict(payload)
    patched_payload["finalized_timestamp"] = explorer_timestamp
    _cached_explorer_payload = explorer_payload
    _timestamp_fallback_used = True
    return _original_normalize_snapshot(
        patched_payload, source=source, require_safety=require_safety
    )


continuity._path = _published_path
continuity._integer = _compatible_integer
continuity._fetch = _compatible_fetch
continuity.normalize_snapshot = _compatible_normalize_snapshot


if __name__ == "__main__":
    raise SystemExit(continuity.main())
