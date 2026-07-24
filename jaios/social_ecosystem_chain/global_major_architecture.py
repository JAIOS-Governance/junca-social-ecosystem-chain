"""Fail-closed controls for Global Major Chain Architecture v1.

This module validates architecture intent, measurable capability claims, roadmap
gates, benchmark plans, security controls, and competitor evidence without
claiming unobserved runtime properties.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
SCHEMA_VERSION = "junca-global-major-chain-architecture/v1"
BOUNDARIES = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
REQUIRED_ONE_CORE = {"knowledge", "production", "governance", "ai", "capital"}
REQUIRED_TRUST = {
    "identity",
    "compliance",
    "payment",
    "data",
    "auditability",
    "reporting",
}
REQUIRED_AXES = {
    "one_core",
    "trust_stack",
    "protocol_kernel",
    "execution",
    "developer_experience",
    "enterprise_adoption",
    "scalability",
    "security",
    "interoperability",
    "ai_native_operations",
    "global_operations",
    "ecosystem_selection",
    "roadmap",
}
REQUIRED_METRICS = {
    "throughput",
    "finality",
    "latency",
    "state_growth",
    "availability",
}
REQUIRED_BENCHMARKS = {"load", "soak", "chaos", "state_growth"}
REQUIRED_COMPETITORS = {
    "JUNCA Social Ecosystem Chain",
    "Ethereum",
    "Solana",
    "Avalanche",
    "Polygon",
    "BNB Chain",
    "TRON",
}
REQUIRED_DIMENSIONS = {
    "compatibility",
    "performance",
    "security",
    "operations",
    "enterprise_adoption",
    "regulatory_evidence",
    "cost",
    "developer_experience",
}
REQUIRED_ROADMAP = (
    "public-testnet",
    "partner-testnet",
    "security-review",
    "candidate-mainnet",
    "mainnet",
)
REQUIRED_AI_ROUTES = {
    "read",
    "write",
    "execute",
    "evidence",
    "approval",
    "maintenance",
}
REQUIRED_BRIDGE_ROUTES = {"bsc-testnet", "tron-shasta"}
PROHIBITED_CLAIMS = (
    "世界一",
    "world's best",
    "world best",
    "best blockchain",
    "superior to every",
    "outperforms all",
)
PROHIBITED_SECRET_FIELDS = (
    "private_key",
    "privatekey",
    "mnemonic",
    "seed_phrase",
    "seedphrase",
    "secret_value",
    "password",
)


class GlobalArchitectureError(ValueError):
    """Raised when an architecture artifact violates a release boundary."""


@dataclass(frozen=True)
class ArchitectureEvidence:
    state: str
    controls: Mapping[str, bool]
    blockers: tuple[str, ...]
    evidence_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "governance": GOVERNANCE,
            "notice": NOTICE,
            "state": self.state,
            "controls": dict(self.controls),
            "blockers": list(self.blockers),
            "evidence_digest": self.evidence_digest,
            **BOUNDARIES,
        }


def evaluate_global_architecture(
    architecture: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    selection_matrix: Mapping[str, Any],
    roadmap: Mapping[str, Any],
    benchmark_plan: Mapping[str, Any],
    security_plan: Mapping[str, Any],
) -> ArchitectureEvidence:
    documents = {
        "architecture": architecture,
        "capabilities": capabilities,
        "selection_matrix": selection_matrix,
        "roadmap": roadmap,
        "benchmark_plan": benchmark_plan,
        "security_plan": security_plan,
    }
    for name, document in documents.items():
        _validate_common(document, name)
    _reject_prohibited_claims(documents)
    _reject_secret_material(documents)

    controls = {
        "architecture_axes": _architecture_axes(architecture),
        "one_core_contract": _one_core(architecture),
        "trust_stack": _trust_stack(architecture),
        "protocol_kernel": _protocol_kernel(architecture),
        "execution_modularity": _execution(architecture),
        "developer_experience": _developer_experience(architecture),
        "enterprise_adoption": _enterprise_adoption(architecture),
        "scalability_measurement": _scalability(architecture),
        "security_architecture": _security_axis(architecture),
        "interoperability_boundary": _interoperability(architecture),
        "ai_native_routing": _ai_native(architecture),
        "global_operations": _global_operations(architecture),
        "capability_registry": _capability_registry(capabilities),
        "selection_matrix": _selection_matrix(selection_matrix),
        "roadmap_gates": _roadmap(roadmap),
        "benchmark_plan": _benchmark_plan(benchmark_plan),
        "security_plan": _security_plan(security_plan),
    }
    blockers = tuple(sorted(name for name, passed in controls.items() if not passed))
    digest = hashlib.sha256(
        json.dumps(
            {"documents": documents, "controls": controls},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ArchitectureEvidence(
        state="VERIFIED" if not blockers else "BLOCKED",
        controls=controls,
        blockers=blockers,
        evidence_digest=digest,
    )


def load_evidence_bundle(root: str | Path) -> ArchitectureEvidence:
    root = Path(root)
    filenames = {
        "architecture": "junca_social_ecosystem_chain_global_major_architecture_v1.json",
        "capabilities": "junca_social_ecosystem_chain_capability_registry_v1.json",
        "selection_matrix": "junca_social_ecosystem_chain_selection_matrix_v1.json",
        "roadmap": "junca_social_ecosystem_chain_roadmap_gates_v1.json",
        "benchmark_plan": "junca_social_ecosystem_chain_benchmark_plan_v1.json",
        "security_plan": "junca_social_ecosystem_chain_security_plan_v1.json",
    }
    loaded: dict[str, Mapping[str, Any]] = {}
    for name, filename in filenames.items():
        try:
            value = json.loads((root / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GlobalArchitectureError(f"unable to load {filename}") from exc
        if not isinstance(value, Mapping):
            raise GlobalArchitectureError(f"{filename} must contain an object")
        loaded[name] = value
    return evaluate_global_architecture(**loaded)


def evaluate_capacity_report(
    plan: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate measured capacity evidence without inventing target values."""
    _validate_common(plan, "benchmark_plan")
    metrics = _map_by_id(plan.get("metrics"), "benchmark_plan.metrics")
    observations = _map_by_id(report.get("metrics"), "capacity_report.metrics")
    results: dict[str, bool] = {}
    for metric in REQUIRED_METRICS:
        spec = metrics.get(metric, {})
        observation = observations.get(metric, {})
        results[metric] = (
            spec.get("target") is not None
            and observation.get("verified_result") is not None
            and observation.get("status") == "VERIFIED"
            and _primary_evidence(observation.get("evidence"))
        )
    passed = all(results.values())
    canonical = {"plan": plan, "report": report, "results": results}
    return {
        "schema_version": "junca-capacity-report/v1",
        "state": "VERIFIED" if passed else "BLOCKED",
        "metrics": results,
        "evidence_digest": hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        **BOUNDARIES,
    }


