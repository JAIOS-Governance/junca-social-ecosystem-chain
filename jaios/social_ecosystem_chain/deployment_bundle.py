"""Deterministic public-testnet genesis and rollback bundle builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "junca-public-testnet-launch-manifest/v1"
OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE_ENTITY = "JAIOS Institutional Governance"
PUBLIC_LABEL = "Public Testnet / No Monetary Value"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DeploymentBundleError(RuntimeError):
    """Raised when launch inputs are incomplete, unsafe, or non-deterministic."""


@dataclass(frozen=True)
class ValidatorIdentity:
    name: str
    address: str


@dataclass(frozen=True)
class LaunchManifest:
    network_name: str
    chain_id: int
    validators: tuple[ValidatorIdentity, ...]
    foundation_address: str
    prefund: tuple[tuple[str, str], ...]
    gas_limit: str
    difficulty: str

    @property
    def missing_bindings(self) -> tuple[str, ...]:
        missing = [item.name for item in self.validators if item.address == "pending"]
        if self.foundation_address == "pending":
            missing.append("foundation-address")
        return tuple(missing)

    @property
    def state(self) -> str:
        return "bound" if not self.missing_bindings else "pending-bindings"

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "network_name": self.network_name,
            "chain_id": self.chain_id,
            "governance_entity": GOVERNANCE_ENTITY,
            "public_label": PUBLIC_LABEL,
            "validator_count": len(self.validators),
            "validator_names": [item.name for item in self.validators],
            "prefund_count": len(self.prefund),
            "state": self.state,
            "missing_bindings": list(self.missing_bindings),
            "secret_material_in_manifest": False,
        }


def load_launch_manifest(path: str | Path) -> LaunchManifest:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentBundleError("unable to load launch manifest") from exc
    if not isinstance(raw, Mapping):
        raise DeploymentBundleError("launch manifest must be an object")
    rendered = json.dumps(raw, ensure_ascii=False).lower()
    for marker in ("private_key", "mnemonic", "seed_phrase", "password", "secret_value"):
        if marker in rendered:
            raise DeploymentBundleError(f"secret material marker prohibited: {marker}")

    _require(raw, "schema_version", SCHEMA_VERSION)
    _require(raw, "official_name", OFFICIAL_NAME)
    _require(raw, "governance_entity", GOVERNANCE_ENTITY)
    _require(raw, "public_label", PUBLIC_LABEL)
    network_name = _text(raw.get("network_name"), "network_name")
    chain_id = _positive_integer(raw.get("chain_id"), "chain_id")

    consensus = _mapping(raw.get("consensus"), "consensus")
    _require(consensus, "engine", "posv")
    _require(consensus, "period_seconds", 2)
    _require(consensus, "epoch_blocks", 900)

    validators_raw = raw.get("validators")
    if not isinstance(validators_raw, list) or len(validators_raw) != 3:
        raise DeploymentBundleError("exactly three validator identities are required")
    validators: list[ValidatorIdentity] = []
    seen_addresses: set[str] = set()
    for index, item in enumerate(validators_raw, start=1):
        record = _mapping(item, f"validators[{index}]")
        name = f"validator-{index}"
        _require(record, "name", name)
        address = _address_or_pending(record.get("address"), f"{name}.address")
        if address != "pending":
            if address in seen_addresses:
                raise DeploymentBundleError("validator addresses must be unique")
            seen_addresses.add(address)
        validators.append(ValidatorIdentity(name, address))

    foundation = _address_or_pending(raw.get("foundation_address"), "foundation_address")
    if foundation != "pending" and foundation in seen_addresses:
        raise DeploymentBundleError("foundation address must be separate from validators")

    prefund_raw = raw.get("prefund")
    if not isinstance(prefund_raw, list):
        raise DeploymentBundleError("prefund must be a list")
    prefund: list[tuple[str, str]] = []
    prefund_addresses: set[str] = set()
    for index, item in enumerate(prefund_raw):
        record = _mapping(item, f"prefund[{index}]")
        address = _address(record.get("address"), f"prefund[{index}].address")
        balance = _quantity(record.get("balance"), f"prefund[{index}].balance")
        if address in prefund_addresses:
            raise DeploymentBundleError("prefund addresses must be unique")
        prefund_addresses.add(address)
        prefund.append((address, balance))

    gas_limit = _quantity(raw.get("gas_limit"), "gas_limit")
    difficulty = _quantity(raw.get("difficulty"), "difficulty")
    release = _mapping(raw.get("release"), "release")
    for field in ("mainnet", "monetary_value", "legacy_state_import", "legacy_key_reuse"):
        _require(release, field, False)

    return LaunchManifest(
        network_name=network_name,
        chain_id=chain_id,
        validators=tuple(validators),
        foundation_address=foundation,
        prefund=tuple(prefund),
        gas_limit=gas_limit,
        difficulty=difficulty,
    )


def render_genesis(manifest: LaunchManifest) -> dict[str, Any]:
    if manifest.missing_bindings:
        raise DeploymentBundleError(
            "genesis blocked by pending bindings: " + ", ".join(manifest.missing_bindings)
        )
    signers = "".join(item.address[2:] for item in manifest.validators)
    extra_data = "0x" + ("00" * 32) + signers + ("00" * 65)
    alloc = {address[2:]: {"balance": balance} for address, balance in manifest.prefund}
    return {
        "config": {
            "chainId": manifest.chain_id,
            "homesteadBlock": 0,
            "eip150Block": 0,
            "eip155Block": 0,
            "eip158Block": 0,
            "byzantiumBlock": 0,
            "constantinopleBlock": 0,
            "petersburgBlock": 0,
            "istanbulBlock": 0,
            "posv": {
                "period": 2,
                "epoch": 900,
                "foundation": manifest.foundation_address,
                "juncaswapAdmin": manifest.foundation_address,
            },
        },
        "nonce": "0x0",
        "timestamp": "0x0",
        "extraData": extra_data,
        "gasLimit": manifest.gas_limit,
        "difficulty": manifest.difficulty,
        "mixHash": "0x" + ("00" * 32),
        "coinbase": "0x" + ("00" * 20),
        "alloc": alloc,
        "number": "0x0",
        "gasUsed": "0x0",
        "parentHash": "0x" + ("00" * 32),
    }


def serialize_genesis(genesis: Mapping[str, Any]) -> bytes:
    return (json.dumps(genesis, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def build_rollback_manifest(
    genesis: Mapping[str, Any],
    *,
    binary_digest: str,
    source_commit: str,
) -> dict[str, Any]:
    if not SHA256.fullmatch(binary_digest):
        raise DeploymentBundleError("binary_digest must be a SHA-256 digest")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise DeploymentBundleError("source_commit must be a lowercase Git SHA")
    genesis_digest = hashlib.sha256(serialize_genesis(genesis)).hexdigest()
    identity = {
        "source_commit": source_commit,
        "binary_digest": binary_digest,
        "genesis_digest": genesis_digest,
    }
    identity_digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "junca-public-testnet-rollback/v1",
        "official_name": OFFICIAL_NAME,
        "governance_entity": GOVERNANCE_ENTITY,
        "release_target": "public-testnet",
        **identity,
        "identity_digest": identity_digest,
        "restore_test_status": "pending-runtime-rehearsal",
        "secret_material_in_bundle": False,
    }


def write_atomic(path: str | Path, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(target)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeploymentBundleError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise DeploymentBundleError(f"{field} must contain 1-200 characters")
    return value.strip()


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DeploymentBundleError(f"{field} must be a positive integer")
    return value


def _address_or_pending(value: Any, field: str) -> str:
    if value == "pending":
        return "pending"
    return _address(value, field)


def _address(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise DeploymentBundleError(f"{field} must be a 20-byte address")
    if value.lower() == "0x" + ("0" * 40):
        raise DeploymentBundleError(f"{field} must not be the zero address")
    return value.lower()


def _quantity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-f]+", value):
        raise DeploymentBundleError(f"{field} must be a lowercase hex quantity")
    if int(value, 16) <= 0:
        raise DeploymentBundleError(f"{field} must be greater than zero")
    return value


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise DeploymentBundleError(f"{field} must be {expected!r}")
