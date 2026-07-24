"""Deterministic fail-closed deployment manifest for bridge testnet assets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class BridgeDeploymentError(ValueError):
    pass


@dataclass(frozen=True)
class BridgeDeploymentManifest:
    state: str
    blockers: tuple[str, ...]
    digest: str
    specification: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "state": self.state,
            "blockers": list(self.blockers),
            "digest": self.digest,
            "specification": dict(self.specification),
        }


def build_bridge_deployment_manifest(specification: Mapping[str, Any]) -> BridgeDeploymentManifest:
    required_text = {
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "environment": "public-testnet",
    }
    for field, expected in required_text.items():
        if specification.get(field) != expected:
            raise BridgeDeploymentError(f"invalid {field}")
    network = specification.get("network")
    if network not in {"bsc-testnet", "tron-shasta"}:
        raise BridgeDeploymentError("unsupported deployment network")
    if specification.get("paused_on_deploy") is not True:
        raise BridgeDeploymentError("deployment must start paused")
    contracts = specification.get("contracts")
    if not isinstance(contracts, Mapping):
        raise BridgeDeploymentError("contract inventory is required")
    required_contracts = {"bridge", "asset_adapter", "mintable_erc20", "mintable_erc721"}
    if set(contracts) != required_contracts:
        raise BridgeDeploymentError("contract inventory mismatch")
    for name, item in contracts.items():
        if not isinstance(item, Mapping):
            raise BridgeDeploymentError(f"invalid {name} contract")
        source_hash = str(item.get("source_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise BridgeDeploymentError(f"invalid {name} source digest")
        address = str(item.get("address", ""))
        if address and not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            raise BridgeDeploymentError(f"invalid {name} address")
    attestations = specification.get("attestations")
    if not isinstance(attestations, Mapping):
        raise BridgeDeploymentError("attestations are required")
    required_attestations = (
        "bytecode_reproduced",
        "multisig_bound",
        "guardian_bound",
        "relayer_keys_bound",
        "independent_security_review",
        "explorer_source_verified",
        "runtime_acceptance",
    )
    blockers = tuple(name for name in required_attestations if attestations.get(name) is not True)
    if any(not contracts[name].get("address") for name in required_contracts):
        blockers += ("contract_addresses_bound",)
    canonical = json.dumps(specification, sort_keys=True, separators=(",", ":"))
    return BridgeDeploymentManifest(
        state="TESTNET_DEPLOYMENT_READY" if not blockers else "BLOCKED",
        blockers=blockers,
        digest=hashlib.sha256(canonical.encode()).hexdigest(),
        specification=json.loads(canonical),
    )


def load_bridge_deployment_manifest(path: str | Path) -> BridgeDeploymentManifest:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise BridgeDeploymentError("specification must be an object")
    return build_bridge_deployment_manifest(value)
