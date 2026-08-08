"""Machine-readable Mainnet development gap matrix validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-mainnet-development-gap-matrix/v1"
REQUIRED_DOMAINS = (
    "protocol",
    "consensus-finality",
    "execution-state",
    "transaction-lifecycle",
    "validator-network",
    "p2p-networking",
    "rpc",
    "runtime-upgrade",
    "governance",
    "security",
    "performance-scalability",
    "explorer-indexer",
    "sdk-application-integration",
    "interoperability",
    "immutable-infrastructure",
    "mainnet-release-candidate",
    "production-acceptance",
)


class MainnetGapMatrixError(ValueError):
    """Raised when the Mainnet development matrix is incomplete or misleading."""


class GapStatus(str, Enum):
    IMPLEMENTED_FOUNDATION = "IMPLEMENTED_FOUNDATION"
    ACTIVE_IMPLEMENTATION = "ACTIVE_IMPLEMENTATION"
    PARTIAL = "PARTIAL"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass(frozen=True)
class MainnetGap:
    domain: str
    status: GapStatus
    evidence: tuple[str, ...]
    remaining: tuple[str, ...]
    completion_gate: str

    def __post_init__(self) -> None:
        if self.domain not in REQUIRED_DOMAINS:
            raise MainnetGapMatrixError("unknown Mainnet development domain")
        if not isinstance(self.status, GapStatus):
            raise MainnetGapMatrixError("gap status is invalid")
        for field in ("evidence", "remaining"):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise MainnetGapMatrixError(f"{field} must be a tuple of text")
        if not isinstance(self.completion_gate, str) or not self.completion_gate.strip():
            raise MainnetGapMatrixError("completion_gate is required")
        if self.status is GapStatus.NOT_IMPLEMENTED and self.evidence:
            raise MainnetGapMatrixError("NOT_IMPLEMENTED domain cannot claim evidence")
        if self.status is not GapStatus.NOT_IMPLEMENTED and not self.evidence:
            raise MainnetGapMatrixError("implemented or active domain requires evidence")


@dataclass(frozen=True)
class MainnetDevelopmentGapMatrix:
    base_sha: str
    entries: tuple[MainnetGap, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base_sha, str)
            or len(self.base_sha) != 40
            or any(char not in "0123456789abcdef" for char in self.base_sha)
        ):
            raise MainnetGapMatrixError("base_sha must be a lowercase Git SHA")
        if not isinstance(self.entries, tuple):
            raise MainnetGapMatrixError("entries must be a tuple")
        domains = tuple(item.domain for item in self.entries)
        if domains != REQUIRED_DOMAINS:
            raise MainnetGapMatrixError(
                "gap matrix must contain every required domain in canonical order"
            )

    @property
    def completion_allowed(self) -> bool:
        return False

    @property
    def active_domains(self) -> tuple[str, ...]:
        return tuple(
            item.domain
            for item in self.entries
            if item.status is GapStatus.ACTIVE_IMPLEMENTATION
        )

    @property
    def pending_domains(self) -> tuple[str, ...]:
        return tuple(
            item.domain
            for item in self.entries
            if item.status
            in {
                GapStatus.PARTIAL,
                GapStatus.ACCEPTANCE_PENDING,
                GapStatus.NOT_IMPLEMENTED,
            }
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "base_sha": self.base_sha,
            "domains": [
                {
                    "domain": item.domain,
                    "status": item.status.value,
                    "evidence": list(item.evidence),
                    "remaining": list(item.remaining),
                    "completion_gate": item.completion_gate,
                }
                for item in self.entries
            ],
            "active_domains": list(self.active_domains),
            "pending_domains": list(self.pending_domains),
            "completion_allowed": self.completion_allowed,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def load_mainnet_gap_matrix(path: str | Path) -> MainnetDevelopmentGapMatrix:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetGapMatrixError("unable to load Mainnet gap matrix") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
        raise MainnetGapMatrixError("gap matrix schema is invalid")
    values = raw.get("domains")
    if not isinstance(values, list):
        raise MainnetGapMatrixError("domains must be a list")
    entries: list[MainnetGap] = []
    required_fields = {
        "domain",
        "status",
        "evidence",
        "remaining",
        "completion_gate",
    }
    for value in values:
        if not isinstance(value, Mapping) or set(value) != required_fields:
            raise MainnetGapMatrixError("gap entry fields are invalid")
        try:
            status = GapStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise MainnetGapMatrixError("gap status is invalid") from exc
        evidence = value["evidence"]
        remaining = value["remaining"]
        if not isinstance(evidence, list) or not isinstance(remaining, list):
            raise MainnetGapMatrixError("gap evidence and remaining must be lists")
        entries.append(
            MainnetGap(
                domain=value["domain"],
                status=status,
                evidence=tuple(evidence),
                remaining=tuple(remaining),
                completion_gate=value["completion_gate"],
            )
        )
    return MainnetDevelopmentGapMatrix(
        base_sha=raw.get("base_sha"),
        entries=tuple(entries),
    )
