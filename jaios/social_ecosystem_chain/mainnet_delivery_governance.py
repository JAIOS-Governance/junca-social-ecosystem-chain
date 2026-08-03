"""Fail-closed governance for continuous JSEC Mainnet implementation delivery."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "jsec-mainnet-delivery-cell/v1"
CLAIM_SCHEMA_VERSION = "jsec-mainnet-delivery-claim/v1"
GOVERNANCE = "JAIOS Institutional Governance"
ACTIVE_CELL = "JSEC Mainnet Native Release Engineering Cell"
ACTIVE_POSITION = "Mainnet Protocol Delivery & Release Lead"
PRIOR_CELL = "JSEC Native Genesis Release Cell"
TARGET_RELEASE_DATE = "2026-10-01"
MANDATORY_SEQUENCE = (
    "development",
    "repair-and-refinement",
    "audit",
    "activation",
    "monitoring",
    "post-activation-repair-and-refinement",
    "stabilization",
)
REQUIRED_PROGRESS_EVIDENCE = (
    "source_commit",
    "changed_paths",
    "tests",
    "next_unblocked_task",
)
SAFETY_FIELDS = (
    "mainnet_changed",
    "genesis_applied",
    "assets_moved",
    "bridge_activated",
    "mainnet_activation_authorized",
)
IMPLEMENTATION_PREFIXES = (
    "contracts/",
    "infra/",
    "infrastructure/",
    "jaios/",
    "packaging/",
    "scripts/",
)


class MainnetDeliveryGovernanceError(ValueError):
    """Raised when a Mainnet delivery cell or progress claim violates policy."""


@dataclass(frozen=True)
class MainnetDeliveryCell:
    name: str
    position: str
    current_phase: str
    target_release_date: str
    prior_cell: str
    prior_cell_status: str
    public_testnet_must_remain_running: bool
    safety: Mapping[str, bool]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "governance": GOVERNANCE,
            "state": "ACTIVE_IMPLEMENTATION",
            "active_cell": self.name,
            "position": self.position,
            "current_phase": self.current_phase,
            "target_release_date": self.target_release_date,
            "prior_cell": self.prior_cell,
            "prior_cell_status": self.prior_cell_status,
            "monitoring_only_is_governance_violation": True,
            "public_testnet_must_remain_running": (
                self.public_testnet_must_remain_running
            ),
            "safety": dict(self.safety),
        }

    def evaluate_progress_claim(self, claim: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(claim, Mapping):
            raise MainnetDeliveryGovernanceError("delivery claim must be an object")
        _exact(claim, "schema_version", CLAIM_SCHEMA_VERSION)
        _exact(claim, "cell", self.name)
        _exact(claim, "phase", self.current_phase)

        progress_type = _text(claim.get("progress_type"), "progress_type", 40)
        if progress_type == "monitoring":
            raise MainnetDeliveryGovernanceError(
                "monitoring-only Mainnet delivery is a governance violation"
            )
        if progress_type not in {"implementation", "repair", "audit-fix"}:
            raise MainnetDeliveryGovernanceError(
                "progress_type must produce Mainnet implementation"
            )

        source_commit = _text(claim.get("source_commit"), "source_commit", 40)
        if not _is_sha(source_commit):
            raise MainnetDeliveryGovernanceError(
                "source_commit must be a lowercase 40-character commit SHA"
            )

        changed_paths = claim.get("changed_paths")
        if not isinstance(changed_paths, list) or not changed_paths:
            raise MainnetDeliveryGovernanceError("changed_paths must be non-empty")
        normalized_paths = tuple(
            _text(path, f"changed_paths[{index}]", 300)
            for index, path in enumerate(changed_paths)
        )
        if not any(path.startswith(IMPLEMENTATION_PREFIXES) for path in normalized_paths):
            raise MainnetDeliveryGovernanceError(
                "delivery claim lacks a Mainnet implementation path"
            )

        tests = claim.get("tests")
        if not isinstance(tests, Mapping):
            raise MainnetDeliveryGovernanceError("tests must be an object")
        passed = _non_negative_integer(tests.get("passed"), "tests.passed")
        failed = _non_negative_integer(tests.get("failed"), "tests.failed")
        if passed == 0 or failed != 0:
            raise MainnetDeliveryGovernanceError(
                "delivery progress requires passing tests and zero failures"
            )

        next_task = _text(
            claim.get("next_unblocked_task"), "next_unblocked_task", 300
        )
        safety = claim.get("safety")
        _validate_safety(safety)

        return {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "state": "IMPLEMENTATION_PROGRESS_VERIFIED",
            "cell": self.name,
            "phase": self.current_phase,
            "progress_type": progress_type,
            "source_commit": source_commit,
            "changed_paths": list(normalized_paths),
            "tests": {"passed": passed, "failed": failed},
            "next_unblocked_task": next_task,
            "monitoring_counted_as_progress": False,
            "safety": dict(safety),
        }


def load_mainnet_delivery_cell(
    path: str | Path = "config/jsec_mainnet_delivery_cell_v1.json",
) -> MainnetDeliveryCell:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetDeliveryGovernanceError(
            "unable to load Mainnet delivery cell"
        ) from exc
    return evaluate_mainnet_delivery_cell(raw)


def evaluate_mainnet_delivery_cell(
    raw: Mapping[str, Any],
) -> MainnetDeliveryCell:
    if not isinstance(raw, Mapping):
        raise MainnetDeliveryGovernanceError("delivery cell must be an object")
    _exact(raw, "schema_version", SCHEMA_VERSION)
    _exact(raw, "governance", GOVERNANCE)

    decision = _mapping(raw.get("decision"), "decision")
    _exact(decision, "effective_date", "2026-08-01")
    _exact(decision, "prior_cell", PRIOR_CELL)
    _exact(decision, "prior_cell_status", "disqualified")
    _exact(
        decision,
        "reason",
        "monitoring-only delivery without source implementation progress",
    )

    active = _mapping(raw.get("active_cell"), "active_cell")
    _exact(active, "name", ACTIVE_CELL)
    _exact(active, "position", ACTIVE_POSITION)
    _exact(active, "status", "active")
    _exact(active, "target_release_date", TARGET_RELEASE_DATE)
    _exact(active, "current_phase", "development")
    _exact(active, "mandatory_sequence", list(MANDATORY_SEQUENCE))
    _exact(active, "progress_policy", "implementation-evidence-required")

    rules = _mapping(raw.get("delivery_rules"), "delivery_rules")
    _exact(rules, "monitoring_only_is_governance_violation", True)
    _exact(rules, "monitoring_is_progress", False)
    _exact(rules, "public_testnet_must_remain_running", True)
    _exact(rules, "required_progress_evidence", list(REQUIRED_PROGRESS_EVIDENCE))
    _exact(rules, "blocked_requires_unique_cause", True)
    _exact(rules, "blocked_requires_repair_action", True)

    safety = _mapping(raw.get("safety"), "safety")
    _validate_safety(safety)
    return MainnetDeliveryCell(
        name=ACTIVE_CELL,
        position=ACTIVE_POSITION,
        current_phase="development",
        target_release_date=TARGET_RELEASE_DATE,
        prior_cell=PRIOR_CELL,
        prior_cell_status="disqualified",
        public_testnet_must_remain_running=True,
        safety=dict(safety),
    )


def _validate_safety(value: Any) -> None:
    safety = _mapping(value, "safety")
    if set(safety) != set(SAFETY_FIELDS):
        raise MainnetDeliveryGovernanceError("safety field set mismatch")
    for field in SAFETY_FIELDS:
        _exact(safety, field, False)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MainnetDeliveryGovernanceError(f"{field} must be an object")
    return value


def _exact(mapping: Mapping[str, Any], field: str, expected: Any) -> None:
    if mapping.get(field) != expected:
        raise MainnetDeliveryGovernanceError(f"{field} must be {expected!r}")


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise MainnetDeliveryGovernanceError(
            f"{field} must contain 1-{maximum} characters"
        )
    return value.strip()


def _non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MainnetDeliveryGovernanceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )
