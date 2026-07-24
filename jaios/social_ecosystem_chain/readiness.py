"""Fail-closed release readiness for JUNCA Social Ecosystem Chain."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-social-ecosystem-chain-readiness/v1"
OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
REQUIRED_GATES = (
    "brand-contract",
    "source-provenance",
    "reproducible-build",
    "genesis-fingerprint",
    "new-key-custody",
    "validator-quorum",
    "rpc-method-boundary",
    "explorer-head-parity",
    "governance-readback",
    "rollback-package",
    "independent-post-release-readback",
)
ALLOWED_TARGETS = frozenset({"private-testnet", "public-testnet", "mainnet"})


class ChainReadinessError(RuntimeError):
    """Raised when readiness evidence is malformed or not promotable."""


@dataclass(frozen=True)
class ChainReadiness:
    release_target: str
    source_commit: str
    gates: tuple[tuple[str, bool], ...]

    @property
    def missing_gates(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.gates if not passed)

    @property
    def state(self) -> str:
        return "ready" if not self.missing_gates else "blocked"

    def assert_promotable(self) -> None:
        if self.missing_gates:
            raise ChainReadinessError(
                "release blocked by: " + ", ".join(self.missing_gates)
            )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "release_target": self.release_target,
            "source_commit": self.source_commit,
            "state": self.state,
            "gates": dict(self.gates),
            "missing_gates": list(self.missing_gates),
        }


def load_readiness(path: str | Path) -> ChainReadiness:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainReadinessError(f"unable to load readiness evidence: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainReadinessError("readiness evidence must be an object")
    _require(raw, "schema_version", SCHEMA_VERSION)
    _require(raw, "official_name", OFFICIAL_NAME)

    release_target = _text(raw.get("release_target"), "release_target", 40)
    if release_target not in ALLOWED_TARGETS:
        raise ChainReadinessError("unsupported release_target")
    source_commit = _text(raw.get("source_commit"), "source_commit", 64)
    if source_commit != "pending" and not _is_sha(source_commit):
        raise ChainReadinessError("source_commit must be pending or a 40-character SHA")

    gates_raw = raw.get("gates")
    if not isinstance(gates_raw, Mapping):
        raise ChainReadinessError("gates must be an object")
    received = set(gates_raw)
    expected = set(REQUIRED_GATES)
    if received != expected:
        missing = sorted(expected - received)
        extra = sorted(received - expected)
        raise ChainReadinessError(
            f"gate set mismatch; missing={missing}; extra={extra}"
        )
    gates: list[tuple[str, bool]] = []
    for name in REQUIRED_GATES:
        value = gates_raw[name]
        if not isinstance(value, bool):
            raise ChainReadinessError(f"{name} must be boolean")
        gates.append((name, value))
    return ChainReadiness(
        release_target=release_target,
        source_commit=source_commit,
        gates=tuple(gates),
    )


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise ChainReadinessError(f"{field} must be {expected!r}")


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ChainReadinessError(f"{field} must contain 1-{maximum} characters")
    return value.strip()


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)
