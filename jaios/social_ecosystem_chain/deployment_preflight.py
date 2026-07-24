"""Fail-closed public-testnet deployment preflight without secret disclosure."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "junca-public-testnet-deployment-preflight/v1"
OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE_ENTITY = "JAIOS Institutional Governance"
RUNTIME_CHECKS = (
    "validator_quorum_verified",
    "rpc_boundary_verified",
    "explorer_head_parity_verified",
    "governance_readback_verified",
    "independent_readback_verified",
)
DIGEST_FIELDS = ("genesis_digest", "binary_digest", "backup_manifest_digest")
SECRET_MARKERS = ("private_key", "mnemonic", "seed_phrase", "password", "secret_value")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class DeploymentPreflightError(RuntimeError):
    """Raised when deployment evidence is malformed or unsafe."""


@dataclass(frozen=True)
class DeploymentPreflight:
    source_commit: str
    validator_attestations: tuple[bool, ...]
    rollback_complete: bool
    runtime_checks: tuple[tuple[str, bool], ...]

    @property
    def missing_controls(self) -> tuple[str, ...]:
        missing: list[str] = []
        for index, passed in enumerate(self.validator_attestations, start=1):
            if not passed:
                missing.append(f"validator-{index}-custody")
        if not self.rollback_complete:
            missing.append("rollback-package")
        missing.extend(name for name, passed in self.runtime_checks if not passed)
        return tuple(missing)

    @property
    def state(self) -> str:
        return "ready" if self.source_commit != "pending" and not self.missing_controls else "blocked"

    def assert_deployable(self) -> None:
        if self.state != "ready":
            controls = list(self.missing_controls)
            if self.source_commit == "pending":
                controls.insert(0, "source-commit")
            raise DeploymentPreflightError("deployment blocked by: " + ", ".join(controls))

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "release_target": "public-testnet",
            "governance_entity": GOVERNANCE_ENTITY,
            "source_commit": self.source_commit,
            "validator_attestations": list(self.validator_attestations),
            "rollback_complete": self.rollback_complete,
            "runtime_checks": dict(self.runtime_checks),
            "state": self.state,
            "missing_controls": list(self.missing_controls),
            "secret_material_in_evidence": False,
        }


def load_deployment_preflight(path: str | Path) -> DeploymentPreflight:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentPreflightError("unable to load deployment preflight") from exc
    if not isinstance(raw, Mapping):
        raise DeploymentPreflightError("deployment preflight must be an object")
    _reject_secret_fields(raw)
    _require(raw, "schema_version", SCHEMA_VERSION)
    _require(raw, "official_name", OFFICIAL_NAME)
    _require(raw, "release_target", "public-testnet")
    _require(raw, "governance_entity", GOVERNANCE_ENTITY)

    source_commit = _text(raw.get("source_commit"), "source_commit")
    if source_commit != "pending" and not SHA.fullmatch(source_commit):
        raise DeploymentPreflightError("source_commit must be pending or a lowercase SHA")

    custody = _mapping(raw.get("custody"), "custody")
    _require(custody, "generation_environment", "deployment-environment-only")
    _require(custody, "key_provider", "secret-manager-or-hsm")
    _require(custody, "legacy_key_reuse", False)
    _require(custody, "repository_secret_material", False)
    validators = custody.get("validators")
    if not isinstance(validators, list) or len(validators) != 3:
        raise DeploymentPreflightError("exactly three validator custody records are required")
    attestations: list[bool] = []
    for index, item in enumerate(validators, start=1):
        record = _mapping(item, f"custody.validators[{index}]")
        _require(record, "name", f"validator-{index}")
        attested = record.get("attested")
        if not isinstance(attested, bool):
            raise DeploymentPreflightError("validator attested must be boolean")
        fields = (record.get("public_address"), record.get("key_id_digest"), record.get("created_at"))
        if attested:
            if not ADDRESS.fullmatch(str(fields[0])):
                raise DeploymentPreflightError("attested validator requires a public address")
            if not DIGEST.fullmatch(str(fields[1])):
                raise DeploymentPreflightError("attested validator requires a key ID digest")
            if not TIMESTAMP.fullmatch(str(fields[2])):
                raise DeploymentPreflightError("attested validator requires an UTC timestamp")
        elif fields != ("pending", "pending", "pending"):
            raise DeploymentPreflightError("unattested validator fields must remain pending")
        attestations.append(attested)

    rollback = _mapping(raw.get("rollback"), "rollback")
    _require(rollback, "package_version", "v1")
    _require(rollback, "governance_entity", GOVERNANCE_ENTITY)
    restore_tested = rollback.get("restore_tested")
    if not isinstance(restore_tested, bool):
        raise DeploymentPreflightError("restore_tested must be boolean")
    digest_values = tuple(rollback.get(name) for name in DIGEST_FIELDS)
    if restore_tested:
        if not all(DIGEST.fullmatch(str(value)) for value in digest_values):
            raise DeploymentPreflightError("tested rollback requires all SHA-256 digests")
    elif digest_values != ("pending", "pending", "pending"):
        raise DeploymentPreflightError("untested rollback digests must remain pending")

    runtime = _mapping(raw.get("runtime"), "runtime")
    if tuple(runtime) != RUNTIME_CHECKS:
        raise DeploymentPreflightError("runtime check set mismatch")
    checks: list[tuple[str, bool]] = []
    for name in RUNTIME_CHECKS:
        value = runtime[name]
        if not isinstance(value, bool):
            raise DeploymentPreflightError(f"{name} must be boolean")
        checks.append((name, value))

    return DeploymentPreflight(
        source_commit=source_commit,
        validator_attestations=tuple(attestations),
        rollback_complete=restore_tested and all(DIGEST.fullmatch(str(value)) for value in digest_values),
        runtime_checks=tuple(checks),
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeploymentPreflightError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise DeploymentPreflightError(f"{field} is invalid")
    return value


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise DeploymentPreflightError(f"{field} must be {expected!r}")


def _reject_secret_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in SECRET_MARKERS):
                raise DeploymentPreflightError(f"secret field prohibited: {path}.{key}")
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")