def _validate_common(document: Mapping[str, Any], name: str) -> None:
    _exact(document, "official_name", OFFICIAL_NAME, name)
    _exact(document, "governance", GOVERNANCE, name)
    _exact(document, "notice", NOTICE, name)
    for field, expected in BOUNDARIES.items():
        if document.get(field) is not expected:
            raise GlobalArchitectureError(f"{name}.{field} must be false")


def _architecture_axes(document: Mapping[str, Any]) -> bool:
    axes = _map_by_id(document.get("axes"), "architecture.axes")
    return set(axes) == REQUIRED_AXES and all(
        axis.get("status") in {"IMPLEMENTED", "PLANNED", "UNVERIFIED"}
        and _texts(axis.get("requirements"), f"axis.{name}.requirements")
        for name, axis in axes.items()
    )


def _one_core(document: Mapping[str, Any]) -> bool:
    items = _map_by_id(document.get("one_core_contract"), "one_core_contract")
    return set(items) == REQUIRED_ONE_CORE and all(
        _texts(item.get("chain_functions"), f"one_core.{name}.chain_functions")
        and _texts(item.get("evidence_outputs"), f"one_core.{name}.evidence_outputs")
        for name, item in items.items()
    )


def _trust_stack(document: Mapping[str, Any]) -> bool:
    layers = _map_by_id(document.get("trust_stack"), "trust_stack")
    return set(layers) == REQUIRED_TRUST and all(
        all(layer.get(field) for field in ("requirement", "control", "evidence", "reporting"))
        for layer in layers.values()
    )


def _protocol_kernel(document: Mapping[str, Any]) -> bool:
    kernel = _mapping(document.get("protocol_kernel"), "protocol_kernel")
    return all(
        kernel.get(field) is True
        for field in (
            "deterministic_genesis",
            "versioned_network_config",
            "validator_quorum_finality",
            "upgrade_compatibility",
            "state_migration",
            "rollback_boundary",
        )
    )


