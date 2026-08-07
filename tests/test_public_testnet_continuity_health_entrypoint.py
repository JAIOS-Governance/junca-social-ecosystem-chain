from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "ops"
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

health_entrypoint = importlib.import_module(
    "public_testnet_continuity_health_entrypoint"
)
compatibility = health_entrypoint.compatibility
continuity = health_entrypoint.continuity


EXPLORER = {
    "status": "ready",
    "read_only": True,
    "finalized_only": True,
    "network": {
        "chain_id_decimal": 20260723,
        "peer_count": 2,
    },
    "head": {
        "height": 15010,
        "hash": "0x" + "12" * 32,
        "timestamp": 1786064010,
        "certificate_hash": "0x" + "34" * 32,
        "signed_power": 3,
        "total_power": 3,
    },
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}

HEALTH = {
    "status": "healthy",
    "read_only": True,
    "validator": {
        "head_height": 15010,
        "head_hash": "0x" + "12" * 32,
    },
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}


class HealthProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        compatibility._cached_explorer_payload = dict(EXPLORER)
        compatibility._timestamp_fallback_used = False

    def tearDown(self) -> None:
        compatibility._cached_explorer_payload = None
        compatibility._timestamp_fallback_used = False

    def test_projects_health_anchor_with_explorer_network_evidence(self) -> None:
        snapshot = health_entrypoint._health_projection_normalize_snapshot(
            HEALTH, source="operational_api", require_safety=True
        )
        self.assertEqual(snapshot.chain_id, 20260723)
        self.assertEqual(snapshot.finalized_height, 15010)
        self.assertEqual(snapshot.authenticated_peer_count, 2)
        self.assertEqual(snapshot.finalized_timestamp, 1786064010)
        self.assertEqual(snapshot.finalized_hash, "0x" + "12" * 32)
        self.assertEqual(snapshot.signed_power, 3)
        self.assertEqual(snapshot.total_power, 3)

    def test_rejects_health_explorer_height_divergence(self) -> None:
        health = {**HEALTH, "validator": {**HEALTH["validator"], "head_height": 15009}}
        with self.assertRaisesRegex(
            continuity.ContinuityError, "finalized heights diverge"
        ):
            health_entrypoint._health_projection_normalize_snapshot(
                health, source="operational_api", require_safety=True
            )

    def test_rejects_missing_independent_health_anchor(self) -> None:
        health = {key: value for key, value in HEALTH.items() if key != "validator"}
        with self.assertRaisesRegex(
            continuity.ContinuityError, "independently publish finalized height and hash"
        ):
            health_entrypoint._health_projection_normalize_snapshot(
                health, source="operational_api", require_safety=True
            )

    def test_rejects_safety_divergence(self) -> None:
        compatibility._cached_explorer_payload = {
            **EXPLORER,
            "assets_moved": True,
        }
        with self.assertRaisesRegex(
            continuity.ContinuityError, "assets_moved diverge"
        ):
            health_entrypoint._health_projection_normalize_snapshot(
                HEALTH, source="operational_api", require_safety=True
            )


if __name__ == "__main__":
    unittest.main()
