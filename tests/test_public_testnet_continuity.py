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

OPERATIONAL_LIVE = {
    "network": {
        "chainId": "20260723",
        "height": "12",
        "headHash": "0x" + "1" * 64,
        "certificateHash": "0x" + "2" * 64,
        "finality": "3 / 3",
        "mainnetChanged": False,
        "assetsMoved": False,
        "bridgeActivated": False,
    }
}

EXPLORER_V4 = {
    "network": {
        "chain_id": "0x1352773",
        "chain_id_decimal": 20260723,
    },
    "head": {
        "height": 12,
        "hash": "0x" + "1" * 64,
        "certificate_hash": "0x" + "2" * 64,
        "signed_power": 3,
        "total_power": 3,
    },
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
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

    def test_normalizes_exact_live_operational_and_explorer_v4_shapes(self) -> None:
        operational = normalize_snapshot(
            OPERATIONAL_LIVE,
            source="operational_api",
            require_safety=True,
        )
        explorer = normalize_snapshot(
            EXPLORER_V4,
            source="explorer_json",
            require_safety=True,
        )
        compare_pair(operational, explorer, expected_chain_id=20260723)
        self.assertEqual(operational.finalized_height, 12)
        self.assertEqual(explorer.chain_id, 20260723)

    def test_integer_strings_accept_only_exact_decimal_or_hex(self) -> None:
        for invalid in (" 20260723", "20260723 ", "+20260723", "20_260_723", "1.0", "0x", "0xg"):
            payload = {
                **EXPLORER,
                "chain_id": invalid,
            }
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ContinuityError, "must be an integer"):
                    normalize_snapshot(
                        payload,
                        source="explorer_json",
                        require_safety=False,
                    )

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

    def test_rejects_cross_source_identity_and_quorum_drift(self) -> None:
        operational = normalize_snapshot(
            OPERATIONAL_LIVE,
            source="operational_api",
            require_safety=True,
        )
        inconsistent_chain = {
            **EXPLORER_V4,
            "network": {
                **EXPLORER_V4["network"],
                "chain_id_decimal": 1,
            },
            "head": dict(EXPLORER_V4["head"]),
        }
        with self.assertRaisesRegex(ContinuityError, "chain_id evidence diverges"):
            normalize_snapshot(
                inconsistent_chain,
                source="explorer_json",
                require_safety=True,
            )
        cases = (
            ("height", 13, "heights diverge"),
            ("hash", "0x" + "3" * 64, "hashes diverge"),
            (
                "certificate_hash",
                "0x" + "4" * 64,
                "certificates diverge",
            ),
            ("signed_power", 4, "finality power diverges"),
        )
        for field, value, message in cases:
            payload = {
                **EXPLORER_V4,
                "network": dict(EXPLORER_V4["network"]),
                "head": dict(EXPLORER_V4["head"]),
            }
            payload["head"][field] = value
            explorer = normalize_snapshot(
                payload,
                source="explorer_json",
                require_safety=True,
            )
            with self.subTest(field=field):
                with self.assertRaisesRegex(ContinuityError, message):
                    compare_pair(
                        operational,
                        explorer,
                        expected_chain_id=20260723,
                    )

    def test_rejects_camel_case_safety_true_or_missing(self) -> None:
        for field in ("mainnetChanged", "assetsMoved", "bridgeActivated"):
            unsafe = {
                "network": dict(OPERATIONAL_LIVE["network"]),
            }
            unsafe["network"][field] = True
            with self.subTest(field=field, state="true"):
                with self.assertRaisesRegex(ContinuityError, "must remain false"):
                    normalize_snapshot(
                        unsafe,
                        source="operational_api",
                        require_safety=True,
                    )
            missing = {
                "network": dict(OPERATIONAL_LIVE["network"]),
            }
            del missing["network"][field]
            with self.subTest(field=field, state="missing"):
                with self.assertRaisesRegex(ContinuityError, "evidence is required"):
                    normalize_snapshot(
                        missing,
                        source="operational_api",
                        require_safety=True,
                    )

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
