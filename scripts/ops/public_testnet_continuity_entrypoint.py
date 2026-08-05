#!/usr/bin/env python3
"""Runtime compatibility entrypoint for Public Testnet continuity evidence.

Only timestamp-labelled fields receive compatibility normalization. Explicit
publication sentinels are treated as absent so canonical fallback paths remain
usable. All other continuity fields retain the canonical strict contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any, Mapping, Sequence

import public_testnet_continuity as continuity


_original_integer = continuity._integer
_original_path = continuity._path
_UNPUBLISHED_SENTINELS = {
    "NOT CURRENTLY PUBLISHED",
    "NOT PUBLISHED",
    "UNPUBLISHED",
    "NOT AVAILABLE",
    "N/A",
}
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


continuity._path = _published_path
continuity._integer = _compatible_integer


if __name__ == "__main__":
    raise SystemExit(continuity.main())
