"""Fail-closed validation for the canonical chain repository boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CHAIN_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
PENDING_OWNER = "PENDING_JAIOS_GITHUB_ORGANIZATION"
PROHIBITED_PUBLIC_IDENTITIES = (
    "CEO-controlled",
    "CEO-managed",
    "founder-controlled",
    "sole personal authority",
    "corporate-owned chain",
)


class RepositoryGovernanceError(ValueError):
    pass


def evaluate_repository_boundary(
    specification: Mapping[str, Any], root: str | Path = "."
) -> dict[str, Any]:
    _exact(specification, "chain_name", CHAIN_NAME)
    _exact(specification, "governance", GOVERNANCE)
    _exact(specification, "network_notice", NOTICE)
    _exact(specification, "repository_role", "canonical-protocol-source")

    if specification.get("corporate_ownership_represented") is not False:
        raise RepositoryGovernanceError(
            "corporate_ownership_represented must remain false"
        )
    if specification.get("personal_control_represented") is not False:
        raise RepositoryGovernanceError(
            "personal_control_represented must remain false"
        )

    owner = _text(specification, "repository_owner_binding")
    blockers: list[str] = []
    if owner == PENDING_OWNER:
        blockers.append("repository_owner_binding")

    required_paths = specification.get("required_paths")
    if not isinstance(required_paths, list) or not required_paths:
        raise RepositoryGovernanceError("required_paths must be a non-empty list")
    repository_root = Path(root)
    missing = [
        path
        for path in required_paths
        if not isinstance(path, str) or not (repository_root / path).exists()
    ]
    if missing:
        raise RepositoryGovernanceError(
            "required repository paths are missing: " + ", ".join(map(str, missing))
        )

    release_boundary = specification.get("release_boundary")
    if not isinstance(release_boundary, Mapping):
        raise RepositoryGovernanceError("release_boundary must be an object")
    for key in (
        "mainnet_changed",
        "assets_moved",
        "bridge_activated",
        "cloud_binding_ready",
    ):
        if release_boundary.get(key) is not False:
            raise RepositoryGovernanceError(f"release_boundary.{key} must be false")

    return {
        "state": "BLOCKED" if blockers else "READY",
        "blockers": blockers,
        "chain_name": CHAIN_NAME,
        "governance": GOVERNANCE,
        "network_notice": NOTICE,
        "repository_owner_binding": owner,
        "repository_role": "canonical-protocol-source",
        "corporate_ownership_represented": False,
        "personal_control_represented": False,
        "release_boundary": dict(release_boundary),
    }


def load_repository_boundary(
    path: str | Path = "governance/repository-boundary.json",
    root: str | Path = ".",
) -> dict[str, Any]:
    try:
        specification = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryGovernanceError(
            f"unable to load repository boundary: {exc}"
        ) from exc
    if not isinstance(specification, Mapping):
        raise RepositoryGovernanceError("repository boundary must be an object")
    return evaluate_repository_boundary(specification, root)


def scan_public_identity(text: str) -> tuple[str, ...]:
    lowered = text.casefold()
    return tuple(
        phrase
        for phrase in PROHIBITED_PUBLIC_IDENTITIES
        if phrase.casefold() in lowered
    )


def _exact(specification: Mapping[str, Any], key: str, expected: str) -> None:
    if specification.get(key) != expected:
        raise RepositoryGovernanceError(f"{key} must equal {expected!r}")


def _text(specification: Mapping[str, Any], key: str) -> str:
    value = specification.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RepositoryGovernanceError(f"{key} must be non-empty text")
    return value.strip()
