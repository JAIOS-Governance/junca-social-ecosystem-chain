"""Deterministic module and application-call contracts for Mainnet candidates.

The registry is declarative: it never imports or executes untrusted code.  A
future execution client may bind an accepted descriptor to an implementation
through a separately reviewed adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "junca-execution-modules/v1"
CALL_DOMAIN = b"JUNCA_APPLICATION_CALL_V1\x00"
REGISTRY_DOMAIN = b"JUNCA_MODULE_REGISTRY_V1\x00"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


class ExecutionModuleError(ValueError):
    """Raised when an execution extension contract is not canonical."""


@dataclass(frozen=True)
class ModuleDescriptor:
    module_id: str
    version: str
    capabilities: tuple[str, ...]
    implementation_digest: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.module_id):
            raise ExecutionModuleError("module_id is invalid")
        if not _VERSION.fullmatch(self.version):
            raise ExecutionModuleError("version must use semantic versioning")
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise ExecutionModuleError("capabilities must be a non-empty tuple")
        if tuple(sorted(set(self.capabilities))) != self.capabilities:
            raise ExecutionModuleError("capabilities must be unique and sorted")
        if any(not _IDENTIFIER.fullmatch(item) for item in self.capabilities):
            raise ExecutionModuleError("capability identifier is invalid")
        _hash(self.implementation_digest, "implementation_digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "implementation_digest": self.implementation_digest,
        }


class ModuleRegistry:
    """Append-only candidate registry with capability negotiation evidence."""

    def __init__(self, descriptors: Iterable[ModuleDescriptor] = ()) -> None:
        self._modules: dict[str, ModuleDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: ModuleDescriptor) -> None:
        if not isinstance(descriptor, ModuleDescriptor):
            raise ExecutionModuleError("descriptor type is invalid")
        if descriptor.module_id in self._modules:
            raise ExecutionModuleError("module_id is already registered")
        self._modules[descriptor.module_id] = descriptor

    def resolve(self, module_id: str, capability: str) -> ModuleDescriptor:
        if not _IDENTIFIER.fullmatch(module_id):
            raise ExecutionModuleError("module_id is invalid")
        if not _IDENTIFIER.fullmatch(capability):
            raise ExecutionModuleError("capability identifier is invalid")
        try:
            descriptor = self._modules[module_id]
        except KeyError as exc:
            raise ExecutionModuleError("module is not registered") from exc
        if capability not in descriptor.capabilities:
            raise ExecutionModuleError("module does not provide capability")
        return descriptor

    @property
    def registry_hash(self) -> str:
        body = [self._modules[key].as_dict() for key in sorted(self._modules)]
        return _digest(
            REGISTRY_DOMAIN
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "module_count": len(self._modules),
            "registry_hash": self.registry_hash,
            "modules": [
                self._modules[key].as_dict() for key in sorted(self._modules)
            ],
            "dynamic_code_loading": False,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


@dataclass(frozen=True)
class ApplicationCall:
    chain_id: int
    protocol_version: str
    module_id: str
    capability: str
    action: str
    caller: str
    nonce: int
    gas_limit: int
    payload_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise ExecutionModuleError("chain_id must be a positive integer")
        if not _VERSION.fullmatch(self.protocol_version):
            raise ExecutionModuleError("protocol_version must use semantic versioning")
        for field in ("module_id", "capability", "action"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise ExecutionModuleError(f"{field} is invalid")
        if not _ADDRESS.fullmatch(self.caller.lower()):
            raise ExecutionModuleError("caller must be a 20-byte address")
        for field in ("nonce", "gas_limit"):
            value = getattr(self, field)
            minimum = 0 if field == "nonce" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ExecutionModuleError(f"{field} is invalid")
        _hash(self.payload_hash, "payload_hash")

    @property
    def call_hash(self) -> str:
        return _digest(
            CALL_DOMAIN
            + json.dumps(
                self.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "protocol_version": self.protocol_version,
            "module_id": self.module_id,
            "capability": self.capability,
            "action": self.action,
            "caller": self.caller.lower(),
            "nonce": self.nonce,
            "gas_limit": self.gas_limit,
            "payload_hash": self.payload_hash.lower(),
        }


def validate_application_call(
    call: ApplicationCall,
    *,
    registry: ModuleRegistry,
) -> ModuleDescriptor:
    if not isinstance(call, ApplicationCall) or not isinstance(registry, ModuleRegistry):
        raise ExecutionModuleError("call and registry are required")
    return registry.resolve(call.module_id, call.capability)


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise ExecutionModuleError(f"{field} must be a 32-byte hash")
    return value.lower()


def _digest(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()
