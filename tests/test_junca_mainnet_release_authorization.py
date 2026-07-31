from __future__ import annotations

from datetime import datetime, timezone
import unittest

from jaios.social_ecosystem_chain import (
    MainnetReleaseAuthorizationError,
    compute_approval_policy_digest,
    compute_approval_set_digest,
    compute_authorization_digest,
    compute_final_approval_attestation_digest,
    compute_review_attestation_digest,
    validate_mainnet_release_authorization,
)
from scripts.junca_mainnet_release_authorization_gate import _parse_now


NOW = datetime(2026, 7, 31, 13, 10, tzinfo=timezone.utc)


def authorization():
    policy = {
        "schema_version": "junca-mainnet-approval-policy/v1",
        "policy_id": "mainnet-controlled-activation-2026-07",
        "threshold": 2,
        "required_roles": ["protocol-reviewer", "security-release-reviewer"],
        "approver": {
            "identity": "verified-ceo-identity",
            "role": "Founder / Chairman / CEO",
            "key_fingerprint": "a" * 64,
        },
        "reviewers": [
            {
                "identity": "protocol-review-team",
                "role": "protocol-reviewer",
                "key_fingerprint": "b" * 64,
            },
            {
                "identity": "security-release-team",
                "role": "security-release-reviewer",
                "key_fingerprint": "c" * 64,
            },
        ],
        "separation_of_duties": {
            "approver_may_review": False,
            "distinct_reviewer_identities": True,
            "distinct_reviewer_roles": True,
            "distinct_reviewer_keys": True,
        },
    }
    policy_digest = compute_approval_policy_digest(policy)
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
        "approval_policy_digest": policy_digest,
    }
    value = {
        "schema_version": "junca-mainnet-release-authorization/v1",
        "authorization_id": "mainnet-release-20260731-001",
        "replay_domain": "junca-mainnet-controlled-activation/v1",
        "environment": "mainnet",
        "decision": "authorized",
        "binding": binding,
        "approval": {
            "approver_identity": "verified-ceo-identity",
            "approver_role": "Founder / Chairman / CEO",
            "approver_key_fingerprint": "a" * 64,
            "approval_policy_digest": policy_digest,
            "approved_at": "2026-07-31T13:05:00Z",
        },
        "reviews": [
            {
                "reviewer_identity": "protocol-review-team",
                "reviewer_role": "protocol-reviewer",
                "reviewer_key_fingerprint": "b" * 64,
                "review_id": "review-1001",
                "reviewed_commit_sha": "1" * 40,
                "reviewed_tree_sha": "2" * 40,
                "verdict": "approved",
                "submitted_at": "2026-07-31T12:55:00Z",
                "approval_policy_digest": policy_digest,
            },
            {
                "reviewer_identity": "security-release-team",
                "reviewer_role": "security-release-reviewer",
                "reviewer_key_fingerprint": "c" * 64,
                "review_id": "review-1002",
                "reviewed_commit_sha": "1" * 40,
                "reviewed_tree_sha": "2" * 40,
                "verdict": "approved",
                "submitted_at": "2026-07-31T13:00:00Z",
                "approval_policy_digest": policy_digest,
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
    for review in value["reviews"]:
        review["attestation_digest"] = compute_review_attestation_digest(
            review, binding, policy_digest
        )
    approval_set_digest = compute_approval_set_digest(
        value["reviews"], binding, policy_digest
    )
    value["approval_set_digest"] = approval_set_digest
    value["approval"]["approval_set_digest"] = approval_set_digest
    value["approval"]["attestation_digest"] = compute_final_approval_attestation_digest(
        value["approval"], binding, policy_digest, approval_set_digest
    )
    value["authorization_digest"] = compute_authorization_digest(value)
    expected = dict(binding)
    return value, expected, policy


class MainnetReleaseAuthorizationTests(unittest.TestCase):
    def validate(self, value, expected, policy, records=None, now=NOW):
        return validate_mainnet_release_authorization(
            value, expected, policy, records or [], now=now
        )

    def test_exact_fresh_unconsumed_evidence_is_validated_without_activation(self):
        value, expected, policy = authorization()
        result = self.validate(value, expected, policy)

        self.assertEqual(result.authorization_digest, value["authorization_digest"])
        evidence = result.as_evidence()
        self.assertEqual(evidence["approval_set_digest"], value["approval_set_digest"])
        self.assertTrue(evidence["authorization_evidence_valid"])
        self.assertFalse(evidence["activation_executed"])
        self.assertFalse(evidence["mainnet_changed"])

    def test_tampered_digest_and_provenance_are_rejected(self):
        value, expected, policy = authorization()
        value["binding"]["artifact_sha256"] = "9" * 64
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "expected provenance"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["authorization_digest"] = "f" * 64
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "digest mismatch"):
            self.validate(value, expected, policy)

    def test_review_must_bind_exact_commit_tree_and_attestation(self):
        value, expected, policy = authorization()
        value["reviews"][1]["reviewed_tree_sha"] = "d" * 40
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "review tree provenance"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["reviews"][1]["attestation_digest"] = "d" * 64
        value["approval_set_digest"] = compute_approval_set_digest(
            value["reviews"], value["binding"], value["binding"]["approval_policy_digest"]
        )
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "review attestation"):
            self.validate(value, expected, policy)

    def test_unregistered_or_string_only_reviewer_is_rejected(self):
        value, expected, policy = authorization()
        value["reviews"][1]["reviewer_identity"] = "invented-review-team"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not registered"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["reviews"][1]["reviewer_key_fingerprint"] = "e" * 64
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "role or key mismatch"):
            self.validate(value, expected, policy)

    def test_duplicate_identity_role_key_or_approver_review_is_rejected(self):
        for field in ("reviewer_identity", "reviewer_role", "reviewer_key_fingerprint"):
            value, expected, policy = authorization()
            value["reviews"][1][field] = value["reviews"][0][field]
            value["authorization_digest"] = compute_authorization_digest(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                MainnetReleaseAuthorizationError, "must be unique"
            ):
                self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["reviews"][0]["reviewer_identity"] = "verified-ceo-identity"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "cannot be"):
            self.validate(value, expected, policy)

    def test_threshold_and_required_roles_are_enforced(self):
        value, expected, policy = authorization()
        value["reviews"] = value["reviews"][:1]
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "threshold"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        policy["required_roles"] = ["protocol-reviewer", "release-auditor"]
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not registered"):
            self.validate(value, expected, policy)

    def test_policy_digest_and_final_approval_set_binding_are_immutable(self):
        value, expected, policy = authorization()
        policy["threshold"] = 3
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "insufficient reviewers"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        policy["policy_id"] = "replacement-policy"
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "policy digest mismatch"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["approval_set_digest"] = "e" * 64
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "approval-set digest"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["approval"]["attestation_digest"] = "e" * 64
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "final approval"):
            self.validate(value, expected, policy)

    def test_policy_separation_and_key_uniqueness_cannot_be_weakened(self):
        value, expected, policy = authorization()
        policy["separation_of_duties"]["distinct_reviewer_keys"] = False
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "must be True"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        policy["reviewers"][1]["key_fingerprint"] = policy["reviewers"][0][
            "key_fingerprint"
        ]
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "must be unique"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        policy["reviewers"][0]["identity"] = policy["approver"]["identity"]
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "separation"):
            self.validate(value, expected, policy)

    def test_approval_set_digest_is_order_independent(self):
        value, _, _ = authorization()
        policy_digest = value["binding"]["approval_policy_digest"]
        forward = compute_approval_set_digest(
            value["reviews"], value["binding"], policy_digest
        )
        reverse = compute_approval_set_digest(
            reversed(value["reviews"]), value["binding"], policy_digest
        )
        self.assertEqual(forward, reverse)

    def test_expired_future_and_overwide_windows_are_rejected(self):
        value, expected, policy = authorization()
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "expired"):
            self.validate(
                value,
                expected,
                policy,
                now=datetime(2026, 7, 31, 13, 16, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not yet"):
            self.validate(
                value,
                expected,
                policy,
                now=datetime(2026, 7, 31, 13, 5, tzinfo=timezone.utc),
            )

        value["window"]["expires_at"] = "2026-07-31T13:30:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "exceeds"):
            self.validate(value, expected, policy)

    def test_stale_approval_and_reviews_are_rejected(self):
        value, expected, policy = authorization()
        value["approval"]["approved_at"] = "2026-07-30T12:00:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "older than 24"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["reviews"][0]["submitted_at"] = "2026-07-28T12:54:00Z"
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "older than 72"):
            self.validate(value, expected, policy)

    def test_each_replay_identity_and_cross_domain_reuse_fails_closed(self):
        value, expected, policy = authorization()
        fields = (
            "authorization_id",
            "authorization_digest",
            "request_digest",
            "release_manifest_sha256",
            "approval_set_digest",
        )
        for field in fields:
            current = value.get(field, value["binding"].get(field))
            record = {field: current, "replay_domain": value["replay_domain"]}
            with self.subTest(field=field), self.assertRaisesRegex(
                MainnetReleaseAuthorizationError, f"replay detected: {field}"
            ):
                self.validate(value, expected, policy, [record])

        record = {
            "request_digest": value["binding"]["request_digest"],
            "replay_domain": "other-activation-domain/v1",
        }
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "cross-domain"):
            self.validate(value, expected, policy, [record])

    def test_safety_boundaries_cannot_be_promoted_by_evidence(self):
        for field in (
            "mainnet_changed",
            "assets_moved",
            "bridge_activated",
            "mainnet_activation_authorized",
        ):
            value, expected, policy = authorization()
            value["safety_boundaries"][field] = True
            value["authorization_digest"] = compute_authorization_digest(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                MainnetReleaseAuthorizationError, field
            ):
                self.validate(value, expected, policy)

    def test_unknown_top_level_and_nested_fields_are_rejected(self):
        value, expected, policy = authorization()
        value["activation_executed"] = True
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "not canonical"):
            self.validate(value, expected, policy)

        value, expected, policy = authorization()
        value["binding"]["unreviewed_artifact"] = "f" * 64
        value["authorization_digest"] = compute_authorization_digest(value)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "unknown"):
            self.validate(value, expected, policy)

    def test_cli_now_override_is_strictly_utc(self):
        self.assertEqual(_parse_now("2026-07-31T13:10:00Z"), NOW)
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "RFC3339 UTC"):
            _parse_now("2026-07-31T13:10:00+09:00")
        with self.assertRaisesRegex(MainnetReleaseAuthorizationError, "invalid"):
            _parse_now("not-a-timeZ")


if __name__ == "__main__":
    unittest.main()
