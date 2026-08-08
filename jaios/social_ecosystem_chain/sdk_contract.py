"""Versioned SDK and application-integration contract for Mainnet candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable


SCHEMA_VERSION = "junca-mainnet-sdk-contract/v1"
REQUEST_DOMAIN = b"JUNCA_SDK_REQUEST_V1\x00"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._/-]{0,127}$")
_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")


class SdkContractError(ValueError):
    """Raised when SDK compatibility or request identity is invalid."""


@dataclass(frozen=True)
class NodeCapabilities:
    protocol_version: str
    api_version: str
    network_profile: str
    chain_id: int
    genesis_hash: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("protocol_version", "api_version"):
            if not _VERSION.fullmatch(getattr(self, field)):
                raise SdkContractError(f"{field} must use semantic versioning")
        if not _IDENTIFIER.fullmatch(self.network_profile):
            raise SdkContractError("network_profile is invalid")
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise SdkContractError("chain_id must be positive")
        _hash(self.genesis_hash, "genesis_hash")
        if (
            not isinstance(self.capabilities, tuple)
            or tuple(sorted(set(self.capabilities))) != self.capabilities
            or any(not _IDENTIFIER.fullmatch(item) for item in self.capabilities)
        ):
            raise SdkContractError("capabilities must be unique, sorted identifiers")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": self.protocol_version,
            "api_version": self.api_version,
            "network_profile": self.network_profile,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash.lower(),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class ApplicationIntegrationContract:
    application_id: str
    required_protocol_major: int
    required_api_major: int
    required_capabilities: tuple[str, ...]
    allowed_network_profiles: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.application_id):
            raise SdkContractError("application_id is invalid")
        for field in ("required_protocol_major", "required_api_major"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SdkContractError(f"{field} must be positive")
        for field in ("required_capabilities", "allowed_network_profiles"):
            values = getattr(self, field)
            if (
                not isinstance(values, tuple)
                or not values
                or tuple(sorted(set(values))) != values
                or any(not _IDENTIFIER.fullmatch(item) for item in values)
            ):
                raise SdkContractError(f"{field} must be unique and sorted")

    def evaluate(self, node: NodeCapabilities) -> dict[str, Any]:
        if not isinstance(node, NodeCapabilities):
            raise SdkContractError("node capabilities are required")
        missing = tuple(sorted(set(self.required_capabilities) - set(node.capabilities)))
        compatible = (
            _major(node.protocol_version) == self.required_protocol_major
            and _major(node.api_version) == self.required_api_major
            and node.network_profile in self.allowed_network_profiles
            and not missing
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "application_id": self.application_id,
            "compatible": compatible,
            "missing_capabilities": list(missing),
            "node_network_profile": node.network_profile,
            "chain_id": node.chain_id,
            "genesis_hash": node.genesis_hash.lower(),
        }


@dataclass(frozen=True)
class SdkRequest:
    request_id: str
    application_id: str
    method: str
    chain_id: int
    genesis_hash: str
    api_version: str
    payload_hash: str

    def __post_init__(self) -> None:
        for field in ("request_id", "application_id", "method"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise SdkContractError(f"{field} is invalid")
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise SdkContractError("chain_id must be positive")
        if not _VERSION.fullmatch(self.api_version):
            raise SdkContractError("api_version must use semantic versioning")
        _hash(self.genesis_hash, "genesis_hash")
        _hash(self.payload_hash, "payload_hash")

    @property
    def request_hash(self) -> str:
        body = {
            "schema_version": SCHEMA_VERSION,
            "request_id": self.request_id,
            "application_id": self.application_id,
            "method": self.method,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash.lower(),
            "api_version": self.api_version,
            "payload_hash": self.payload_hash.lower(),
        }
        return "0x" + hashlib.sha256(
            REQUEST_DOMAIN
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def build_capabilities(
    *,
    protocol_version: str,
    api_version: str,
    network_profile: str,
    chain_id: int,
    genesis_hash: str,
    capabilities: Iterable[str],
) -> NodeCapabilities:
    return NodeCapabilities(
        protocol_version=protocol_version,
        api_version=api_version,
        network_profile=network_profile,
        chain_id=chain_id,
        genesis_hash=genesis_hash,
        capabilities=tuple(sorted(set(capabilities))),
    )


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise SdkContractError(f"{field} must be a 32-byte hash")
    return value.lower()
