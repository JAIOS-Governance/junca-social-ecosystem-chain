import unittest

from jaios.social_ecosystem_chain.mainnet_readiness import (
    MainnetReadinessError,
    REQUIRED_GATES,
    SCHEMA_VERSION,
    evaluate_mainnet_readiness,
)


def evidence(*, passed: bool = False):
    return {
        "schema_version": SCHEMA_VERSION,
        "source_commit": "a" * 40,
        "gates": {name: passed for name in REQUIRED_GATES},
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class MainnetReadinessTests(unittest.TestCase):
    def test_current_process_is_blocked_with_explicit_missing_gates(self):
        result = evaluate_mainnet_readiness(evidence())
        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.missing_gates, REQUIRED_GATES)
        self.assertFalse(result.as_evidence()["mainnet_changed"])

    def test_all_gates_allow_candidate_stage_only(self):
        result = evaluate_mainnet_readiness(evidence(passed=True))
        result.assert_candidate_mainnet_ready()
        self.assertEqual(result.state, "ready")
        self.assertEqual(result.as_evidence()["release_stage"], "candidate-mainnet")
        self.assertFalse(result.as_evidence()["assets_moved"])

    def test_rejects_skipped_or_renamed_gate(self):
        value = evidence()
        value["gates"].pop("independent_security_review")
        with self.assertRaisesRegex(MainnetReadinessError, "gate set mismatch"):
            evaluate_mainnet_readiness(value)

    def test_rejects_asset_bridge_or_direct_mainnet_change(self):
        for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
            with self.subTest(boundary=boundary):
                value = evidence(passed=True)
                value[boundary] = True
                with self.assertRaises(MainnetReadinessError):
                    evaluate_mainnet_readiness(value)

    def test_rejects_non_boolean_gate(self):
        value = evidence()
        value["gates"]["sustained_finality"] = "PASS"
        with self.assertRaisesRegex(MainnetReadinessError, "must be boolean"):
            evaluate_mainnet_readiness(value)


if __name__ == "__main__":
    unittest.main()
