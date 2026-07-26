"""Immutable validator runtime artifact and AMI handoff evidence.

This module only packages evidence.  It never builds an AMI, reads signer
secret material, deploys a node, or turns a pending handoff into a live claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
CANONICAL_ACCOUNT = "595710543956"
CANONICAL_REGION = "us-east-1"
_AMI = re.compile(r"^ami-[0-9a-f]{8,17}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ValidatorArtifactError(ValueError):
    """Raised when an immutable runtime handoff is not safe to produce."""


@dataclass(frozen=True)
class ValidatorArtifactHandoff:
    state: str
    evidence: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.evidence)


def build_validator_artifact_handoff(
    specification: Mapping[str, Any],
    *,
    node_binary: Path,
    genesis: Path,
) -> ValidatorArtifactHandoff:
    """Verify local immutable inputs and produce a deployer-facing handoff."""
    _exact(specification, "governance", GOVERNANCE)
    _exact(specification, "notice", NOTICE)
    _exact(specification, "aws_account_id", CANONICAL_ACCOUNT)
    _exact(specification, "aws_region", CANONICAL_REGION)
    for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
        if specification.get(boundary) is not False:
            raise ValidatorArtifactError(f"{boundary} must be false")

    source_commit = _match(specification.get("source_commit"), _COMMIT, "source_commit")
    ami_id = _match(specification.get("ami_id"), _AMI, "ami_id")
    validators = _texts(specification.get("validator_ids"), "validator_ids")
    if len(validators) != 3 or len(set(validators)) != 3:
        raise ValidatorArtifactError("three unique validator_ids are required")
    if set(validators) != {"validator-01", "validator-02", "validator-03"}:
        raise ValidatorArtifactError("canonical validator IDs are required")

    signer_arns = _texts(specification.get("signer_arns"), "signer_arns")
    if len(signer_arns) != 3 or len(set(signer_arns)) != 3:
        raise ValidatorArtifactError("three distinct signer ARNs are required")
    prefix = f"arn:aws:kms:{CANONICAL_REGION}:{CANONICAL_ACCOUNT}:key/"
    if any(not arn.startswith(prefix) for arn in signer_arns):
        raise ValidatorArtifactError("signers must use canonical AWS KMS resources")

    binary_digest = _file_digest(node_binary, "node_binary")
    genesis_digest = _file_digest(genesis, "genesis")
    genesis_data = _json_object(genesis)
    if genesis_data.get("chain_id") != specification.get("chain_id"):
        raise ValidatorArtifactError("genesis chain_id does not match specification")
    if genesis_data.get("network") != "public-testnet":
        raise ValidatorArtifactError("genesis must identify public-testnet")
    if genesis_data.get("notice") != NOTICE:
        raise ValidatorArtifactError("genesis notice is not canonical")
    genesis_validators = _texts(genesis_data.get("validator_ids"), "genesis.validator_ids")
    if tuple(genesis_validators) != tuple(validators):
        raise ValidatorArtifactError("genesis validator order does not match handoff")

    canonical_spec = json.dumps(
        specification, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    evidence: dict[str, Any] = {
        "schema_version": "junca-validator-artifact-handoff/v1",
        "state": "READY_FOR_AWS_AMI_READBACK",
        "governance": GOVERNANCE,
        "notice": NOTICE,
        "aws_account_id": CANONICAL_ACCOUNT,
        "aws_region": CANONICAL_REGION,
        "source_commit": source_commit,
        "ami_id": ami_id,
        "chain_id": specification.get("chain_id"),
        "validator_ids": list(validators),
        "validator_count": 3,
        "node_artifact_sha256": binary_digest,
        "genesis_sha256": genesis_digest,
        "specification_sha256": hashlib.sha256(canonical_spec).hexdigest(),
        "signer_resource_digests": [
            hashlib.sha256(arn.encode("utf-8")).hexdigest() for arn in signer_arns
        ],
        "ami_readback_required": True,
        "live_runtime_verified": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    evidence["handoff_digest"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ValidatorArtifactHandoff(state=evidence["state"], evidence=evidence)


def pending_validator_artifact_handoff() -> ValidatorArtifactHandoff:
    blockers = [
        "immutable_node_binary",
        "canonical_public_testnet_genesis",
        "approved_ami_id",
        "three_canonical_kms_signer_arns",
        "aws_ami_digest_readback",
        "three_validator_quorum",
        "runtime_acceptance",
    ]
    evidence = {
        "schema_version": "junca-validator-artifact-handoff/v1",
        "state": "BLOCKED_FAIL_CLOSED",
        "governance": GOVERNANCE,
        "notice": NOTICE,
        "aws_account_id": CANONICAL_ACCOUNT,
        "aws_region": CANONICAL_REGION,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "blockers": blockers,
        "ami_readback_required": True,
        "live_runtime_verified": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    evidence["handoff_digest"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ValidatorArtifactHandoff(state=evidence["state"], evidence=evidence)


def _file_digest(path: Path, field: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValidatorArtifactError(f"{field} must be a regular non-symlink file")
    data = path.read_bytes()
    if not data:
        raise ValidatorArtifactError(f"{field} must not be empty")
    return hashlib.sha256(data).hexdigest()


def _json_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidatorArtifactError("genesis must be valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise ValidatorArtifactError("genesis must be a JSON object")
    return value


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValidatorArtifactError(f"{field} must contain non-empty text")
    return tuple(item.strip() for item in value)


def _match(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValidatorArtifactError(f"{field} has invalid format")
    return value


def _exact(specification: Mapping[str, Any], field: str, expected: str) -> None:
    if specification.get(field) != expected:
        raise ValidatorArtifactError(f"{field} must equal {expected!r}")