def _execution(document: Mapping[str, Any]) -> bool:
    execution = _mapping(document.get("execution"), "execution")
    profiles = _map_by_id(execution.get("profiles"), "execution.profiles")
    return (
        profiles.get("evm", {}).get("conformance_status") == "UNVERIFIED"
        and profiles.get("evm", {}).get("test_suite_required") is True
        and profiles.get("wasm", {}).get("status") == "PLANNED"
        and profiles.get("custom", {}).get("status") == "PLANNED"
        and execution.get("plugin_interface_version") == "v1"
    )


def _developer_experience(document: Mapping[str, Any]) -> bool:
    dx = _mapping(document.get("developer_experience"), "developer_experience")
    return all(
        dx.get(field) is True
        for field in (
            "versioned_rpc_schema",
            "sdk_api_compatibility_contract",
            "local_dev_profile",
            "contract_verification",
            "reproducible_build",
            "migration_tooling",
        )
    )


def _enterprise_adoption(document: Mapping[str, Any]) -> bool:
    enterprise = _mapping(document.get("enterprise_adoption"), "enterprise_adoption")
    return (
        all(
            enterprise.get(field) is True
            for field in (
                "permission_role_separation",
                "tenant_project_isolation",
                "regulated_asset_pattern",
                "credential_pattern",
            )
        )
        and all(
            enterprise.get(field) == "DESIGN_BOUNDARY"
            for field in (
                "account_abstraction",
                "sponsored_fee",
                "policy_controlled_transaction",
            )
        )
    )


def _scalability(document: Mapping[str, Any]) -> bool:
    metrics = _map_by_id(document.get("scalability_metrics"), "scalability_metrics")
    return set(metrics) == REQUIRED_METRICS and all(
        metric.get("target") is None
        and metric.get("verified_result") is None
        and metric.get("status") == "UNVERIFIED"
        and bool(metric.get("measurement"))
        for metric in metrics.values()
    )


def _security_axis(document: Mapping[str, Any]) -> bool:
    security = _mapping(document.get("security"), "security")
    return all(
        security.get(field) is True
        for field in (
            "threat_model",
            "sbom",
            "dependency_policy",
            "upgrade_safety",
            "key_rotation",
            "incident_pause",
            "recovery",
            "formal_verification_readiness",
            "security_review_gate",
            "bug_bounty_gate",
        )
    )


def _interoperability(document: Mapping[str, Any]) -> bool:
    registry = _map_by_id(document.get("interoperability"), "interoperability")
    return REQUIRED_BRIDGE_ROUTES.issubset(registry) and all(
        route.get("status") == "PAUSED"
        and route.get("assets_moved") is False
        and route.get("mainnet_connection") is False
        and all(
            route.get(gate) is True
            for gate in (
                "finality_gate",
                "replay_gate",
                "limit_gate",
                "custody_gate",
                "security_review_gate",
            )
        )
        for route in registry.values()
    )


def _ai_native(document: Mapping[str, Any]) -> bool:
    operations = _mapping(document.get("ai_native_operations"), "ai_native_operations")
    routes = _map_by_id(operations.get("routes"), "ai_native_operations.routes")
    return (
        set(routes) == REQUIRED_AI_ROUTES
        and operations.get("machine_readable_state") is True
        and operations.get("policy_evaluation") is True
        and operations.get("audit_evidence") is True
        and operations.get("human_approval_boundary") is True
        and operations.get("personal_control_representation") is False
    )


def _global_operations(document: Mapping[str, Any]) -> bool:
    operations = _mapping(document.get("global_operations"), "global_operations")
    return all(
        operations.get(field) is True
        for field in (
            "multi_region_design",
            "failure_domain_separation",
            "observability",
            "slo_sli_schema",
            "backup_snapshot",
            "disaster_recovery",
            "data_residency_mapping",
            "compliance_mapping",
        )
    )


def _capability_registry(document: Mapping[str, Any]) -> bool:
    capabilities = _map_by_id(document.get("capabilities"), "capabilities")
    if not REQUIRED_AXES.issubset(capabilities):
        return False
    return all(
        item.get("status") in {"IMPLEMENTED", "PLANNED", "UNVERIFIED", "BLOCKED"}
        and _texts(item.get("controls"), f"capabilities.{name}.controls")
        and _texts(item.get("evidence_requirements"), f"capabilities.{name}.evidence")
        and item.get("claim_allowed") is (item.get("status") in {"IMPLEMENTED", "VERIFIED"})
        for name, item in capabilities.items()
    )


