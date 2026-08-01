"""Public-preview testnet launch contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


class PublicTestnetError(RuntimeError):
    """Raised when the public-testnet launch contract is unsafe."""


REQUIRED_SERVICES = ("rpc", "explorer", "faucet", "status")


@dataclass(frozen=True)
class PublicTestnetPlan:
    network_name: str
    release_stage: str
    audience: str
    issuance_management: str
    validator_count: int
    validator_quorum: int
    services: tuple[str, ...]
    monetary_value: bool
    mainnet: bool

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-public-testnet-plan/v1",
            "network_name": self.network_name,
            "release_stage": self.release_stage,
            "audience": self.audience,
            "issuance_management": self.issuance_management,
            "validator_count": self.validator_count,
            "validator_quorum": self.validator_quorum,
            "services": list(self.services),
            "monetary_value": self.monetary_value,
            "mainnet": self.mainnet,
            "configuration_status": "valid-public-preview",
            "deployment_status": "pending-runtime-evidence",
        }


def load_public_testnet_plan(path: str | Path) -> PublicTestnetPlan:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicTestnetError("unable to load public-testnet plan") from exc
    if not isinstance(raw, Mapping):
        raise PublicTestnetError("plan must be an object")
    _require(raw, "schema_version", "junca-public-testnet-plan/v1")
    _require(raw, "release_stage", "public-preview")
    _require(raw, "audience", "public-technical-evaluation")
    _require(raw, "issuance_management", "JAIOS Institutional Governance")
    _require(raw, "public_label", "Public Testnet / No Monetary Value")
    if raw.get("mainnet") is not False or raw.get("monetary_value") is not False:
        raise PublicTestnetError(
            "preview must remain a public-testnet protocol-validation environment "
            "and must not be represented as mainnet"
        )
    if raw.get("legacy_key_reuse") is not False:
        raise PublicTestnetError("legacy key reuse is prohibited")

    topology = _mapping(raw.get("topology"), "topology")
    validators = _integer(topology.get("validators"), "topology.validators")
    quorum = _integer(topology.get("validator_quorum"), "topology.validator_quorum")
    if validators < 3 or quorum < 3 or quorum > validators:
        raise PublicTestnetError("preview requires at least 3 validators and quorum 3")

    services = _mapping(raw.get("services"), "services")
    if tuple(services) != REQUIRED_SERVICES:
        raise PublicTestnetError("services must contain rpc, explorer, faucet and status")
    for name in REQUIRED_SERVICES:
        service = _mapping(services[name], f"services.{name}")
        _require(service, "public", True)
        _require(service, "status", "pending-deployment")

    gates = _mapping(raw.get("launch_gates"), "launch_gates")
    required_gates = {
        "new_keys_attested",
        "genesis_fingerprint_verified",
        "validator_quorum_verified",
        "rpc_boundary_verified",
        "explorer_head_parity_verified",
        "faucet_rate_limit_verified",
        "status_page_verified",
        "rollback_package_verified",
        "independent_readback_verified",
    }
    if set(gates) != required_gates or any(value is not False for value in gates.values()):
        raise PublicTestnetError("all exact launch gates must start false")

    name = raw.get("network_name")
    if not isinstance(name, str) or not name.strip():
        raise PublicTestnetError("network_name is required")
    return PublicTestnetPlan(
        network_name=name.strip(),
        release_stage="public-preview",
        audience="public-technical-evaluation",
        issuance_management="JAIOS Institutional Governance",
        validator_count=validators,
        validator_quorum=quorum,
        services=REQUIRED_SERVICES,
        monetary_value=False,
        mainnet=False,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicTestnetError(f"{field} must be an object")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PublicTestnetError(f"{field} must be a positive integer")
    return value


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise PublicTestnetError(f"{field} must be {expected!r}")
