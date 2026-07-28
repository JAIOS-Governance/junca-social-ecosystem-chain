"""Evidence-based Mainnet Candidate performance acceptance evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "junca-mainnet-performance-acceptance/v1"


class PerformanceAcceptanceError(ValueError):
    """Raised when performance evidence is malformed."""


@dataclass(frozen=True)
class MainnetPerformanceTargets:
    sustained_tps: int = 2_000
    burst_tps: int = 5_000
    finality_p95_seconds: float = 6.0
    rpc_read_p95_ms: float = 250.0
    availability_percent: float = 99.95
    maximum_error_percent: float = 0.10
    minimum_observation_hours: int = 24

    def __post_init__(self) -> None:
        for field in ("sustained_tps", "burst_tps", "minimum_observation_hours"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise PerformanceAcceptanceError(f"{field} must be positive")
        for field in (
            "finality_p95_seconds",
            "rpc_read_p95_ms",
            "availability_percent",
            "maximum_error_percent",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise PerformanceAcceptanceError(f"{field} must be positive")
        if self.burst_tps < self.sustained_tps:
            raise PerformanceAcceptanceError("burst_tps is below sustained_tps")
        if not 0 < self.availability_percent <= 100:
            raise PerformanceAcceptanceError("availability_percent is invalid")
        if not 0 < self.maximum_error_percent < 100:
            raise PerformanceAcceptanceError("maximum_error_percent is invalid")


@dataclass(frozen=True)
class PerformanceObservation:
    sustained_tps: float
    burst_tps: float
    finality_p95_seconds: float
    rpc_read_p95_ms: float
    availability_percent: float
    error_percent: float
    observation_hours: float
    validator_count: int
    failure_domains: int
    load_test_passed: bool
    chaos_test_passed: bool
    state_growth_test_passed: bool
    upgrade_rehearsal_passed: bool

    def __post_init__(self) -> None:
        numeric = (
            "sustained_tps",
            "burst_tps",
            "finality_p95_seconds",
            "rpc_read_p95_ms",
            "availability_percent",
            "error_percent",
            "observation_hours",
        )
        for field in numeric:
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise PerformanceAcceptanceError(f"{field} must be non-negative")
        for field in ("validator_count", "failure_domains"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise PerformanceAcceptanceError(f"{field} must be positive")
        for field in (
            "load_test_passed",
            "chaos_test_passed",
            "state_growth_test_passed",
            "upgrade_rehearsal_passed",
        ):
            if not isinstance(getattr(self, field), bool):
                raise PerformanceAcceptanceError(f"{field} must be boolean")


def evaluate_performance(
    observation: PerformanceObservation,
    *,
    targets: MainnetPerformanceTargets | None = None,
) -> dict[str, Any]:
    if not isinstance(observation, PerformanceObservation):
        raise PerformanceAcceptanceError("performance observation is required")
    policy = MainnetPerformanceTargets() if targets is None else targets
    if not isinstance(policy, MainnetPerformanceTargets):
        raise PerformanceAcceptanceError("performance targets are required")

    checks = {
        "sustained_tps": observation.sustained_tps >= policy.sustained_tps,
        "burst_tps": observation.burst_tps >= policy.burst_tps,
        "finality_p95": observation.finality_p95_seconds <= policy.finality_p95_seconds,
        "rpc_read_p95": observation.rpc_read_p95_ms <= policy.rpc_read_p95_ms,
        "availability": observation.availability_percent >= policy.availability_percent,
        "error_rate": observation.error_percent <= policy.maximum_error_percent,
        "observation_duration": observation.observation_hours >= policy.minimum_observation_hours,
        "validator_scale": observation.validator_count >= 9,
        "failure_domains": observation.failure_domains >= 5,
        "load_test": observation.load_test_passed,
        "chaos_test": observation.chaos_test_passed,
        "state_growth_test": observation.state_growth_test_passed,
        "upgrade_rehearsal": observation.upgrade_rehearsal_passed,
    }
    accepted = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": accepted,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "public_slo_claim_allowed": accepted,
        "activation_status": "CANDIDATE_NOT_ACTIVATED",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
