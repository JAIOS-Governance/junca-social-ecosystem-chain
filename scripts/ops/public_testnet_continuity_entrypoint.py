#!/usr/bin/env python3
"""Compatibility entrypoint for Public Testnet continuity evidence.

The governed Operational API may expose timestamps as RFC 3339 / ISO 8601 text,
while the continuity contract internally compares Unix epoch seconds. This
entrypoint preserves the existing strict integer contract for every non-time
field and normalizes only timestamp-labelled values before invoking the
canonical sampler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import public_testnet_continuity as continuity


_original_integer = continuity._integer


def _compatible_integer(value: Any, label: str) -> int:
    try:
        return _original_integer(value, label)
    except continuity.ContinuityError:
        if "timestamp" not in label or not isinstance(value, str):
            raise

        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            raise continuity.ContinuityError(
                f"{label} must be an integer or ISO 8601 timestamp"
            ) from None
        if parsed.tzinfo is None:
            raise continuity.ContinuityError(
                f"{label} ISO 8601 timestamp must include a timezone"
            )
        epoch_seconds = int(parsed.timestamp())
        if epoch_seconds < 0:
            raise continuity.ContinuityError(f"{label} must not be negative")
        return epoch_seconds


continuity._integer = _compatible_integer


if __name__ == "__main__":
    raise SystemExit(continuity.main())
