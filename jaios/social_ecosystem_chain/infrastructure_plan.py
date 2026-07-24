"""Deterministic, provider-neutral public testnet infrastructure planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
UNSAFE_RPC_METHODS = (
    "admin_*", "debug_*", "personal_*", "miner_*",
    "eth_sendRawTransaction", "eth_sendTransaction",
)


class InfrastructurePlanError(ValueError):
    pass


@dataclass(frozen=True)
class InfrastructurePlan:
    digest: str
    plan: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"plan_digest": self.digest, **self.plan}


def build_infrastructure_plan(specification: Mapping[str, Any]) -> InfrastructurePlan:
    _require_exact(specification, "governance", GOVERNANCE)
    _require_exact(specification, "notice", NOTICE)
    _require_exact(specification, "environment", "public-testnet")
    release_commit = _text(specification, "release_commit")
    failure_domains = specification.get("failure_domains")
    if (
        not isinstance(failure_domains, list)
        or len(failure_domains) != 3
        or not all(isinstance(domain, str) and domain.strip() for domain in failure_domains)
        or len(set(failure_domains)) != 3
    ):
        raise InfrastructurePlanError("three distinct failure_domains are required")
    nodes = [
        {
            "id": f"validator-{index + 1:02d}",
            "failure_domain": domain,
            "public_rpc": False,
            "signer": "external-secret-resource",
            "p2p_port": 30303,
            "rpc_bind": "127.0.0.1:8545",
        }
        for index, domain in enumerate(failure_domains)
    ]
    plan = {
        "schema_version": 1,
        "environment": "public-testnet",
        "release_commit": release_commit,
        "governance": GOVERNANCE,
        "notice": NOTICE,
        "topology": {
            "validators": nodes,
            "public_rpc_gateway": {
                "replicas": 2,
                "ingress": ["443/tcp"],
                "upstream": "validator-readonly-pool",
                "rate_limit_required": True,
                "tls_required": True,
                "unsafe_rpc_methods_denied": list(UNSAFE_RPC_METHODS),
            },
            "explorer": {
                "replicas": 1,
                "ingress": ["443/tcp"],
                "source": "finalized-readonly-index",
            },
            "monitoring": {
                "external_health_probe": True,
                "validator_quorum_alert": True,
                "rpc_head_lag_alert": True,
                "disk_capacity_alert": True,
            },
        },
        "rollout": [
            "verify-artifact-digests", "bind-external-signer-resources",
            "deploy-validator-01", "deploy-validator-02", "deploy-validator-03",
            "verify-validator-quorum", "deploy-readonly-rpc-gateway",
            "verify-rpc-acceptance", "deploy-explorer",
            "verify-explorer-head-parity", "enable-monitoring",
            "publish-public-testnet-endpoints",
        ],
        "rollback": [
            "withdraw-public-endpoints", "pause-bridge-routes",
            "preserve-logs-and-finalized-checkpoint",
            "restore-last-verified-binary-and-genesis",
            "verify-validator-quorum", "restore-readonly-endpoints",
        ],
        "release_boundary": {
            "mainnet_changed": False,
            "bridge_activated": False,
            "assets_moved": False,
            "automatic_deployment": False,
        },
    }
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return InfrastructurePlan(digest, plan)


def _require_exact(specification: Mapping[str, Any], key: str, expected: str) -> None:
    if specification.get(key) != expected:
        raise InfrastructurePlanError(f"{key} must equal {expected!r}")


def _text(specification: Mapping[str, Any], key: str) -> str:
    value = specification.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InfrastructurePlanError(f"{key} must be non-empty text")
    return value.strip()
