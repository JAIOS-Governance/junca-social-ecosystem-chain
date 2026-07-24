"""Complete fail-closed runtime acceptance evaluator for the public testnet."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
UNSAFE_METHODS = frozenset(
    {
        "admin_addPeer",
        "admin_nodeInfo",
        "debug_traceBlockByNumber",
        "personal_listAccounts",
        "personal_unlockAccount",
        "miner_start",
        "eth_sendRawTransaction",
        "eth_sendTransaction",
    }
)


class RuntimeAcceptanceV2Error(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeAcceptanceV2:
    state: str
    gates: Mapping[str, bool]
    failed_gates: tuple[str, ...]
    evidence_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-runtime-acceptance/v2",
            "governance": GOVERNANCE,
            "notice": NOTICE,
            "state": self.state,
            "gates": dict(self.gates),
            "failed_gates": list(self.failed_gates),
            "evidence_digest": self.evidence_digest,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def evaluate_runtime_acceptance_v2(
    policy: Mapping[str, Any], observations: Mapping[str, Any]
) -> RuntimeAcceptanceV2:
    _exact(policy, "governance", GOVERNANCE)
    _exact(policy, "notice", NOTICE)
    if policy.get("mainnet_changed") is not False:
        raise RuntimeAcceptanceV2Error("mainnet_changed must be false")
    if policy.get("assets_moved") is not False:
        raise RuntimeAcceptanceV2Error("assets_moved must be false")
    if policy.get("bridge_activated") is not False:
        raise RuntimeAcceptanceV2Error("bridge_activated must be false")
    chain_id = _positive_int(policy.get("chain_id"), "policy.chain_id")
    genesis_identity = _digest(policy.get("genesis_identity"), "policy.genesis_identity")
    validator_ids = _texts(policy.get("validator_ids"), "policy.validator_ids")
    if len(validator_ids) != 3 or len(set(validator_ids)) != 3:
        raise RuntimeAcceptanceV2Error("three unique validator_ids are required")

    head = _samples(observations.get("head_samples"), "head_samples")
    finalized = _samples(observations.get("finalized_head_samples"), "finalized_head_samples")
    rpc = _mapping(observations.get("rpc"), "rpc")
    explorer = _mapping(observations.get("explorer"), "explorer")
    health = _mapping(observations.get("health"), "health")
    monitoring = _mapping(observations.get("monitoring"), "monitoring")
    public = _mapping(observations.get("public_metadata"), "public_metadata")
    rejected = set(_texts(rpc.get("rejected_methods"), "rpc.rejected_methods"))

    gates = {
        "https": observations.get("https_verified") is True,
        "tls_certificate": observations.get("tls_certificate_verified") is True,
        "dns": observations.get("dns_verified") is True,
        "chain_id": observations.get("chain_id") == chain_id,
        "genesis_identity": observations.get("genesis_identity") == genesis_identity,
        "advancing_head": head[-1] > head[0],
        "finalized_head": finalized[-1] > finalized[0] and finalized[-1] <= head[-1],
        "validator_quorum": set(_texts(observations.get("validator_ids"), "validator_ids"))
        == set(validator_ids),
        "peer_count": _nonnegative_int(observations.get("peer_count"), "peer_count") >= 2,
        "rpc_response_id": rpc.get("response_id_matches") is True,
        "json_rpc_envelope": rpc.get("jsonrpc") == "2.0"
        and rpc.get("envelope_verified") is True,
        "unsafe_rpc_rejection": UNSAFE_METHODS.issubset(rejected),
        "rpc_rate_limit": rpc.get("rate_limit_verified") is True,
        "explorer_rpc_parity": explorer.get("head") == finalized[-1]
        and explorer.get("finalized_only") is True,
        "health_endpoint": health.get("ok") is True,
        "monitoring_signal": all(
            monitoring.get(name) is True
            for name in (
                "validator_quorum",
                "rpc_head_lag",
                "disk_capacity",
                "external_health",
            )
        ),
        "restart_recovery": observations.get("restart_recovery_verified") is True,
        "rollback_readiness": observations.get("rollback_readiness_verified") is True,
        "institutional_governance": public.get("governance") == GOVERNANCE,
        "no_monetary_value_notice": public.get("notice") == NOTICE,
    }
    failed = tuple(name for name, passed in gates.items() if not passed)
    canonical = {"policy": policy, "observations": observations, "gates": gates}
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RuntimeAcceptanceV2(
        state="ACCEPTED" if not failed else "BLOCKED",
        gates=gates,
        failed_gates=failed,
        evidence_digest=digest,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeAcceptanceV2Error(f"{field} must be an object")
    return value


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise RuntimeAcceptanceV2Error(f"{field} must contain non-empty text")
    return tuple(item.strip() for item in value)


def _samples(value: Any, field: str) -> tuple[int, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) < 2
    ):
        raise RuntimeAcceptanceV2Error(f"{field} requires at least two samples")
    samples = tuple(_nonnegative_int(item, field) for item in value)
    return samples


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeAcceptanceV2Error(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeAcceptanceV2Error(f"{field} must be a non-negative integer")
    return value


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise RuntimeAcceptanceV2Error(f"{field} must be a lowercase SHA-256")
    return value


def _exact(specification: Mapping[str, Any], field: str, expected: str) -> None:
    if specification.get(field) != expected:
        raise RuntimeAcceptanceV2Error(f"{field} must equal {expected!r}")

