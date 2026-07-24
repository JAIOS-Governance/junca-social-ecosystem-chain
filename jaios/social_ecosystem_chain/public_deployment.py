"""Fail-closed public testnet infrastructure binding and release evidence."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


REQUIRED_GOVERNANCE = "JAIOS Institutional Governance"
REQUIRED_NOTICE = "Public Testnet / No Monetary Value"
SECRET_RESOURCE = re.compile(
    r"^projects/[a-z][a-z0-9-]{4,28}/secrets/[A-Za-z0-9_-]{1,255}/versions/(?:[1-9][0-9]*|latest)$"
)
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class PublicDeploymentError(ValueError):
    pass


@dataclass(frozen=True)
class PublicDeploymentEvidence:
    state: str
    digest: str
    blockers: tuple[str, ...]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "deployment_digest": self.digest,
            "blockers": list(self.blockers),
            **self.evidence,
        }


def evaluate_public_deployment(specification: Mapping[str, Any]) -> PublicDeploymentEvidence:
    _require_exact(specification, "governance", REQUIRED_GOVERNANCE)
    _require_exact(specification, "notice", REQUIRED_NOTICE)
    _require_exact(specification, "environment", "public-testnet")

    chain_id = specification.get("chain_id")
    if not isinstance(chain_id, int) or isinstance(chain_id, bool) or chain_id <= 0:
        raise PublicDeploymentError("chain_id must be a positive integer")

    validators = specification.get("validators")
    if not isinstance(validators, list) or len(validators) != 3:
        raise PublicDeploymentError("exactly three validators are required")

    blockers: list[str] = []
    normalized_validators: list[dict[str, str]] = []
    validator_ids: set[str] = set()
    for index, validator in enumerate(validators):
        if not isinstance(validator, Mapping):
            raise PublicDeploymentError(f"validator {index} must be an object")
        validator_id = _required_text(validator, "id")
        if validator_id in validator_ids:
            raise PublicDeploymentError("validator ids must be unique")
        validator_ids.add(validator_id)
        signer = _required_text(validator, "signer_secret_resource")
        if _is_pending(signer):
            blockers.append(f"validators[{index}].signer_secret_resource")
        elif not SECRET_RESOURCE.fullmatch(signer):
            raise PublicDeploymentError(
                f"validators[{index}].signer_secret_resource must be a Secret Manager version resource"
            )
        normalized_validators.append({"id": validator_id, "signer_secret_resource": signer})

    endpoints = specification.get("endpoints")
    if not isinstance(endpoints, Mapping):
        raise PublicDeploymentError("endpoints must be an object")
    normalized_endpoints: dict[str, str] = {}
    for name in ("rpc", "explorer", "health"):
        endpoint = _required_text(endpoints, name)
        if _is_pending(endpoint):
            blockers.append(f"endpoints.{name}")
        else:
            _validate_public_https_endpoint(name, endpoint)
        normalized_endpoints[name] = endpoint

    release_commit = _required_text(specification, "release_commit")
    if _is_pending(release_commit):
        blockers.append("release_commit")
    elif not COMMIT_SHA.fullmatch(release_commit):
        raise PublicDeploymentError("release_commit must be a lowercase 40-character Git SHA")

    attestations = specification.get("attestations")
    if not isinstance(attestations, Mapping):
        raise PublicDeploymentError("attestations must be an object")
    normalized_attestations: dict[str, bool] = {}
    for name in (
        "dns_tls_verified",
        "validator_quorum_verified",
        "rpc_acceptance_verified",
        "explorer_parity_verified",
        "monitoring_verified",
        "rollback_verified",
        "security_review_approved",
    ):
        value = attestations.get(name)
        if not isinstance(value, bool):
            raise PublicDeploymentError(f"attestations.{name} must be boolean")
        normalized_attestations[name] = value
        if not value:
            blockers.append(f"attestations.{name}")

    canonical = {
        "schema_version": 1,
        "environment": "public-testnet",
        "chain_id": chain_id,
        "governance": REQUIRED_GOVERNANCE,
        "notice": REQUIRED_NOTICE,
        "release_commit": release_commit,
        "validators": normalized_validators,
        "endpoints": normalized_endpoints,
        "attestations": normalized_attestations,
        "mainnet_changed": False,
        "assets_moved": False,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return PublicDeploymentEvidence(
        "BLOCKED" if blockers else "ACCEPTED",
        digest,
        tuple(sorted(blockers)),
        canonical,
    )


def load_public_deployment(path: str | Path) -> PublicDeploymentEvidence:
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicDeploymentError(f"unable to load deployment specification: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicDeploymentError("deployment specification must be an object")
    return evaluate_public_deployment(payload)


def _require_exact(specification: Mapping[str, Any], key: str, expected: str) -> None:
    if specification.get(key) != expected:
        raise PublicDeploymentError(f"{key} must equal {expected!r}")


def _required_text(specification: Mapping[str, Any], key: str) -> str:
    value = specification.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublicDeploymentError(f"{key} must be non-empty text")
    return value.strip()


def _is_pending(value: str) -> bool:
    return value.startswith("PENDING_")


def _validate_public_https_endpoint(name: str, endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise PublicDeploymentError(f"endpoints.{name} must be an HTTPS URL without credentials")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise PublicDeploymentError(f"endpoints.{name} must be publicly routable")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise PublicDeploymentError(f"endpoints.{name} must be publicly routable")
