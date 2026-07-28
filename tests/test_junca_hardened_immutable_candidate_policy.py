from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "junca_hardened_immutable_candidate_policy.py"
POLICY_PATH = ROOT / "config" / "junca_hardened_immutable_candidate_policy.json"

SPEC = importlib.util.spec_from_file_location("hardened_policy", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HardenedImmutableCandidatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_canonical_policy_is_accepted(self) -> None:
        outputs = MODULE.validate_policy(self.policy)
        self.assertEqual(
            outputs["minimum_hardened_main_commit"],
            "8ff509be3733cb1f6e55cb4c0d3af66d997678d1",
        )
        self.assertEqual(outputs["migration_run_id"], "30301559973")
        self.assertEqual(
            outputs["policy_sha256"],
            MODULE.canonical_policy_sha256(self.policy),
        )

    def test_old_pr145_candidate_is_retired_but_preserved(self) -> None:
        retired = self.policy["retired_candidates"][0]
        self.assertTrue(retired["preserve_for_audit"])
        self.assertFalse(retired["acceptance_eligible"])
        self.assertFalse(retired["foundation_resume_allowed"])
        with self.assertRaisesRegex(
            MODULE.HardenedCandidatePolicyError,
            "retired request digest",
        ):
            MODULE.reject_retired_request(
                {"request_sha256": retired["request_sha256"]},
                self.policy,
            )
        with self.assertRaisesRegex(
            MODULE.HardenedCandidatePolicyError,
            "retired AMI run",
        ):
            MODULE.reject_retired_request(
                {"ami_run_id": retired["ami_run_id"]},
                self.policy,
            )

    def test_incomplete_service_contract_is_rejected(self) -> None:
        changed = copy.deepcopy(self.policy)
        changed["required_runtime_contract"].remove("health-endpoints")
        changed["policy_sha256"] = MODULE.canonical_policy_sha256(changed)
        with self.assertRaisesRegex(
            MODULE.HardenedCandidatePolicyError,
            "runtime contract is incomplete",
        ):
            MODULE.validate_policy(changed)

    def test_parallel_or_multi_validator_apply_is_rejected(self) -> None:
        for key, value in (
            ("parallel_replacement_allowed", True),
            ("max_validator_replacements_per_apply", 2),
            ("terraform_destroy_allowed", True),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.policy)
                changed["rolling_release"][key] = value
                changed["policy_sha256"] = MODULE.canonical_policy_sha256(changed)
                with self.assertRaisesRegex(
                    MODULE.HardenedCandidatePolicyError,
                    "rolling release policy mismatch",
                ):
                    MODULE.validate_policy(changed)

    def test_activation_boundary_cannot_be_relaxed(self) -> None:
        changed = copy.deepcopy(self.policy)
        changed["boundaries"]["mainnet_activation_authorized"] = True
        changed["policy_sha256"] = MODULE.canonical_policy_sha256(changed)
        with self.assertRaisesRegex(
            MODULE.HardenedCandidatePolicyError,
            "safety boundary mismatch",
        ):
            MODULE.validate_policy(changed)

    def test_policy_digest_tampering_is_rejected(self) -> None:
        changed = copy.deepcopy(self.policy)
        changed["migration_binding"]["run_id"] = "30301559974"
        with self.assertRaisesRegex(
            MODULE.HardenedCandidatePolicyError,
            "policy_sha256 mismatch",
        ):
            MODULE.validate_policy(changed)


if __name__ == "__main__":
    unittest.main()
