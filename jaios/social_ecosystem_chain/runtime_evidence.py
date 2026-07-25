"""Bind live validator evidence to the public-testnet acceptance gates.

This module is deliberately cloud-neutral.  It accepts redacted evidence from
the chain runtime and endpoint probes, verifies their common identity and then
builds the exact observation shape consumed by Runtime Acceptance v2.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from .runtime_acceptance_v2 import (
    GOVERNANCE,
    NOTICE,
    RuntimeAcceptanceV2,
    evaluate_runtime_acceptance_v2,
)


class LiveRuntimeEvidenceError(ValueError):
    """Raised when runtime evidence is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class LiveRuntimeEvidenceBundle:
    observations: Mapping[str, Any]
    source_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-live-runtime-evidence/v1",
            "governance": GOVERNANCE,
            "notice": NOTICE,
            "source_digest": self.source_digest,
            "observations": dict(self.observations),
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def build_live_runtime_evidence(
    *,
    policy: Mapping[str, Any],
    validator_runtime: Mapping[str, Any],
    finalized_blocks: Sequence[Mapping[str, Any]],
    operational_observations: Mapping[str, Any],
) -> LiveRuntimeEvidenceBundle:
    """Validate and combine chain-local and externally collected evidence."""
    chain_id = _positive_int(policy.get("chain_id"), "policy.chain_id")
    validator_ids = _texts(policy.get("validator_ids"), "policy.validator_ids")
    if len(validator_ids) != 3 or len(set(validator_ids)) != 3:
        raise LiveRuntimeEvidenceError("policy requires three unique validator_ids")

    _identity(validator_runtime, "validator_runtime")
    if validator_runtime.get("schema_version") != "junca-live-validator-runtime/v1":
        raise LiveRuntimeEvidenceError("validator runtime schema is not supported")
    if validator_runtime.get("chain_id") != chain_id:
        raise LiveRuntimeEvidenceError("validator runtime chain_id mismatch")
    if validator_runtime.get("private_key_material_accepted") is not False:
        raise LiveRuntimeEvidenceError("private key material boundary is not proven")

    bindings = validator_runtime.get("signer_bindings")
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise LiveRuntimeEvidenceError("signer_bindings must be a sequence")
    bound_ids: list[str] = []
    key_digests: list[str] = []
    for index, item in enumerate(bindings):
        if not isinstance(item, Mapping):
            raise LiveRuntimeEvidenceError(f"signer_bindings[{index}] must be an object")
        bound_ids.append(_text(item.get("validator_id"), "binding.validator_id"))
        key_digests.append(_digest(item.get("key_resource_digest"), "key_resource_digest"))
        if any(name in item for name in ("key_resource", "private_key", "secret")):
            raise LiveRuntimeEvidenceError("signer evidence contains a secret-bearing field")
    if set(bound_ids) != set(validator_ids) or len(bound_ids) != 3:
        raise LiveRuntimeEvidenceError("signer bindings do not match validator policy")
    if len(set(key_digests)) != 3:
        raise LiveRuntimeEvidenceError("signer resource digests must be distinct")

    if (
        not isinstance(finalized_blocks, Sequence)
        or isinstance(finalized_blocks, (str, bytes))
        or len(finalized_blocks) < 2
    ):
        raise LiveRuntimeEvidenceError("at least two finalized block samples are required")
    heights: list[int] = []
    for index, block in enumerate(finalized_blocks):
        if not isinstance(block, Mapping):
            raise LiveRuntimeEvidenceError(f"finalized_blocks[{index}] must be an object")
        _identity(block, f"finalized_blocks[{index}]")
        if block.get("schema_version") != "junca-live-validator-finalization/v1":
            raise LiveRuntimeEvidenceError("finalized block schema is not supported")
        if block.get("finality_status") != "FINALIZED":
            raise LiveRuntimeEvidenceError("block is not finalized")
        _digest(block.get("block_hash"), "block_hash")
        _digest(block.get("state_root"), "state_root")
        _digest(block.get("certificate_hash"), "certificate_hash")
        signed = _positive_int(block.get("signed_power"), "signed_power")
        total = _positive_int(block.get("total_power"), "total_power")
        if signed * 3 <= total * 2 or signed > total:
            raise LiveRuntimeEvidenceError("finality certificate lacks strict quorum")
        heights.append(_nonnegative_int(block.get("height"), "height"))
    if any(current <= previous for previous, current in zip(heights, heights[1:])):
        raise LiveRuntimeEvidenceError("finalized block heights must strictly advance")
    if validator_runtime.get("head_height") != heights[-1]:
        raise LiveRuntimeEvidenceError("runtime head does not match finalization evidence")

    if not isinstance(operational_observations, Mapping):
        raise LiveRuntimeEvidenceError("operational_observations must be an object")
    observations = dict(operational_observations)
    protected = {
        "chain_id": chain_id,
        "head_samples": list(heights),
        "finalized_head_samples": list(heights),
        "validator_ids": list(validator_ids),
    }
    for field, expected in protected.items():
        if field in observations and observations[field] != expected:
            raise LiveRuntimeEvidenceError(f"operational {field} conflicts with chain evidence")
        observations[field] = expected

    canonical = {
        "policy": policy,
        "validator_runtime": validator_runtime,
        "finalized_blocks": list(finalized_blocks),
        "operational_observations": operational_observations,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return LiveRuntimeEvidenceBundle(observations=observations, source_digest=digest)


def evaluate_live_runtime_acceptance(
    *,
    policy: Mapping[str, Any],
    validator_runtime: Mapping[str, Any],
    finalized_blocks: Sequence[Mapping[str, Any]],
    operational_observations: Mapping[str, Any],
) -> RuntimeAcceptanceV2:
    bundle = build_live_runtime_evidence(
        policy=policy,
        validator_runtime=validator_runtime,
        finalized_blocks=finalized_blocks,
        operational_observations=operational_observations,
    )
    return evaluate_runtime_acceptance_v2(policy, bundle.observations)


def _identity(value: Mapping[str, Any], field: str) -> None:
    if value.get("governance") != GOVERNANCE:
        raise LiveRuntimeEvidenceError(f"{field} governance mismatch")
    network = value.get("network", value.get("notice"))
    if network != NOTICE:
        raise LiveRuntimeEvidenceError(f"{field} network notice mismatch")
    for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
        if value.get(boundary) is not False:
            raise LiveRuntimeEvidenceError(f"{field}.{boundary} must be false")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveRuntimeEvidenceError(f"{field} must be non-empty text")
    return value.strip()


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
    ):
        raise LiveRuntimeEvidenceError(f"{field} must contain non-empty text")
    return tuple(_text(item, field) for item in value)


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LiveRuntimeEvidenceError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LiveRuntimeEvidenceError(f"{field} must be a non-negative integer")
    return value


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise LiveRuntimeEvidenceError(f"{field} must be a lowercase SHA-256")
    return value
