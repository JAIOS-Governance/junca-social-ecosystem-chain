"""Fail-closed canonical cloud binding for the JUNCA public testnet.

The module validates non-secret infrastructure identifiers without selecting a
provider or inventing a project.  It never accepts literal key material and its
evidence output contains only presence flags and a deterministic fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
PROVIDERS = frozenset({"google-cloud", "aws", "azure"})
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SECRET_MARKERS = (
    "private_key",
    "privatekey",
    "mnemonic",
    "seed_phrase",
    "seedphrase",
    "secret_value",
    "password",
)


class CanonicalBindingError(ValueError):
    """Raised when a binding attempts an unsafe or malformed state."""


@dataclass(frozen=True)
class CanonicalBindingEvidence:
    state: str
    blockers: tuple[str, ...]
    binding_fingerprint: str
    evidence: Mapping[str, Any]

    @property
    def ready(self) -> bool:
        return self.state == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-public-testnet-cloud-binding/v1",
            "official_name": OFFICIAL_NAME,
            "governance": GOVERNANCE,
            "notice": NOTICE,
            "state": self.state,
            "blockers": list(self.blockers),
            "binding_fingerprint": self.binding_fingerprint,
            **self.evidence,
        }


def evaluate_canonical_binding(specification: Mapping[str, Any]) -> CanonicalBindingEvidence:
    _reject_secret_material(specification)
    _require_exact(specification, "official_name", OFFICIAL_NAME)
    _require_exact(specification, "governance", GOVERNANCE)
    _require_exact(specification, "notice", NOTICE)
    _require_exact(specification, "environment", "public-testnet")
    for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
        if specification.get(boundary) is not False:
            raise CanonicalBindingError(f"{boundary} must be false")

    blockers: list[str] = []
    canonical: dict[str, Any] = {
        "official_name": OFFICIAL_NAME,
        "governance": GOVERNANCE,
        "notice": NOTICE,
        "environment": "public-testnet",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }

    provider = _binding_text(specification, "provider", blockers)
    if not _pending(provider) and provider not in PROVIDERS:
        raise CanonicalBindingError("provider must be google-cloud, aws, or azure")
    canonical["provider"] = provider

    for field in (
        "account_scope",
        "project_id",
        "region",
        "network_id",
        "dns_zone",
        "state_backend_resource",
        "deployment_principal_resource",
    ):
        canonical[field] = _binding_text(specification, field, blockers)

    release_commit = _binding_text(specification, "release_commit", blockers)
    if not _pending(release_commit) and not COMMIT_SHA.fullmatch(release_commit):
        raise CanonicalBindingError("release_commit must be a lowercase 40-character Git SHA")
    canonical["release_commit"] = release_commit

    failure_domains = _text_sequence(specification.get("failure_domains"), "failure_domains")
    if any(_pending(item) for item in failure_domains):
        blockers.append("failure_domains")
    elif len(failure_domains) != 3 or len(set(failure_domains)) != 3:
        raise CanonicalBindingError("exactly three distinct failure_domains are required")
    canonical["failure_domains"] = sorted(failure_domains)

    signer_resources = _text_sequence(
        specification.get("signer_resources"), "signer_resources"
    )
    if any(_pending(item) for item in signer_resources):
        blockers.append("signer_resources")
    elif len(signer_resources) != 3 or len(set(signer_resources)) != 3:
        raise CanonicalBindingError("exactly three distinct signer_resources are required")
    canonical["signer_resources"] = sorted(signer_resources)

    for field in (
        "billing_active",
        "identity_authenticated",
        "dns_zone_authoritative",
        "secret_resources_present",
    ):
        value = specification.get(field)
        if not isinstance(value, bool):
            raise CanonicalBindingError(f"{field} must be boolean")
        canonical[field] = value
        if not value:
            blockers.append(field)

    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    redacted = {
        "provider_bound": not _pending(provider),
        "account_scope_bound": not _pending(canonical["account_scope"]),
        "project_bound": not _pending(canonical["project_id"]),
        "region_bound": not _pending(canonical["region"]),
        "network_bound": not _pending(canonical["network_id"]),
        "dns_zone_bound": not _pending(canonical["dns_zone"]),
        "state_backend_bound": not _pending(canonical["state_backend_resource"]),
        "deployment_principal_bound": not _pending(
            canonical["deployment_principal_resource"]
        ),
        "failure_domain_count": 0
        if "failure_domains" in blockers
        else len(failure_domains),
        "signer_resource_count": 0
        if "signer_resources" in blockers
        else len(signer_resources),
        "release_commit": release_commit,
        "billing_active": canonical["billing_active"],
        "identity_authenticated": canonical["identity_authenticated"],
        "dns_zone_authoritative": canonical["dns_zone_authoritative"],
        "secret_resources_present": canonical["secret_resources_present"],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    return CanonicalBindingEvidence(
        state="BLOCKED" if blockers else "READY",
        blockers=tuple(sorted(set(blockers))),
        binding_fingerprint=fingerprint,
        evidence=redacted,
    )


def load_canonical_binding(path: str | Path) -> CanonicalBindingEvidence:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalBindingError("unable to load canonical binding") from exc
    if not isinstance(payload, Mapping):
        raise CanonicalBindingError("canonical binding must be an object")
    return evaluate_canonical_binding(payload)


def _binding_text(
    specification: Mapping[str, Any], field: str, blockers: list[str]
) -> str:
    value = specification.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CanonicalBindingError(f"{field} must be non-empty text")
    value = value.strip()
    if _pending(value):
        blockers.append(field)
    return value


def _text_sequence(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise CanonicalBindingError(f"{field} must contain non-empty text")
    return tuple(item.strip() for item in value)


def _require_exact(specification: Mapping[str, Any], field: str, expected: str) -> None:
    if specification.get(field) != expected:
        raise CanonicalBindingError(f"{field} must equal {expected!r}")


def _pending(value: str) -> bool:
    return value.startswith("PENDING_")


def _reject_secret_material(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(marker in key_text for marker in SECRET_MARKERS):
                raise CanonicalBindingError(f"secret material field is forbidden at {path}")
            _reject_secret_material(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _reject_secret_material(child, f"{path}[{index}]")

