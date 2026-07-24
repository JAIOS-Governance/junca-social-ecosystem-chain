"""Scale and extension architecture contract for JUNCA Social Ecosystem Chain v2."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


class ChainArchitectureError(RuntimeError):
    """Raised when the v2 scale or extension architecture is incomplete."""


REQUIRED_EXTENSION_BOUNDARIES = frozenset({
    "execution-client",
    "consensus-engine",
    "precompile-registry",
    "bridge-adapter",
    "indexer-sink",
    "rpc-policy",
    "fee-policy",
    "governance-adapter",
})


@dataclass(frozen=True)
class ChainScaleProfile:
    generation: str
    sustained_tps_target: int
    burst_tps_target: int
    finality_p95_seconds: int
    rpc_read_p95_ms: int
    availability_target_percent: float
    validators: int
    validator_quorum: int
    rpc_nodes: int
    indexer_nodes: int
    archive_nodes: int
    failure_domains: int
    extension_boundaries: tuple[str, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-social-ecosystem-chain-scale-profile/v1",
            "generation": self.generation,
            "targets": {
                "sustained_tps": self.sustained_tps_target,
                "burst_tps": self.burst_tps_target,
                "finality_p95_seconds": self.finality_p95_seconds,
                "rpc_read_p95_ms": self.rpc_read_p95_ms,
                "availability_percent": self.availability_target_percent,
            },
            "topology": {
                "validators": self.validators,
                "validator_quorum": self.validator_quorum,
                "rpc_nodes": self.rpc_nodes,
                "indexer_nodes": self.indexer_nodes,
                "archive_nodes": self.archive_nodes,
                "failure_domains": self.failure_domains,
            },
            "extension_boundaries": list(self.extension_boundaries),
            "architecture_status": "valid",
            "performance_status": "target-not-yet-benchmarked",
        }


def load_scale_profile(path: str | Path) -> ChainScaleProfile:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainArchitectureError(f"unable to load scale profile: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainArchitectureError("scale profile must be a JSON object")
    _require(raw, "schema_version", "junca-social-ecosystem-chain-scale-profile/v1")
    _require(raw, "generation", "sovereign-v2")
    _require(raw, "legacy_protocol_role", "audit-reference-only")

    targets = _mapping(raw.get("performance_targets"), "performance_targets")
    sustained = _positive_int(targets.get("sustained_tps"), "sustained_tps")
    burst = _positive_int(targets.get("burst_tps"), "burst_tps")
    finality = _positive_int(targets.get("finality_p95_seconds"), "finality_p95_seconds")
    rpc_latency = _positive_int(targets.get("rpc_read_p95_ms"), "rpc_read_p95_ms")
    availability = targets.get("availability_percent")
    if not isinstance(availability, (int, float)) or isinstance(availability, bool):
        raise ChainArchitectureError("availability_percent must be numeric")
    availability = float(availability)
    if sustained < 2_000 or burst < 5_000 or burst < sustained:
        raise ChainArchitectureError("v2 throughput targets must be at least 2k/5k TPS")
    if finality > 6 or rpc_latency > 250 or availability < 99.95:
        raise ChainArchitectureError("v2 latency or availability target is below baseline")
    _require(targets, "status", "target-not-guarantee")

    topology = _mapping(raw.get("production_topology"), "production_topology")
    validators = _positive_int(topology.get("validators"), "validators")
    quorum = _positive_int(topology.get("validator_quorum"), "validator_quorum")
    rpc_nodes = _positive_int(topology.get("rpc_nodes"), "rpc_nodes")
    indexers = _positive_int(topology.get("indexer_nodes"), "indexer_nodes")
    archives = _positive_int(topology.get("archive_nodes"), "archive_nodes")
    domains = _positive_int(topology.get("failure_domains"), "failure_domains")
    if validators < 9 or quorum < 7 or quorum > validators:
        raise ChainArchitectureError("production topology requires validators 9 / quorum 7")
    if quorum * 100 <= validators * 75:
        raise ChainArchitectureError("validator quorum must exceed 75 percent")
    if rpc_nodes < 6 or indexers < 3 or archives < 2 or domains < 5:
        raise ChainArchitectureError("production topology is below sovereign-v2 baseline")

    storage = _mapping(raw.get("state_and_storage"), "state_and_storage")
    _require(storage, "full_node_mode", "pruned-with-snapshots")
    _require(storage, "archive_tier", "isolated")
    if storage.get("state_snapshot_export") is not True:
        raise ChainArchitectureError("state_snapshot_export must be true")
    if storage.get("online_schema_migration") is not True:
        raise ChainArchitectureError("online_schema_migration must be true")

    extension = _mapping(raw.get("extension_architecture"), "extension_architecture")
    boundaries_raw = extension.get("boundaries")
    if not isinstance(boundaries_raw, list) or not all(
        isinstance(item, str) and item for item in boundaries_raw
    ):
        raise ChainArchitectureError("extension boundaries must be a string list")
    boundaries = tuple(boundaries_raw)
    if len(boundaries) != len(set(boundaries)):
        raise ChainArchitectureError("extension boundaries contain duplicates")
    missing = REQUIRED_EXTENSION_BOUNDARIES.difference(boundaries)
    if missing:
        raise ChainArchitectureError(
            f"extension boundaries missing: {', '.join(sorted(missing))}"
        )
    _require(extension, "api_versioning", "semver-and-capability-negotiation")
    if extension.get("consensus_coupled_business_logic") is not False:
        raise ChainArchitectureError("business logic must not be coupled to consensus")

    gates = _mapping(raw.get("verification_gates"), "verification_gates")
    for field in (
        "load_test_passed",
        "chaos_test_passed",
        "state_growth_test_passed",
        "upgrade_rehearsal_passed",
        "bridge_security_review_passed",
        "public_slo_claim_allowed",
    ):
        if gates.get(field) is not False:
            raise ChainArchitectureError(f"verification_gates.{field} must start false")

    return ChainScaleProfile(
        generation="sovereign-v2",
        sustained_tps_target=sustained,
        burst_tps_target=burst,
        finality_p95_seconds=finality,
        rpc_read_p95_ms=rpc_latency,
        availability_target_percent=availability,
        validators=validators,
        validator_quorum=quorum,
        rpc_nodes=rpc_nodes,
        indexer_nodes=indexers,
        archive_nodes=archives,
        failure_domains=domains,
        extension_boundaries=boundaries,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChainArchitectureError(f"{field} must be an object")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ChainArchitectureError(f"{field} must be a positive integer")
    return value


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise ChainArchitectureError(f"{field} must be {expected!r}")
