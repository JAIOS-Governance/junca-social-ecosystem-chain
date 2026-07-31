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
POLICY_SCHEMA_VERSION = "junca-mainnet-approval-policy/v1"
REPLAY_DOMAIN = "junca-mainnet-controlled-activation/v1"
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
    "approval_policy_digest",
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
    approval_policy_digest: str
    approval_set_digest: str
    replay_domain: str
    not_before: datetime
    expires_at: datetime

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "authorization_id": self.authorization_id,
            "authorization_digest": self.authorization_digest,
            "request_digest": self.request_digest,
            "release_manifest_sha256": self.release_manifest_sha256,
            "approval_policy_digest": self.approval_policy_digest,
            "approval_set_digest": self.approval_set_digest,
            "replay_domain": self.replay_domain,
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
            "replay_domain",
            "environment",
            "decision",
            "binding",
            "approval",
            "reviews",
            "approval_set_digest",
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


def compute_approval_policy_digest(policy: Mapping[str, Any]) -> str:
    """Bind the immutable reviewer threshold, roles, identities, and keys."""

    return _domain_digest(b"JUNCA-MAINNET-APPROVAL-POLICY-V1\0", policy)


def compute_review_attestation_digest(
    review: Mapping[str, Any],
    binding: Mapping[str, Any],
    approval_policy_digest: str,
    replay_domain: str = REPLAY_DOMAIN,
) -> str:
    """Bind one authenticated review record to the exact release provenance."""

    material = {
        "replay_domain": replay_domain,
        "approval_policy_digest": approval_policy_digest,
        "binding": binding,
        "review": {key: value for key, value in review.items() if key != "attestation_digest"},
    }
    return _domain_digest(b"JUNCA-MAINNET-REVIEW-ATTESTATION-V1\0", material)


def compute_approval_set_digest(
    reviews: Iterable[Mapping[str, Any]],
    binding: Mapping[str, Any],
    approval_policy_digest: str,
    replay_domain: str = REPLAY_DOMAIN,
) -> str:
    """Bind the complete, order-independent approval set to release provenance."""

    normalized = sorted(
        (dict(review) for review in reviews),
        key=lambda item: (str(item.get("reviewer_identity")), str(item.get("review_id"))),
    )
    material = {
        "replay_domain": replay_domain,
        "approval_policy_digest": approval_policy_digest,
        "binding": binding,
        "reviews": normalized,
    }
    return _domain_digest(b"JUNCA-MAINNET-APPROVAL-SET-V1\0", material)


def compute_final_approval_attestation_digest(
    approval: Mapping[str, Any],
    binding: Mapping[str, Any],
    approval_policy_digest: str,
    approval_set_digest: str,
    replay_domain: str = REPLAY_DOMAIN,
) -> str:
    """Bind final approval to the immutable policy and complete review set."""

    material = {
        "replay_domain": replay_domain,
        "approval_policy_digest": approval_policy_digest,
        "approval_set_digest": approval_set_digest,
        "binding": binding,
        "approval": {
            key: value for key, value in approval.items() if key != "attestation_digest"
        },
    }
    return _domain_digest(b"JUNCA-MAINNET-FINAL-APPROVAL-V1\0", material)


