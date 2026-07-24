"""Deterministic partner asset issuance controls for JUNCA Social Ecosystem Chain."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


class AssetIssuanceError(ValueError):
    """Raised when a partner asset specification violates issuance policy."""


GOVERNANCE = "JAIOS Institutional Governance"
TESTNET_NOTICE = "Public Testnet / No Monetary Value"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
ASSET_TYPES = frozenset({"fungible-token", "nft-collection"})
ALLOWED_STANDARDS = {
    "fungible-token": frozenset({"ERC-20"}),
    "nft-collection": frozenset({"ERC-721"}),
}


@dataclass(frozen=True)
class IssuanceManifest:
    state: str
    asset_id: str
    asset_type: str
    standard: str
    deployment_salt: str
    specification_digest: str
    blockers: tuple[str, ...]
    normalized: Mapping[str, Any]

    @property
    def releasable(self) -> bool:
        return self.state == "TESTNET_READY"

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-partner-asset-issuance/v1",
            "network": "JUNCA Social Ecosystem Chain Public Testnet",
            "governance": GOVERNANCE,
            "notice": TESTNET_NOTICE,
            "state": self.state,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "standard": self.standard,
            "deployment_salt": self.deployment_salt,
            "specification_digest": self.specification_digest,
            "blockers": list(self.blockers),
            "specification": dict(self.normalized),
        }


def build_issuance_manifest(specification: Mapping[str, Any]) -> IssuanceManifest:
    if not isinstance(specification, Mapping):
        raise AssetIssuanceError("specification must be an object")
    asset_id = _text(specification.get("asset_id"), "asset_id", 64)
    asset_type = _text(specification.get("asset_type"), "asset_type", 32)
    if asset_type not in ASSET_TYPES:
        raise AssetIssuanceError("unsupported asset_type")
    standard = _text(specification.get("standard"), "standard", 16)
    if standard not in ALLOWED_STANDARDS[asset_type]:
        raise AssetIssuanceError(f"{standard} is not approved for {asset_type}")
    name = _text(specification.get("name"), "name", 64)
    symbol = _text(specification.get("symbol"), "symbol", 10)
    if not SYMBOL.fullmatch(symbol):
        raise AssetIssuanceError("symbol must contain 2-10 uppercase letters or digits")
    chain_id = _positive_int(specification.get("chain_id"), "chain_id")
    if chain_id != 20260723:
        raise AssetIssuanceError("issuance plan must target Public Testnet chain ID 20260723")

    roles = _mapping(specification.get("roles"), "roles")
    normalized_roles = {
        key: _address(roles.get(key), f"roles.{key}")
        for key in ("admin", "treasury", "pauser")
    }
    if len(set(normalized_roles.values())) != 3:
        raise AssetIssuanceError("admin, treasury and pauser roles must be separated")

    controls = _mapping(specification.get("controls"), "controls")
    normalized_controls = {
        "mintable": _boolean(controls.get("mintable"), "controls.mintable"),
        "burnable": _boolean(controls.get("burnable"), "controls.burnable"),
        "pausable": _boolean(controls.get("pausable"), "controls.pausable"),
        "upgradeable": _boolean(controls.get("upgradeable"), "controls.upgradeable"),
        "multisig_required": _boolean(
            controls.get("multisig_required"), "controls.multisig_required"
        ),
    }
    if not normalized_controls["multisig_required"]:
        raise AssetIssuanceError("institutional multisig custody is mandatory")
    if normalized_controls["upgradeable"]:
        raise AssetIssuanceError("upgradeable partner contracts require a separate review path")

    asset_fields = _normalize_asset_fields(asset_type, specification)
    attestations = _mapping(specification.get("attestations"), "attestations")
    normalized_attestations = {
        key: _boolean(attestations.get(key), f"attestations.{key}")
        for key in (
            "partner_authorized",
            "legal_review_complete",
            "security_review_complete",
            "metadata_rights_confirmed",
            "testnet_only",
        )
    }
    if not normalized_attestations["testnet_only"]:
        raise AssetIssuanceError("this workflow is restricted to Public Testnet")

    normalized = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "standard": standard,
        "name": name,
        "symbol": symbol,
        "chain_id": chain_id,
        "roles": normalized_roles,
        "controls": normalized_controls,
        **asset_fields,
        "attestations": normalized_attestations,
    }
    blockers = tuple(
        name for name, passed in normalized_attestations.items() if not passed
    )
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    salt = "0x" + hashlib.sha256(
        f"JUNCA_SOCIAL_ECOSYSTEM_CHAIN:{asset_id}:{digest}".encode("utf-8")
    ).hexdigest()
    return IssuanceManifest(
        state="TESTNET_READY" if not blockers else "BLOCKED",
        asset_id=asset_id,
        asset_type=asset_type,
        standard=standard,
        deployment_salt=salt,
        specification_digest=digest,
        blockers=blockers,
        normalized=normalized,
    )


def load_issuance_manifest(path: str | Path) -> IssuanceManifest:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetIssuanceError(f"unable to load issuance specification: {path}") from exc
    return build_issuance_manifest(raw)


def _normalize_asset_fields(asset_type: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    if asset_type == "fungible-token":
        decimals = _nonnegative_int(spec.get("decimals"), "decimals")
        if decimals > 18:
            raise AssetIssuanceError("decimals must not exceed 18")
        max_supply = _positive_int(spec.get("max_supply"), "max_supply")
        initial_supply = _nonnegative_int(spec.get("initial_supply"), "initial_supply")
        if initial_supply > max_supply:
            raise AssetIssuanceError("initial_supply must not exceed max_supply")
        return {
            "decimals": decimals,
            "initial_supply": initial_supply,
            "max_supply": max_supply,
        }

    max_supply = _positive_int(spec.get("max_supply"), "max_supply")
    if max_supply > 1_000_000:
        raise AssetIssuanceError("NFT max_supply must not exceed 1,000,000")
    base_uri = _text(spec.get("base_uri"), "base_uri", 2048)
    if not base_uri.startswith(("ipfs://", "https://")):
        raise AssetIssuanceError("base_uri must use ipfs:// or https://")
    if "?" in base_uri or "#" in base_uri:
        raise AssetIssuanceError("base_uri must not contain query or fragment")
    return {"max_supply": max_supply, "base_uri": base_uri}


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssetIssuanceError(f"{field} must be an object")
    return value


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AssetIssuanceError(f"{field} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise AssetIssuanceError(f"{field} must contain 1-{maximum} characters")
    return cleaned


def _address(value: Any, field: str) -> str:
    text = _text(value, field, 42)
    if not ADDRESS.fullmatch(text) or text.lower() == "0x" + "0" * 40:
        raise AssetIssuanceError(f"{field} must be a non-zero EVM address")
    return text.lower()


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise AssetIssuanceError(f"{field} must be boolean")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AssetIssuanceError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AssetIssuanceError(f"{field} must be a non-negative integer")
    return value
