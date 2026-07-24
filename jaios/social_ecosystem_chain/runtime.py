"""Fail-closed runtime contract for the public-preview testnet."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


class PublicTestnetRuntimeError(RuntimeError):
    """Raised when runtime configuration could expose unsafe capabilities."""


@dataclass(frozen=True)
class PublicTestnetRuntime:
    chain_id: int
    issuance_management: str
    validators: tuple[str, ...]
    allowed_rpc_modules: tuple[str, ...]
    denied_rpc_modules: tuple[str, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-public-testnet-runtime-evidence/v1",
            "chain_id": self.chain_id,
            "issuance_management": self.issuance_management,
            "validator_count": len(self.validators),
            "validators": list(self.validators),
            "allowed_rpc_modules": list(self.allowed_rpc_modules),
            "denied_rpc_modules": list(self.denied_rpc_modules),
            "secret_material_in_repository": False,
            "configuration_status": "valid",
            "deployment_status": "pending-runtime-binding",
        }


def load_public_testnet_runtime(path: str | Path) -> PublicTestnetRuntime:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicTestnetRuntimeError("unable to load runtime configuration") from exc
    if not isinstance(raw, Mapping):
        raise PublicTestnetRuntimeError("runtime configuration must be an object")
    _require(raw, "schema_version", "junca-public-testnet-runtime/v1")
    _require(raw, "network", "public-preview")
    _require(raw, "issuance_management", "JAIOS Institutional Governance")

    chain_id = raw.get("chain_id")
    if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
        raise PublicTestnetRuntimeError("chain_id must be a positive integer")

    consensus = _mapping(raw.get("consensus"), "consensus")
    _require(consensus, "engine", "posv")
    _require(consensus, "period_seconds", 2)
    _require(consensus, "epoch_blocks", 900)

    validators_raw = raw.get("validators")
    if not isinstance(validators_raw, list) or len(validators_raw) != 3:
        raise PublicTestnetRuntimeError("exactly 3 validators are required")
    names: list[str] = []
    key_files: set[str] = set()
    volumes: set[str] = set()
    for index, item in enumerate(validators_raw, start=1):
        validator = _mapping(item, f"validators[{index}]")
        expected_name = f"validator-{index}"
        _require(validator, "name", expected_name)
        key_file = validator.get("key_file")
        volume = validator.get("data_volume")
        if key_file != f"/run/secrets/{expected_name}.key":
            raise PublicTestnetRuntimeError("validator keys must be read-only secret mounts")
        if not isinstance(volume, str) or not volume:
            raise PublicTestnetRuntimeError("validator data volume is required")
        names.append(expected_name)
        key_files.add(key_file)
        volumes.add(volume)
    if len(key_files) != 3 or len(volumes) != 3:
        raise PublicTestnetRuntimeError("validator custody and storage must be isolated")

    rpc = _mapping(raw.get("rpc"), "rpc")
    allowed = _string_tuple(rpc.get("allowed_modules"), "rpc.allowed_modules")
    denied = _string_tuple(rpc.get("denied_modules"), "rpc.denied_modules")
    if allowed != ("eth", "net", "web3"):
        raise PublicTestnetRuntimeError("public RPC must expose only eth, net and web3")
    unsafe = {"admin", "debug", "miner", "personal", "txpool"}
    if set(denied) != unsafe or unsafe.intersection(allowed):
        raise PublicTestnetRuntimeError("unsafe RPC modules must remain denied")
    _require(rpc, "cors_policy", "explicit-origin-only")
    _require(rpc, "rate_limit_required", True)

    custody = _mapping(raw.get("custody"), "custody")
    _require(custody, "key_generation", "deployment-environment-only")
    _require(custody, "key_mount", "read-only-secret")
    _require(custody, "legacy_key_reuse", False)
    _require(custody, "repository_secret_material", False)

    release = _mapping(raw.get("release"), "release")
    _require(release, "public_label", "Public Testnet / No Monetary Value")
    _require(release, "mainnet", False)
    _require(release, "rollback_bundle_required", True)

    return PublicTestnetRuntime(
        chain_id=chain_id,
        issuance_management="JAIOS Institutional Governance",
        validators=tuple(names),
        allowed_rpc_modules=allowed,
        denied_rpc_modules=denied,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicTestnetRuntimeError(f"{field} must be an object")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PublicTestnetRuntimeError(f"{field} must be a string list")
    return tuple(value)


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise PublicTestnetRuntimeError(f"{field} must be {expected!r}")
