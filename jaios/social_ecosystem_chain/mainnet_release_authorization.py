"""Fail-closed validation for Mainnet controlled-activation authorization evidence.

This module validates an authorization envelope.  It does not activate a network,
move assets, dispatch a release, or mutate an external system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping


class MainnetReleaseAuthorizationError(RuntimeError):
    """Raised when controlled-activation evidence is incomplete or unsafe."""


SCHEMA_VERSION = "junca-mainnet-release-authorization/v1"
REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain"
MAX_AUTHORIZATION_WINDOW = timedelta(minutes=15)
MAX_APPROVAL_AGE = timedelta(hours=24)
MAX_REVIEW_AGE = timedelta(hours=72)
HEX_40 = frozenset("0123456789abcdef")
BOUND_HEX_64_FIELDS = (
    "release_manifest_sha256",
    "request_digest",
    "artifact_sha256",
    "sbom_sha256",
    "genesis_sha256",
    "constitution_sha256",
)
SAFETY_BOUNDARIES = (
    "mainnet_changed",
    "assets_moved",
    "bridge_activated",
    "mainnet_activation_authorized",
)


@dataclass(frozen=True)
class ValidatedMainnetReleaseAuthorization:
    authorization_id: str
    authorization_digest: str
    request_digest: str
    release_manifest_sha256: str
    not_before: datetime
    expires_at: datetime

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "authorization_id": self.authorization_id,
            "authorization_digest": self.authorization_digest,
            "request_digest": self.request_digest,
            "release_manifest_sha256": self.release_manifest_sha256,
            "not_before": _render_time(self.not_before),
            "expires_at": _render_time(self.expires_at),
            "authorization_evidence_valid": True,
            "activation_executed": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def compute_authorization_digest(envelope: Mapping[str, Any]) -> str:
    """Compute the domain-separated digest for an authorization envelope."""

    material = {
        key: envelope.get(key)
        for key in (
            "schema_version",
            "authorization_id",
            "environment",
            "decision",
            "binding",
            "approval",
            "reviews",
            "window",
            "safety_boundaries",
        )
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"JUNCA-MAINNET-AUTHORIZATION-V1\0" + encoded).hexdigest()


def validate_mainnet_release_authorization(
    envelope: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    consumed_records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> ValidatedMainnetReleaseAuthorization:
    """Validate exact provenance, freshness, review, safety, and replay controls."""

    if not isinstance(envelope, Mapping):
        raise MainnetReleaseAuthorizationError("authorization envelope must be an object")
    if not isinstance(expected_binding, Mapping):
        raise MainnetReleaseAuthorizationError("expected binding must be an object")
    _exact_fields(
        expected_binding,
        {
            "repository",
            "source_commit_sha",
            "source_tree_sha",
            *BOUND_HEX_64_FIELDS,
            "constitution_revision_id",
            "approver_identity",
        },
        "expected binding",
    )
    current = _utc(now or datetime.now(timezone.utc), "now")

    _exact_fields(
        envelope,
        {
            "schema_version",
            "authorization_id",
            "environment",
            "decision",
            "binding",
            "approval",
            "reviews",
            "window",
            "safety_boundaries",
            "authorization_digest",
        },
        "authorization envelope",
    )

    _require(envelope, "schema_version", SCHEMA_VERSION)
    _require(envelope, "environment", "mainnet")
    _require(envelope, "decision", "authorized")
    authorization_id = _text(envelope.get("authorization_id"), "authorization_id", 128)

    binding = _mapping(envelope.get("binding"), "binding")
    _exact_fields(
        binding,
        {
            "repository",
            "source_commit_sha",
            "source_tree_sha",
            *BOUND_HEX_64_FIELDS,
            "constitution_revision_id",
        },
        "binding",
    )
    _require(binding, "repository", REPOSITORY)
    _hex(binding.get("source_commit_sha"), 40, "binding.source_commit_sha")
    _hex(binding.get("source_tree_sha"), 40, "binding.source_tree_sha")
    for field in BOUND_HEX_64_FIELDS:
        _hex(binding.get(field), 64, f"binding.{field}")
    _text(binding.get("constitution_revision_id"), "binding.constitution_revision_id", 256)
    _validate_exact_binding(binding, expected_binding)

    window = _mapping(envelope.get("window"), "window")
    _exact_fields(window, {"not_before", "expires_at"}, "window")
    not_before = _time(window.get("not_before"), "window.not_before")
    expires_at = _time(window.get("expires_at"), "window.expires_at")
    if expires_at <= not_before:
        raise MainnetReleaseAuthorizationError("authorization window must advance")
    if expires_at - not_before > MAX_AUTHORIZATION_WINDOW:
        raise MainnetReleaseAuthorizationError("authorization window exceeds 15 minutes")
    if current < not_before:
        raise MainnetReleaseAuthorizationError("authorization is not yet valid")
    if current > expires_at:
        raise MainnetReleaseAuthorizationError("authorization has expired")

    approval = _mapping(envelope.get("approval"), "approval")
    _exact_fields(
        approval,
        {"approver_identity", "approver_role", "approved_at"},
        "approval",
    )
    approver = _text(approval.get("approver_identity"), "approval.approver_identity", 200)
    _require(approval, "approver_role", "Founder / Chairman / CEO")
    approved_at = _time(approval.get("approved_at"), "approval.approved_at")
    if approved_at > not_before:
        raise MainnetReleaseAuthorizationError("approval postdates authorization window")
    if not_before - approved_at > MAX_APPROVAL_AGE:
        raise MainnetReleaseAuthorizationError("approval evidence is older than 24 hours")
    expected_approver = _text(
        expected_binding.get("approver_identity"),
        "expected_binding.approver_identity",
        200,
    )
    if approver != expected_approver:
        raise MainnetReleaseAuthorizationError("approver identity mismatch")

    reviews = envelope.get("reviews")
    if not isinstance(reviews, list) or len(reviews) < 2:
        raise MainnetReleaseAuthorizationError("at least two independent reviews are required")
    reviewer_ids: set[str] = set()
    review_ids: set[str] = set()
    for index, value in enumerate(reviews):
        review = _mapping(value, f"reviews[{index}]")
        _exact_fields(
            review,
            {
                "reviewer_identity",
                "review_id",
                "reviewed_commit_sha",
                "reviewed_tree_sha",
                "verdict",
                "submitted_at",
            },
            f"reviews[{index}]",
        )
        reviewer = _text(
            review.get("reviewer_identity"), f"reviews[{index}].reviewer_identity", 200
        )
        review_id = _text(review.get("review_id"), f"reviews[{index}].review_id", 200)
        if reviewer == approver:
            raise MainnetReleaseAuthorizationError("approver cannot be an independent reviewer")
        if reviewer in reviewer_ids or review_id in review_ids:
            raise MainnetReleaseAuthorizationError("review identities and IDs must be unique")
        reviewer_ids.add(reviewer)
        review_ids.add(review_id)
        _require(review, "verdict", "approved")
        if review.get("reviewed_commit_sha") != binding["source_commit_sha"]:
            raise MainnetReleaseAuthorizationError("review commit provenance mismatch")
        if review.get("reviewed_tree_sha") != binding["source_tree_sha"]:
            raise MainnetReleaseAuthorizationError("review tree provenance mismatch")
        submitted_at = _time(review.get("submitted_at"), f"reviews[{index}].submitted_at")
        if submitted_at > approved_at:
            raise MainnetReleaseAuthorizationError("review postdates final approval")
        if approved_at - submitted_at > MAX_REVIEW_AGE:
            raise MainnetReleaseAuthorizationError("review evidence is older than 72 hours")

    safety = _mapping(envelope.get("safety_boundaries"), "safety_boundaries")
    _exact_fields(safety, set(SAFETY_BOUNDARIES), "safety_boundaries")
    for field in SAFETY_BOUNDARIES:
        if safety.get(field) is not False:
            raise MainnetReleaseAuthorizationError(f"safety boundary must be false: {field}")

    supplied_digest = _hex(
        envelope.get("authorization_digest"), 64, "authorization_digest"
    )
    calculated_digest = compute_authorization_digest(envelope)
    if supplied_digest != calculated_digest:
        raise MainnetReleaseAuthorizationError("authorization digest mismatch")

    request_digest = str(binding["request_digest"])
    manifest_digest = str(binding["release_manifest_sha256"])
    for index, record_value in enumerate(consumed_records):
        record = _mapping(record_value, f"consumed_records[{index}]")
        comparisons = (
            ("authorization_id", authorization_id),
            ("authorization_digest", supplied_digest),
            ("request_digest", request_digest),
            ("release_manifest_sha256", manifest_digest),
        )
        for field, current_value in comparisons:
            if record.get(field) == current_value:
                raise MainnetReleaseAuthorizationError(f"authorization replay detected: {field}")

    return ValidatedMainnetReleaseAuthorization(
        authorization_id=authorization_id,
        authorization_digest=supplied_digest,
        request_digest=request_digest,
        release_manifest_sha256=manifest_digest,
        not_before=not_before,
        expires_at=expires_at,
    )


def _validate_exact_binding(
    binding: Mapping[str, Any], expected_binding: Mapping[str, Any]
) -> None:
    fields = (
        "repository",
        "source_commit_sha",
        "source_tree_sha",
        *BOUND_HEX_64_FIELDS,
        "constitution_revision_id",
    )
    for field in fields:
        if binding.get(field) != expected_binding.get(field):
            raise MainnetReleaseAuthorizationError(f"expected provenance mismatch: {field}")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MainnetReleaseAuthorizationError(f"{field} must be an object")
    return value


def _exact_fields(values: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(values)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise MainnetReleaseAuthorizationError(
            f"{field} fields are not canonical: {'; '.join(details)}"
        )


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise MainnetReleaseAuthorizationError(f"{field} is invalid")
    return value.strip()


def _hex(value: Any, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(
        char not in HEX_40 for char in value
    ):
        raise MainnetReleaseAuthorizationError(f"{field} must be lowercase hex-{length}")
    return value


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise MainnetReleaseAuthorizationError(f"{field} must be {expected!r}")


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MainnetReleaseAuthorizationError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise MainnetReleaseAuthorizationError(f"{field} is invalid") from exc
    return _utc(parsed, field)


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise MainnetReleaseAuthorizationError(f"{field} must use UTC")
    return value.astimezone(timezone.utc)


def _render_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
