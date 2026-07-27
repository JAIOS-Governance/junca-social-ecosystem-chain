"""Fail-closed Candidate Mainnet and Mainnet release gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "junca-mainnet-readiness/v1"
REQUIRED_GATES = (
    "public_testnet_runtime_acceptance",
    "sustained_finality",
    "quorum_loss_recovery",
    "node_replacement_recovery",
    "rpc_boundary",
    "explorer_parity",
    "rollback_rehearsal",
    "independent_security_review",
    "legacy_mainnet_snapshot_audit",
    "continuity_decision",
    "mainnet_genesis_approved",
    "mainnet_key_custody",
    "mainnet_validator_topology",
    "independent_post_release_readback",
    "governance_release_approval",
)


class MainnetReadinessError(ValueError):
    """Raised when Mainnet evidence is malformed or promotion is unsafe."""


@dataclass(frozen=True)
class MainnetReadiness:
    source_commit: str
    gates: tuple[tuple[str, bool], ...]
    assets_moved: bool
    bridge_activated: bool

    @property
    def missing_gates(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.gates if not passed)

    @property
    def state(self) -> str:
        return "ready" if not self.missing_gates else "blocked"

    def assert_candidate_mainnet_ready(self) -> None:
        if self.assets_moved or self.bridge_activated:
            raise MainnetReadinessError(
                "assets and bridge must remain inactive during Candidate Mainnet"
            )
        if self.missing_gates:
            raise MainnetReadinessError(
                "Candidate Mainnet blocked by: " + ", ".join(self.missing_gates)
            )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "release_stage": "candidate-mainnet",
            "source_commit": self.source_commit,
            "state": self.state,
            "gates": dict(self.gates),
            "missing_gates": list(self.missing_gates),
            "mainnet_changed": False,
            "assets_moved": self.assets_moved,
            "bridge_activated": self.bridge_activated,
        }


def evaluate_mainnet_readiness(evidence: Mapping[str, Any]) -> MainnetReadiness:
    if not isinstance(evidence, Mapping):
        raise MainnetReadinessError("evidence must be an object")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise MainnetReadinessError("unsupported schema_version")
    source_commit = evidence.get("source_commit")
    if not isinstance(source_commit, str) or not _is_sha(source_commit):
        raise MainnetReadinessError("source_commit must be a lowercase commit SHA")

    gates = evidence.get("gates")
    if not isinstance(gates, Mapping) or set(gates) != set(REQUIRED_GATES):
        raise MainnetReadinessError("Mainnet gate set mismatch")
    ordered: list[tuple[str, bool]] = []
    for name in REQUIRED_GATES:
        value = gates[name]
        if not isinstance(value, bool):
            raise MainnetReadinessError(f"{name} must be boolean")
        ordered.append((name, value))

    for boundary in ("assets_moved", "bridge_activated"):
        if evidence.get(boundary) is not False:
            raise MainnetReadinessError(
                f"{boundary} must remain false during Candidate Mainnet"
            )
    if evidence.get("mainnet_changed") is not False:
        raise MainnetReadinessError(
            "Mainnet deployment requires a separate terminal release action"
        )

    return MainnetReadiness(
        source_commit=source_commit,
        gates=tuple(ordered),
        assets_moved=False,
        bridge_activated=False,
    )


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)