def validate_mainnet_release_authorization(
    envelope: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
    approval_policy: Mapping[str, Any],
    consumed_records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> ValidatedMainnetReleaseAuthorization:
    """Validate exact provenance, freshness, review, safety, and replay controls."""

    if not isinstance(envelope, Mapping):
        raise MainnetReleaseAuthorizationError("authorization envelope must be an object")
    if not isinstance(expected_binding, Mapping):
        raise MainnetReleaseAuthorizationError("expected binding must be an object")
    if not isinstance(approval_policy, Mapping):
        raise MainnetReleaseAuthorizationError("approval policy must be an object")
    _exact_fields(
        expected_binding,
        {
            "repository",
            "source_commit_sha",
            "source_tree_sha",
            *BOUND_HEX_64_FIELDS,
            "constitution_revision_id",
        },
        "expected binding",
    )
    policy_digest, policy_approver, trusted_reviewers, threshold, required_roles = (
        _validate_approval_policy(approval_policy)
    )
    current = _utc(now or datetime.now(timezone.utc), "now")

    _exact_fields(
        envelope,
        {
            "schema_version",
            "authorization_id",
            "replay_domain",
            "environment",
            "decision",
            "binding",
            "approval",
            "reviews",
            "approval_set_digest",
            "window",
            "safety_boundaries",
            "authorization_digest",
        },
        "authorization envelope",
    )

    _require(envelope, "schema_version", SCHEMA_VERSION)
    _require(envelope, "replay_domain", REPLAY_DOMAIN)
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
    if binding["approval_policy_digest"] != policy_digest:
        raise MainnetReleaseAuthorizationError("approval policy digest mismatch")

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
        {
            "approver_identity",
            "approver_role",
            "approver_key_fingerprint",
            "approval_policy_digest",
            "approval_set_digest",
            "approved_at",
            "attestation_digest",
        },
        "approval",
    )
    approver = _text(approval.get("approver_identity"), "approval.approver_identity", 200)
    _require(approval, "approver_role", policy_approver["role"])
    _require(approval, "approver_key_fingerprint", policy_approver["key_fingerprint"])
    _require(approval, "approval_policy_digest", policy_digest)
    approved_at = _time(approval.get("approved_at"), "approval.approved_at")
    if approved_at > not_before:
        raise MainnetReleaseAuthorizationError("approval postdates authorization window")
    if not_before - approved_at > MAX_APPROVAL_AGE:
        raise MainnetReleaseAuthorizationError("approval evidence is older than 24 hours")
    if approver != policy_approver["identity"]:
        raise MainnetReleaseAuthorizationError("approver identity mismatch")

    reviews = envelope.get("reviews")
    if not isinstance(reviews, list) or len(reviews) < threshold:
        raise MainnetReleaseAuthorizationError("approval threshold is not satisfied")
    reviewer_ids: set[str] = set()
    review_ids: set[str] = set()
    reviewer_roles: set[str] = set()
    reviewer_keys: set[str] = set()
    for index, value in enumerate(reviews):
        review = _mapping(value, f"reviews[{index}]")
        _exact_fields(
            review,
            {
                "reviewer_identity",
                "reviewer_role",
                "reviewer_key_fingerprint",
                "review_id",
                "reviewed_commit_sha",
                "reviewed_tree_sha",
                "verdict",
                "submitted_at",
                "approval_policy_digest",
                "attestation_digest",
            },
            f"reviews[{index}]",
        )
        reviewer = _text(
            review.get("reviewer_identity"), f"reviews[{index}].reviewer_identity", 200
        )
        review_id = _text(review.get("review_id"), f"reviews[{index}].review_id", 200)
        reviewer_role = _text(
            review.get("reviewer_role"), f"reviews[{index}].reviewer_role", 200
        )
        reviewer_key = _hex(
            review.get("reviewer_key_fingerprint"),
            64,
            f"reviews[{index}].reviewer_key_fingerprint",
        )
        if reviewer == approver:
            raise MainnetReleaseAuthorizationError("approver cannot be an independent reviewer")
        if (
            reviewer in reviewer_ids
            or review_id in review_ids
            or reviewer_role in reviewer_roles
            or reviewer_key in reviewer_keys
        ):
            raise MainnetReleaseAuthorizationError(
                "review identities, roles, keys, and IDs must be unique"
            )
        reviewer_ids.add(reviewer)
        review_ids.add(review_id)
        reviewer_roles.add(reviewer_role)
        reviewer_keys.add(reviewer_key)
        trusted = trusted_reviewers.get(reviewer)
        if trusted is None:
            raise MainnetReleaseAuthorizationError("reviewer is not registered by policy")
        if reviewer_role != trusted["role"] or reviewer_key != trusted["key_fingerprint"]:
            raise MainnetReleaseAuthorizationError("reviewer role or key mismatch")
        _require(review, "approval_policy_digest", policy_digest)
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
        expected_review_digest = compute_review_attestation_digest(
            review, binding, policy_digest
        )
        if review.get("attestation_digest") != expected_review_digest:
            raise MainnetReleaseAuthorizationError("review attestation digest mismatch")

    if not required_roles.issubset(reviewer_roles):
        raise MainnetReleaseAuthorizationError("required reviewer roles are missing")
    supplied_approval_set_digest = _hex(
        envelope.get("approval_set_digest"), 64, "approval_set_digest"
    )
    expected_approval_set_digest = compute_approval_set_digest(
        reviews, binding, policy_digest
    )
    if supplied_approval_set_digest != expected_approval_set_digest:
        raise MainnetReleaseAuthorizationError("approval-set digest mismatch")
    _require(approval, "approval_set_digest", supplied_approval_set_digest)
    expected_final_approval = compute_final_approval_attestation_digest(
        approval,
        binding,
        policy_digest,
        supplied_approval_set_digest,
    )
    if approval.get("attestation_digest") != expected_final_approval:
        raise MainnetReleaseAuthorizationError("final approval attestation digest mismatch")

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
            ("approval_set_digest", supplied_approval_set_digest),
        )
        for field, current_value in comparisons:
            if record.get(field) == current_value:
                if record.get("replay_domain") != REPLAY_DOMAIN:
                    raise MainnetReleaseAuthorizationError(
                        f"cross-domain authorization replay detected: {field}"
                    )
                raise MainnetReleaseAuthorizationError(f"authorization replay detected: {field}")

    return ValidatedMainnetReleaseAuthorization(
        authorization_id=authorization_id,
        authorization_digest=supplied_digest,
        request_digest=request_digest,
        release_manifest_sha256=manifest_digest,
        approval_policy_digest=policy_digest,
        approval_set_digest=supplied_approval_set_digest,
        replay_domain=REPLAY_DOMAIN,
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


def _validate_approval_policy(
    policy: Mapping[str, Any],
) -> tuple[str, dict[str, str], dict[str, dict[str, str]], int, set[str]]:
    _exact_fields(
        policy,
        {
            "schema_version",
            "policy_id",
            "threshold",
            "required_roles",
            "approver",
            "reviewers",
            "separation_of_duties",
        },
        "approval policy",
    )
    _require(policy, "schema_version", POLICY_SCHEMA_VERSION)
    _text(policy.get("policy_id"), "approval policy.policy_id", 200)
    threshold = policy.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 2:
        raise MainnetReleaseAuthorizationError("approval policy threshold must be at least two")

    roles_value = policy.get("required_roles")
    if not isinstance(roles_value, list) or not all(
        isinstance(role, str) and role.strip() for role in roles_value
    ):
        raise MainnetReleaseAuthorizationError("approval policy required roles are invalid")
    required_roles = {str(role).strip() for role in roles_value}
    if len(required_roles) != len(roles_value) or len(required_roles) > threshold:
        raise MainnetReleaseAuthorizationError(
            "approval policy required roles must be unique and fit the threshold"
        )

    approver_value = _mapping(policy.get("approver"), "approval policy.approver")
    _exact_fields(
        approver_value,
        {"identity", "role", "key_fingerprint"},
        "approval policy.approver",
    )
    approver = {
        "identity": _text(
            approver_value.get("identity"), "approval policy.approver.identity", 200
        ),
        "role": _text(approver_value.get("role"), "approval policy.approver.role", 200),
        "key_fingerprint": _hex(
            approver_value.get("key_fingerprint"),
            64,
            "approval policy.approver.key_fingerprint",
        ),
    }
    if approver["role"] != "Founder / Chairman / CEO":
        raise MainnetReleaseAuthorizationError("approval policy approver role is invalid")

    reviewers_value = policy.get("reviewers")
    if not isinstance(reviewers_value, list) or len(reviewers_value) < threshold:
        raise MainnetReleaseAuthorizationError("approval policy has insufficient reviewers")
    reviewers: dict[str, dict[str, str]] = {}
    registered_roles: set[str] = set()
    registered_keys: set[str] = {approver["key_fingerprint"]}
    for index, item in enumerate(reviewers_value):
        reviewer = _mapping(item, f"approval policy.reviewers[{index}]")
        _exact_fields(
            reviewer,
            {"identity", "role", "key_fingerprint"},
            f"approval policy.reviewers[{index}]",
        )
        identity = _text(
            reviewer.get("identity"), f"approval policy.reviewers[{index}].identity", 200
        )
        role = _text(reviewer.get("role"), f"approval policy.reviewers[{index}].role", 200)
        key = _hex(
            reviewer.get("key_fingerprint"),
            64,
            f"approval policy.reviewers[{index}].key_fingerprint",
        )
        if identity == approver["identity"]:
            raise MainnetReleaseAuthorizationError(
                "approval policy violates approver/reviewer separation"
            )
        if identity in reviewers or role in registered_roles or key in registered_keys:
            raise MainnetReleaseAuthorizationError(
                "approval policy reviewer identities, roles, and keys must be unique"
            )
        reviewers[identity] = {"role": role, "key_fingerprint": key}
        registered_roles.add(role)
        registered_keys.add(key)
    if not required_roles.issubset(registered_roles):
        raise MainnetReleaseAuthorizationError(
            "approval policy required roles are not registered"
        )

    separation = _mapping(
        policy.get("separation_of_duties"), "approval policy.separation_of_duties"
    )
    _exact_fields(
        separation,
        {
            "approver_may_review",
            "distinct_reviewer_identities",
            "distinct_reviewer_roles",
            "distinct_reviewer_keys",
        },
        "approval policy.separation_of_duties",
    )
    _require(separation, "approver_may_review", False)
    _require(separation, "distinct_reviewer_identities", True)
    _require(separation, "distinct_reviewer_roles", True)
    _require(separation, "distinct_reviewer_keys", True)

    return (
        compute_approval_policy_digest(policy),
        approver,
        reviewers,
        threshold,
        required_roles,
    )


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


def _domain_digest(domain: bytes, value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()
