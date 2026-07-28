from __future__ import annotations

import unittest

from scripts.ops.public_testnet_continuity import (
    ContinuityError,
    compare_pair,
    evaluate_observations,
    normalize_snapshot,
)


OPERATIONAL = {
    "runtime_evidence": {
        "chain_id": 20260723,
        "finalized_height": 12,
        "finalized_hash": "0x" + "1" * 64,
        "certificate_hash": "0x" + "2" * 64,
        "signed_power": 3,
        "total_power": 3,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
}

EXPLORER = {
    "chain_id": 20260723,
    "head_height": 12,
    "head_hash": "0x" + "1" * 64,
    "last_certificate_hash": "0x" + "2" * 64,
    "quorum": "3/3",
}


class PublicTestnetContinuityTests(unittest.TestCase):
    def test_normalizes_and_compares_public_evidence(self) -> None:
        operational = normalize_snapshot(
            OPERATIONAL, source="operational_api", require_safety=True
        )
        explorer = normalize_snapshot(
            EXPLORER, source="explorer_json", require_safety=False
        )
        compare_pair(operational, explorer, expected_chain_id=20260723)
        self.assertEqual(operational.finalized_height, 12)
        self.assertEqual(operational.signed_power, 3)

    def test_rejects_missing_operational_safety_boundary(self) -> None:
        with self.assertRaisesRegex(ContinuityError, "mainnet_changed evidence"):
            normalize_snapshot(
                {"chain_id": 20260723, "height": 1, "quorum": "3/3"},
                source="operational_api",
                require_safety=True,
            )

    def test_rejects_divergent_finalized_height(self) -> None:
        operational = normalize_snapshot(
            OPERATIONAL, source="operational_api", require_safety=True
        )
        explorer_payload = {**EXPLORER, "head_height": 11}
        explorer = normalize_snapshot(
            explorer_payload, source="explorer_json", require_safety=False
        )
        with self.assertRaisesRegex(ContinuityError, "heights diverge"):
            compare_pair(operational, explorer, expected_chain_id=20260723)

    def test_rejects_non_quorum_snapshot(self) -> None:
        value = {
            **EXPLORER,
            "quorum": "2/3",
        }
        with self.assertRaisesRegex(ContinuityError, "does not exceed two-thirds"):
            normalize_snapshot(value, source="explorer_json", require_safety=False)

    def test_classifies_advancing_observation_window(self) -> None:
        observations = [
            {"operational": {"finalized_height": 10}},
            {"operational": {"finalized_height": 10}},
            {"operational": {"finalized_height": 11}},
        ]
        self.assertEqual(
            evaluate_observations(observations, require_advancement=True),
            "ACTIVE_ADVANCING",
        )

    def test_stable_window_is_read_only_when_advancement_not_required(self) -> None:
        observations = [
            {"operational": {"finalized_height": 10}},
            {"operational": {"finalized_height": 10}},
        ]
        self.assertEqual(
            evaluate_observations(observations, require_advancement=False),
            "ACTIVE_STABLE_READ_ONLY",
        )
        with self.assertRaisesRegex(ContinuityError, "did not advance"):
            evaluate_observations(observations, require_advancement=True)

    def test_rejects_height_regression(self) -> None:
        observations = [
            {"operational": {"finalized_height": 10}},
            {"operational": {"finalized_height": 9}},
        ]
        with self.assertRaisesRegex(ContinuityError, "regressed"):
            evaluate_observations(observations, require_advancement=False)


if __name__ == "__main__":
    unittest.main()
