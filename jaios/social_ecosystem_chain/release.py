"""Machine-verifiable institutional release policy for JUNCA Social Ecosystem Chain."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .branding import OFFICIAL_NAME


class ChainReleasePolicyError(RuntimeError):
    """Raised when the release authority, representation, or custody policy is unsafe."""


REQUIRED_CONTROLS = frozenset({
    "source-provenance",
    "reproducible-build",
    "genesis-fingerprint",
    "new-key-custody",
    "validator-quorum",
    "rpc-method-boundary",
    "explorer-head-parity",
    "governance-readback",
    "rollback-package",
    "independent-post-release-readback",
})

PROHIBITED_FIELD_MARKERS = (
    "private_key",
    "private-key",
    "mnemonic",
    "seed_phrase",
    "seed-phrase",
    "password",
    "secret",
    "token",
)

PROHIBITED_PUBLIC_CONTROL_TERMS = (
    "ceo-controlled",
    "ceo-sovereign",
    "sole personal authority",
    "ceo管理",
    "ceo支配",
    "個人による単独支配",
)

ALLOWED_SAFETY_FIELDS = frozenset({"secrets_in_repository"})


@dataclass(frozen=True)
class ChainReleasePolicy:
    schema_version: str
    release_model: str
    governance_entity: str
    source_repository: str
    brand: str
    testnet_strategy: str
    mainnet_strategy: str
    issuance_management: str
    testnet_label: str
    required_controls: tuple[str, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "release_model": self.release_model,
            "governance_entity": self.governance_entity,
            "source_repository": self.source_repository,
            "brand": self.brand,
            "testnet_strategy": self.testnet_strategy,
            "mainnet_strategy": self.mainnet_strategy,
            "issuance_management": self.issuance_management,
            "testnet_label": self.testnet_label,
            "required_controls": list(self.required_controls),
            "policy_status": "valid",
            "release_status": "pending-runtime-evidence",
        }


def load_release_policy(path: str | Path) -> ChainReleasePolicy:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainReleasePolicyError(f"unable to load release policy: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainReleasePolicyError("release policy must be a JSON object")
    _reject_sensitive_fields(raw)
    _reject_personal_control_representation(raw)

    if raw.get("schema_version") != "junca-social-ecosystem-chain-release/v2":
        raise ChainReleasePolicyError("unsupported release policy schema")
    if raw.get("release_model") != "institutional-governance":
        raise ChainReleasePolicyError("release model must be institutional-governance")

    authority = _mapping(raw.get("authority"), "authority")
    _require(authority, "public_governance_entity", "JAIOS Institutional Governance")
    _require(authority, "approval_model", "internal-governance-control")
    _require(authority, "operator_model", "jaios-controlled-automation")
    _require(authority, "former_team_dependency", "prohibited")
    _require(authority, "personal_control_representation", "prohibited")
    governance_entity = _text(authority.get("public_governance_entity"), "public_governance_entity")
    repository = _text(authority.get("source_repository"), "source_repository")

    assets = _mapping(raw.get("asset_policy"), "asset_policy")
    _require(assets, "legacy_source", "audit-reference-only")
    _require(assets, "legacy_keys", "prohibited")
    _require(assets, "legacy_credentials", "prohibited")
    if assets.get("new_keys_required") is not True:
        raise ChainReleasePolicyError("new_keys_required must be true")
    if assets.get("secrets_in_repository") is not False:
        raise ChainReleasePolicyError("secrets_in_repository must be false")

    strategy = _mapping(raw.get("network_strategy"), "network_strategy")
    _require(strategy, "brand", OFFICIAL_NAME)
    _require(strategy, "testnet", "new-genesis")
    _require(strategy, "mainnet", "snapshot-audit-before-continuity-decision")
    if strategy.get("reuse_legacy_chain_id_before_decision") is not False:
        raise ChainReleasePolicyError(
            "legacy chain IDs must not be reused before the continuity decision"
        )

    representation = _mapping(raw.get("public_representation"), "public_representation")
    _require(representation, "issuance_management", "JAIOS Institutional Governance")
    _require(representation, "testnet_label", "Public Testnet / No Monetary Value")
    _require(representation, "decentralization_claims", "evidence-required")
    _require(representation, "responsibility_disclosure", "mandatory")

    controls_raw = raw.get("required_controls")
    if not isinstance(controls_raw, list) or not all(
        isinstance(item, str) and item for item in controls_raw
    ):
        raise ChainReleasePolicyError("required_controls must be a string list")
    controls = tuple(controls_raw)
    if len(controls) != len(set(controls)):
        raise ChainReleasePolicyError("required_controls contains duplicates")
    missing = REQUIRED_CONTROLS.difference(controls)
    if missing:
        raise ChainReleasePolicyError(
            f"required_controls missing: {', '.join(sorted(missing))}"
        )

    return ChainReleasePolicy(
        schema_version=str(raw["schema_version"]),
        release_model=str(raw["release_model"]),
        governance_entity=governance_entity,
        source_repository=repository,
        brand=OFFICIAL_NAME,
        testnet_strategy=str(strategy["testnet"]),
        mainnet_strategy=str(strategy["mainnet"]),
        issuance_management=str(representation["issuance_management"]),
        testnet_label=str(representation["testnet_label"]),
        required_controls=controls,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChainReleasePolicyError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ChainReleasePolicyError(f"{field} must contain 1-200 characters")
    return value.strip()


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise ChainReleasePolicyError(f"{field} must be {expected!r}")


def _reject_sensitive_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if (
                normalized not in ALLOWED_SAFETY_FIELDS
                and any(marker in normalized for marker in PROHIBITED_FIELD_MARKERS)
            ):
                raise ChainReleasePolicyError(
                    f"sensitive field is prohibited in release policy: {path}.{key}"
                )
            _reject_sensitive_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


def _reject_personal_control_representation(value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False).lower()
    matches = [term for term in PROHIBITED_PUBLIC_CONTROL_TERMS if term in rendered]
    if matches:
        raise ChainReleasePolicyError(
            "personal-control representation is prohibited: " + ", ".join(matches)
        )
