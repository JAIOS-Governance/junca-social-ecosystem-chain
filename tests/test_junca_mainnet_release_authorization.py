from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from jaios.social_ecosystem_chain import (
    MainnetReleaseAuthorizationError,
    compute_authorization_digest,
    validate_mainnet_release_authorization,
)


NOW = datetime(2026, 7, 31, 13, 10, tzinfo=timezone.utc)


def authorization():
    binding = {
        "repository": "JAIOS-Governance/junca-social-ecosystem-chain",
        "source_commit_sha": "1" * 40,
        "source_tree_sha": "2" * 40,
        "release_manifest_sha256": "3" * 64,
        "request_digest": "4" * 64,
        "artifact_sha256": "5" * 64,
        "sbom_sha256": "6" * 64,
        "genesis_sha256": "7" * 64,
        "constitution_revision_id": "drive-revision-20260731",
        "constitution_sha256": "8" * 64,
    }
    value = {
        "schema_version": "junca-mainnet-release-authorization/v1",
        "authorization_id": "mainnet-release-20260731-001",
        "environment": "mainnet",
        "decision": "authorized",
        "binding": binding,
        "approval": {
            "approver_identity": "verified-ceo-identity",
            "approver_role": "Founder / Chairman / CEO",
            "approved_at": "2026-07-31T13:05:00Z",
        },
        "reviews": [
            {
                "reviewer_identity": "protocol-review-team",
                "review_id": "review-1001",
                "reviewed_commit_sha": "1" * 40,
                "reviewed_tree_sha": "2" * 40,
                "verdict": "approved",
                "submitted_at": "2026-07-31T12:55:00Z",
            },
            {
                "reviewer_identity": "security-release-team",
                "review_id": "review-1002",
                "reviewed_commit_sha": "1" * 40,
                "reviewed_tree_sha": "2" * 40,
                "verdict": "approved",
                "submitted_at": "2026-07-31T13:00:00Z",
            },
        ],
        "window": {
            "not_before": "2026-07-31T13:06:00Z",
            "expires_at": "2026-07-31T13:15:00Z",
        },
        "safety_boundaries": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        },
    }
    value["authorization_digest"] = compute_authorization_digest(value)
    expected = {**binding, "approver_identity": "verified-ceo-identity"}
    return value, expected


class MainnetReleaseAuthorizationTests(unittest.TestCase):
    def test_exact_fresh_unconsumed_evidence_is_validated_without_activation(self):
        value, expected = authorization()
        result = validate_mainnet_release_authorization(value, expected, [], now=NOW)

        self.assertEqual(result.authorization_digest, value["authorization_digest"])
        evidence = result.as_evidence()
        self.assertTrue(evidence["authorization_evidence_valid"])
        self.assertFalse(evidence["activation_executed"])
        self.assertFalse(evidence["mainnet_changed"])

    def test_tampered_digest_is_rejected(self):
        value, expected = authorization()
        value["binding"]["artifact_sha256"] = "9" * 64
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "expected provenance"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

        value, expected = authorization()
        value["authorization_digest"] = "f" * 64
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "digest mismatch"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_review_must_bind_exact_commit_and_tree(self):
        value, expected = authorization()
        value["reviews"][1]["reviewed_tree_sha"] = "a" * 40
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "review tree provenance"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_duplicate_or_approver_reviewers_are_rejected(self):
        value, expected = authorization()
        value["reviews"][1]["reviewer_identity"] = value["reviews"][0]["reviewer_identity"]
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "must be unique"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

        value, expected = authorization()
        value["reviews"][0]["reviewer_identity"] = "verified-ceo-identity"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "cannot be"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_expired_future_and_overwide_windows_are_rejected(self):
        value, expected = authorization()
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "expired"):
            validate_mainnet_release_authorization(
                value,
                expected,
                [],
                now=datetime(2026, 7, 31, 13, 16, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not yet"):
            validate_mainnet_release_authorization(
                value,
                expected,
                [],
                now=datetime(2026, 7, 31, 13, 5, tzinfo=timezone.utc),
            )

        value["window"]["expires_at"] = "2026-07-31T13:30:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "exceeds"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_stale_approval_and_reviews_are_rejected(self):
        value, expected = authorization()
        value["approval"]["approved_at"] = "2026-07-30T12:00:00Z"
        value["reviews"][0]["submitted_at"] = "2026-07-30T11:00:00Z"
        value["reviews"][1]["submitted_at"] = "2026-07-30T11:30:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "older than 24"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

        value, expected = authorization()
        value["reviews"][0]["submitted_at"] = "2026-07-28T12:54:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "older than 72"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

        value, expected = authorization()
        value["reviews"][0]["submitted_at"] = "2026-07-31T13:05:30Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "postdates"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_each_replay_identity_fails_closed(self):
        value, expected = authorization()
        for field in (
            "authorization_id",
            "authorization_digest",
            "request_digest",
            "release_manifest_sha256",
        ):
            with self.subTest(field=field):
                record = {field: (
                    value[field]
                    if field in value
                    else value["binding"][field]
                )}
                with self.assertRaisesRegex(
                    MainnetReleaseAuthorizationError, f"replay detected: {field}"
                ):
                    validate_mainnet_release_authorization(value, expected, [record], now=NOW)

    def test_safety_boundaries_cannot_be_promoted_by_evidence(self):
        for field in (
            "mainnet_changed",
            "assets_moved",
            "bridge_activated",
            "mainnet_activation_authorized",
        ):
            value, expected = authorization()
            value["safety_boundaries"][field] = True
            value["authorization_digest"] = compute_authorization_digest(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                MainnetReleaseAuthorizationError, field
            ):
                validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_expected_approver_mismatch_is_rejected(self):
        value, expected = authorization()
        expected = deepcopy(expected)
        expected["approver_identity"] = "different-verified-identity"
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "approver identity"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

    def test_unknown_top_level_and_nested_fields_are_rejected(self):
        value, expected = authorization()
        value["activation_executed"] = True
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not canonical"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)

        value, expected = authorization()
        value["binding"]["unreviewed_artifact"] = "f" * 64
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "unknown"):
            validate_mainnet_release_authorization(value, expected, [], now=NOW)


if __name__ == "__main__":
    unittest.main()
