from __future__ import annotations

import unittest

from scripts.observability.junca_metrics_exporter import (
    MetricsError,
    endpoint_assignments,
    render_metrics,
)


class JuncaMetricsExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshots = {
            validator_id: {
                "status": "healthy",
                "validator_id": validator_id,
                "head_height": 8,
                "peer_count": 2,
                "consensus": {
                    "authenticated_vote_count": 3,
                    "required_vote_count": 3,
                    "last_certificate_hash": "0x" + "a" * 64,
                },
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            }
            for validator_id in ("validator-01", "validator-02", "validator-03")
        }

    def test_renders_converged_validator_metrics(self) -> None:
        metrics = render_metrics(self.snapshots, observed_at=123.5)
        self.assertIn('junca_validator_up{validator="validator-01"} 1', metrics)
        self.assertIn("junca_network_finalized_height_min 8", metrics)
        self.assertIn("junca_network_finalized_height_max 8", metrics)
        self.assertIn("junca_network_height_divergence 0", metrics)
        self.assertIn("junca_network_certificate_converged 1", metrics)
        self.assertNotIn("arn:aws:kms", metrics)

    def test_detects_height_and_certificate_divergence(self) -> None:
        self.snapshots["validator-03"]["head_height"] = 7
        self.snapshots["validator-03"]["consensus"]["last_certificate_hash"] = (
            "0x" + "b" * 64
        )
        metrics = render_metrics(self.snapshots, observed_at=123.5)
        self.assertIn("junca_network_height_divergence 1", metrics)
        self.assertIn("junca_network_certificate_converged 0", metrics)

    def test_recovery_state_is_exposed_without_changing_safety(self) -> None:
        self.snapshots["validator-02"]["status"] = "recovery_required"
        metrics = render_metrics(self.snapshots, observed_at=123.5)
        self.assertIn(
            'junca_validator_recovery_required{validator="validator-02"} 1',
            metrics,
        )
        self.assertIn(
            'junca_network_safety_boundary{boundary="mainnet_changed_false"} 1',
            metrics,
        )

    def test_rejects_missing_validator_identity(self) -> None:
        del self.snapshots["validator-01"]["validator_id"]
        with self.assertRaisesRegex(MetricsError, "identity"):
            render_metrics(self.snapshots, observed_at=123.5)

    def test_requires_exactly_three_endpoint_assignments(self) -> None:
        value = endpoint_assignments(
            "validator-01=http://one/health,"
            "validator-02=http://two/health,"
            "validator-03=http://three/health"
        )
        self.assertEqual(len(value), 3)
        with self.assertRaisesRegex(MetricsError, "exactly three"):
            endpoint_assignments("validator-01=http://one/health")


if __name__ == "__main__":
    unittest.main()
