"""Canonical brand contract for JUNCA Social Ecosystem Chain."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
DISPLAY_NAME = "JUNCA SOCIAL ECOSYSTEM CHAIN"
SHORT_REFERENCE = "JUNCA Chain"
BRAND_SCHEMA = "junca-social-ecosystem-chain-brand/v1"
BRAND_HIERARCHY = (
    "ONE CORE",
    "JUNCA Intelligence Ecosystem",
    OFFICIAL_NAME,
)


class ChainBrandError(RuntimeError):
    """Raised when the chain brand contract is incomplete or inconsistent."""


@dataclass(frozen=True)
class ChainBrand:
    official_name: str
    display_name: str
    short_reference: str
    japanese_descriptor: str
    brand_hierarchy: tuple[str, ...]
    architecture_role: str
    narrative_en: str
    narrative_ja: str
    former_public_name: str
    former_name_usage: str
    unapproved_abbreviations: tuple[str, ...]
    reserved_superordinate_names: tuple[str, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": BRAND_SCHEMA,
            "official_name": self.official_name,
            "display_name": self.display_name,
            "short_reference": self.short_reference,
            "brand_hierarchy": list(self.brand_hierarchy),
            "architecture_role": self.architecture_role,
            "former_public_name": self.former_public_name,
            "former_name_usage": self.former_name_usage,
            "brand_status": "canonical",
        }


def load_brand_contract(path: str | Path) -> ChainBrand:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainBrandError(f"unable to load brand contract: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainBrandError("brand contract must be a JSON object")
    _require(raw, "schema_version", BRAND_SCHEMA)
    _require(raw, "official_name", OFFICIAL_NAME)
    _require(raw, "display_name", DISPLAY_NAME)
    _require(raw, "short_reference", SHORT_REFERENCE)

    hierarchy = _string_tuple(raw.get("brand_hierarchy"), "brand_hierarchy")
    if hierarchy != BRAND_HIERARCHY:
        raise ChainBrandError(
            "brand_hierarchy must preserve ONE CORE, JUNCA Intelligence Ecosystem, "
            "and JUNCA Social Ecosystem Chain in that order"
        )

    narrative = _mapping(raw.get("canonical_narrative"), "canonical_narrative")
    naming = _mapping(raw.get("naming_policy"), "naming_policy")
    _require(naming, "former_public_name", "JUNCA Global Chain")
    _require(
        naming,
        "former_name_usage",
        "legacy-history-and-migration-reference-only",
    )
    reserved = _string_tuple(
        naming.get("reserved_superordinate_names"),
        "reserved_superordinate_names",
    )
    if reserved != BRAND_HIERARCHY[:2]:
        raise ChainBrandError("reserved_superordinate_names must preserve upper layers")

    return ChainBrand(
        official_name=OFFICIAL_NAME,
        display_name=DISPLAY_NAME,
        short_reference=SHORT_REFERENCE,
        japanese_descriptor=_text(
            raw.get("japanese_descriptor"),
            "japanese_descriptor",
        ),
        brand_hierarchy=hierarchy,
        architecture_role=_text(raw.get("architecture_role"), "architecture_role"),
        narrative_en=_text(narrative.get("en"), "canonical_narrative.en"),
        narrative_ja=_text(narrative.get("ja"), "canonical_narrative.ja"),
        former_public_name="JUNCA Global Chain",
        former_name_usage="legacy-history-and-migration-reference-only",
        unapproved_abbreviations=_string_tuple(
            naming.get("unapproved_abbreviations"),
            "unapproved_abbreviations",
        ),
        reserved_superordinate_names=reserved,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChainBrandError(f"{field} must be an object")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ChainBrandError(f"{field} must be a non-empty string list")
    result = tuple(item.strip() for item in value)
    if len(result) != len(set(result)):
        raise ChainBrandError(f"{field} contains duplicates")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ChainBrandError(f"{field} must contain 1-500 characters")
    return value.strip()


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise ChainBrandError(f"{field} must be {expected!r}")