def _selection_matrix(document: Mapping[str, Any]) -> bool:
    dimensions = set(_texts(document.get("dimensions"), "selection_matrix.dimensions"))
    chains = _map_by_id(document.get("chains"), "selection_matrix.chains")
    if dimensions != REQUIRED_DIMENSIONS or set(chains) != REQUIRED_COMPETITORS:
        return False
    for chain_name, chain in chains.items():
        cells = _map_by_id(chain.get("dimensions"), f"chains.{chain_name}.dimensions")
        if set(cells) != REQUIRED_DIMENSIONS:
            return False
        for cell in cells.values():
            if cell.get("status") == "VERIFIED":
                if cell.get("value") is None or not _primary_evidence(cell.get("evidence")):
                    return False
            elif cell.get("status") != "UNVERIFIED" or cell.get("value") is not None:
                return False
    return True


def _roadmap(document: Mapping[str, Any]) -> bool:
    stages = document.get("stages")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise GlobalArchitectureError("roadmap.stages must be a list")
    ids = tuple(item.get("id") for item in stages if isinstance(item, Mapping))
    if ids != REQUIRED_ROADMAP:
        return False
    prior_complete = True
    for stage in stages:
        criteria = _texts(stage.get("exit_criteria"), f"roadmap.{stage.get('id')}")
        if not criteria:
            return False
        if stage.get("status") == "COMPLETE" and not prior_complete:
            return False
        prior_complete = prior_complete and stage.get("status") == "COMPLETE"
    return stages[0].get("status") == "BLOCKED" and all(
        stage.get("status") == "PENDING" for stage in stages[1:]
    )


def _benchmark_plan(document: Mapping[str, Any]) -> bool:
    suites = _map_by_id(document.get("suites"), "benchmark_plan.suites")
    metrics = _map_by_id(document.get("metrics"), "benchmark_plan.metrics")
    return (
        set(suites) == REQUIRED_BENCHMARKS
        and set(metrics) == REQUIRED_METRICS
        and all(
            suite.get("status") == "SCAFFOLDED"
            and bool(suite.get("procedure"))
            and bool(suite.get("evidence_schema"))
            for suite in suites.values()
        )
        and all(
            metric.get("target") is None
            and metric.get("verified_result") is None
            and metric.get("status") == "UNVERIFIED"
            for metric in metrics.values()
        )
    )


def _security_plan(document: Mapping[str, Any]) -> bool:
    gates = _map_by_id(document.get("gates"), "security_plan.gates")
    required = {
        "threat-model",
        "supply-chain-sbom",
        "dependency-policy",
        "upgrade-safety",
        "key-rotation",
        "incident-pause",
        "recovery",
        "formal-verification-readiness",
        "independent-security-review",
        "bug-bounty",
    }
    return set(gates) == required and all(
        gate.get("status") in {"IMPLEMENTED", "PENDING", "UNVERIFIED"}
        and _texts(gate.get("evidence_requirements"), f"security.{name}")
        for name, gate in gates.items()
    )


def _primary_evidence(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("source_type") == "official-primary"
        and isinstance(value.get("url"), str)
        and value.get("url", "").startswith("https://")
        and bool(value.get("retrieved_at"))
        and bool(value.get("content_digest"))
    )


def _map_by_id(value: Any, field: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GlobalArchitectureError(f"{field} must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise GlobalArchitectureError(f"{field} items must be objects")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise GlobalArchitectureError(f"{field} requires unique non-empty ids")
        result[identifier] = item
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GlobalArchitectureError(f"{field} must be an object")
    return value


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise GlobalArchitectureError(f"{field} must contain non-empty text")
    return tuple(item.strip() for item in value)


def _exact(document: Mapping[str, Any], field: str, expected: str, name: str) -> None:
    if document.get(field) != expected:
        raise GlobalArchitectureError(f"{name}.{field} must equal {expected!r}")


def _reject_prohibited_claims(value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False).lower()
    for claim in PROHIBITED_CLAIMS:
        if claim.lower() in text:
            raise GlobalArchitectureError(f"unsupported supremacy claim is forbidden: {claim}")


def _reject_secret_material(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(marker in normalized for marker in PROHIBITED_SECRET_FIELDS):
                raise GlobalArchitectureError(f"secret material field is forbidden at {path}")
            _reject_secret_material(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _reject_secret_material(child, f"{path}[{index}]")
