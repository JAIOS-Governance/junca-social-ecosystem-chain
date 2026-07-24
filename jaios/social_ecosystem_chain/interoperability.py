"""Fail-closed testnet interoperability controls for JUNCA, BSC and TRON."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

REQUIRED_GOVERNANCE = "JAIOS Institutional Governance"
REQUIRED_NOTICE = "Public Testnet / No Monetary Value"
SOURCE_NETWORK = "junca-public-testnet"
SOURCE_CHAIN_ID = 20260723

NETWORKS: dict[str, dict[str, Any]] = {
    "bsc-testnet": {
        "family": "evm",
        "chain_id": 97,
        "rpc_hosts": {"data-seed-prebsc-1-s1.bnbchain.org:8545"},
        "fungible_standard": "BEP-20",
        "nft_standard": "ERC-721 (BSC-compatible)",
    },
    "tron-shasta": {
        "family": "tron",
        "network_id": "tron-shasta",
        "rpc_hosts": {"api.shasta.trongrid.io"},
        "fungible_standard": "TRC-20",
        "nft_standard": "TRC-721",
    },
}


class InteroperabilityError(ValueError):
    """Raised when an interoperability route violates a safety invariant."""


@dataclass(frozen=True)
class InteroperabilityManifest:
    state: str
    digest: str
    route: Mapping[str, Any]
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "state": self.state,
            "digest": self.digest,
            "route": dict(self.route),
            "blockers": list(self.blockers),
        }


def _is_https_allowlisted(url: str, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname is not None and (
        parsed.netloc in hosts or parsed.hostname in hosts
    ) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment


def _valid_evm_address(value: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", value)) and int(value[2:], 16) != 0


def _base58_decode(value: str) -> bytes | None:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    try:
        for character in value:
            number = number * 58 + alphabet.index(character)
    except ValueError:
        return None
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + body


def _valid_tron_address(value: str) -> bool:
    if re.fullmatch(r"41[0-9a-fA-F]{40}", value):
        return int(value[2:], 16) != 0
    if len(value) != 34 or not value.startswith("T"):
        return False
    decoded = _base58_decode(value)
    if decoded is None or len(decoded) != 25 or decoded[0] != 0x41:
        return False
    checksum = hashlib.sha256(hashlib.sha256(decoded[:21]).digest()).digest()[:4]
    return decoded[21:] == checksum


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InteroperabilityError(message)


def build_interoperability_manifest(specification: Mapping[str, Any]) -> InteroperabilityManifest:
    """Validate a route and return deterministic evidence without moving assets."""

    destination = str(specification.get("destination_network", ""))
    _require(destination in NETWORKS, "destination_network must be bsc-testnet or tron-shasta")
    network = NETWORKS[destination]
    _require(specification.get("source_network") == SOURCE_NETWORK, "invalid source_network")
    _require(specification.get("source_chain_id") == SOURCE_CHAIN_ID, "invalid source_chain_id")
    _require(specification.get("governance") == REQUIRED_GOVERNANCE, "invalid governance display")
    _require(specification.get("notice") == REQUIRED_NOTICE, "testnet notice is required")
    _require(specification.get("bridge_mode") == "lock-mint-burn-release", "unsupported bridge_mode")
    _require(_is_https_allowlisted(str(specification.get("rpc_url", "")), network["rpc_hosts"]), "RPC URL is not allowlisted")

    asset_type = str(specification.get("asset_type", ""))
    _require(asset_type in {"fungible", "nft"}, "asset_type must be fungible or nft")
    expected_source = "ERC-20" if asset_type == "fungible" else "ERC-721"
    expected_destination = network["fungible_standard"] if asset_type == "fungible" else network["nft_standard"]
    _require(specification.get("source_standard") == expected_source, "invalid source token standard")
    _require(specification.get("destination_standard") == expected_destination, "invalid destination token standard")

    source_contract = str(specification.get("source_contract", ""))
    destination_contract = str(specification.get("destination_contract", ""))
    _require(_valid_evm_address(source_contract), "invalid JUNCA contract address")
    destination_valid = _valid_evm_address(destination_contract) if network["family"] == "evm" else _valid_tron_address(destination_contract)
    _require(destination_valid, "invalid destination contract address")

    relayers = specification.get("relayers")
    _require(isinstance(relayers, list) and len(relayers) >= 3, "at least three relayers are required")
    relayer_ids = [str(item.get("id", "")) for item in relayers if isinstance(item, Mapping)]
    _require(len(relayer_ids) == len(relayers) and all(relayer_ids), "each relayer requires an id")
    _require(len(set(relayer_ids)) == len(relayer_ids), "relayer ids must be unique")
    threshold = specification.get("relayer_threshold")
    _require(isinstance(threshold, int) and 2 <= threshold <= len(relayers), "invalid relayer threshold")

    controls = specification.get("controls")
    _require(isinstance(controls, Mapping), "controls are required")
    _require(controls.get("paused") is True, "new routes must start paused")
    _require(controls.get("replay_protection") is True, "replay protection is required")
    _require(isinstance(controls.get("finality_confirmations"), int) and controls["finality_confirmations"] > 0, "finality confirmations are required")
    _require(isinstance(controls.get("per_transaction_limit"), int) and controls["per_transaction_limit"] > 0, "per-transaction limit is required")
    _require(isinstance(controls.get("daily_limit"), int) and controls["daily_limit"] >= controls["per_transaction_limit"], "daily limit is invalid")
    _require(controls.get("custody") == "multisig", "multisig custody is required")
    _require(controls.get("role_separation") is True, "role separation is required")

    attestations = specification.get("attestations")
    _require(isinstance(attestations, Mapping), "attestations are required")
    required_attestations = (
        "source_contract_deployed",
        "destination_contract_deployed",
        "independent_security_review",
        "relayer_keys_verified",
        "incident_runbook_approved",
    )
    blockers = tuple(name for name in required_attestations if attestations.get(name) is not True)
    canonical = json.dumps(specification, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return InteroperabilityManifest(
        state="TESTNET_READY" if not blockers else "BLOCKED",
        digest=digest,
        route=json.loads(canonical),
        blockers=blockers,
    )


def load_interoperability_manifest(path: str | Path) -> InteroperabilityManifest:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    _require(isinstance(value, Mapping), "specification must be a JSON object")
    return build_interoperability_manifest(value)
