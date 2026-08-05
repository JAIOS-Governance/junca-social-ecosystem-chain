#!/usr/bin/env python3
"""Runtime compatibility entrypoint for Public Testnet continuity evidence.

Only timestamp-labelled fields receive compatibility normalization. All other
continuity fields remain subject to the canonical strict contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any

import public_testnet_continuity as continuity


_original_integer = continuity._integer


def _normalize_epoch(value: float, label: str) -> int:
    if value < 0:
        raise continuity.ContinuityError(f"{label} must not be negative")
    # Accept seconds, milliseconds, microseconds, or nanoseconds from public APIs.
    while value >= 100_000_000_000:
        value /= 1000
    return int(value)


def _parse_timestamp_text(value: str, label: str) -> int:
    candidate = value.strip()

    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", candidate):
        return _normalize_epoch(float(candidate), label)

    normalized = re.sub(r"\s+(UTC|GMT)$", "+00:00", candidate, flags=re.IGNORECASE)
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    # Python accepts microseconds; trim longer RFC3339 fractions deterministically.
    normalized = re.sub(r"(\.\d{6})\d+(?=Z|[+-]\d\d:?\d\d$)", r"\1", normalized)

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
        ):
            try:
                parsed = datetime.strptime(candidate, pattern)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

    if parsed is None:
        raise continuity.ContinuityError(
            f"{label} has an unsupported timestamp representation"
        )
    if parsed.tzinfo is None:
        raise continuity.ContinuityError(
            f"{label} timestamp must include a timezone"
        )
    return _normalize_epoch(parsed.timestamp(), label)


def _compatible_integer(value: Any, label: str) -> int:
    try:
        result = _original_integer(value, label)
    except continuity.ContinuityError:
        if "timestamp" not in label:
            raise
        if isinstance(value, float):
            return _normalize_epoch(value, label)
        if isinstance(value, str):
            return _parse_timestamp_text(value, label)
        raise

    if "timestamp" in label:
        return _normalize_epoch(float(result), label)
    return result


continuity._integer = _compatible_integer


if __name__ == "__main__":
    raise SystemExit(continuity.main())
