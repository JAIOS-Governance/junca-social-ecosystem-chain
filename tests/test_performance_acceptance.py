from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.performance_acceptance import (
    MainnetPerformanceTargets,
    PerformanceObservation,
    evaluate_performance,
)


class PerformanceAcceptanceTests(unittest.TestCase):
    def _observation(self, **overrides) -> PerformanceObservation:
        values = {
            "sustained_tps": 2_100,
            "burst_tps": 5_200,
            "finality_p95_seconds": 5.5,
            "rpc_read_p95_ms": 220,
            "availability_percent": 99.97,
            "error_percent": 0.05,
            "observation_hours": 24,
            "validator_count": 9,
            "failure_domains": 5,
            "load_test_passed": True,
            "chaos_test_passed": True,
            "state_growth_test_passed": True,
            "upgrade_rehearsal_passed": True,
        }
        values.update(overrides)
        return PerformanceObservation(**values)

    def test_complete_evidence_passes(self) -> None:
        result = evaluate_performance(self._observation())

        self.assertTrue(result["accepted"])
        self.assertTrue(result["public_slo_claim_allowed"])
        self.assertEqual(result["failed_checks"], [])

    def test_short_soak_blocks_acceptance(self) -> None:
        result = evaluate_performance(self._observation(observation_hours=23.9))

        self.assertFalse(result["accepted"])
        self.assertIn("observation_duration", result["failed_checks"])
        self.assertFalse(result["public_slo_claim_allowed"])

    def test_chaos_and_upgrade_rehearsal_are_mandatory(self) -> None:
        result = evaluate_performance(
            self._observation(
                chaos_test_passed=False,
                upgrade_rehearsal_passed=False,
            )
        )

        self.assertFalse(result["accepted"])
        self.assertIn("chaos_test", result["failed_checks"])
        self.assertIn("upgrade_rehearsal", result["failed_checks"])

    def test_validator_scale_and_failure_domains_are_mandatory(self) -> None:
        result = evaluate_performance(
            self._observation(validator_count=3, failure_domains=2)
        )

        self.assertFalse(result["accepted"])
        self.assertIn("validator_scale", result["failed_checks"])
        self.assertIn("failure_domains", result["failed_checks"])

    def test_custom_targets_are_enforced(self) -> None:
        targets = MainnetPerformanceTargets(
            sustained_tps=3_000,
            burst_tps=6_000,
            finality_p95_seconds=4,
            rpc_read_p95_ms=150,
            availability_percent=99.99,
            maximum_error_percent=0.01,
            minimum_observation_hours=48,
        )
        result = evaluate_performance(self._observation(), targets=targets)

        self.assertFalse(result["accepted"])
        self.assertGreater(len(result["failed_checks"]), 1)

    def test_evidence_preserves_activation_boundary(self) -> None:
        result = evaluate_performance(self._observation())

        self.assertEqual(result["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(result["mainnet_changed"])
        self.assertFalse(result["assets_moved"])
        self.assertFalse(result["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
