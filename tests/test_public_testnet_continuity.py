from __future__ import annotations

from pathlib import Path
import unittest

from scripts.ops.public_testnet_continuity import (
    ContinuityError,
    compare_pair,
    evaluate_observations,
    normalize_snapshot,
    validate_freshness,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-public-testnet-continuity.yml"


OPERATIONAL = {
    "runtime_evidence": {
        "chain_id": 20260723,
        "finalized_height": 12,
        "authenticated_peer_count": 2,
        "finalized_timestamp": 1_800_000_000,
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
    "peer_count": 2,
    "finalized_timestamp": 1_800_000_000,
    "head_hash": "0x" + "1" * 64,
    "last_certificate_hash": "0x" + "2" * 64,
    "quorum": "3/3",
}

OPERATIONAL_LIVE = {
    "network": {
        "chainId": "20260723",
        "height": "12",
        "peers": "2",
        "headHash": "0x" + "1" * 64,
        "certificateHash": "0x" + "2" * 64,
        "finality": "3 / 3",
        "mainnetChanged": False,
        "assetsMoved": False,
        "bridgeActivated": False,
    },
    "recovery": {
        "rpcPeers": "0x2",
        "rpcTimestamp": "0x6b49d200",
    },
}

EXPLORER_V4 = {
    "network": {
        "chain_id": "0x1352773",
        "chain_id_decimal": 20260723,
        "peer_count": 2,
        "peer_count_hex": "0x2",
    },
    "head": {
        "height": 12,
        "hash": "0x" + "1" * 64,
        "certificate_hash": "0x" + "2" * 64,
        "signed_power": 3,
        "timestamp": "0x6b49d200",
        "total_power": 3,
    },
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}


class PublicTestnetContinuityTests(unittest.TestCase):
    def test_workflow_binds_exact_activation_contract(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for argument in (
            "--expected-chain-id 20260723",
            "--expected-peer-count 2",
            "--expected-signed-power 3",
            "--expected-total-power 3",
            "--max-head-age-seconds 300",
            "--require-advancement",
        ):
            self.assertIn(argument, workflow)

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
        self.assertEqual(operational.authenticated_peer_count, 2)
        self.assertEqual(explorer.finalized_timestamp, 1_800_000_000)

    def test_integer_strings_accept_only_exact_decimal_or_hex(self) -> None:
        for invalid in (
            " 20260723",
            "20260723 ",
            "+20260723",
            "20_260_723",
            "1.0",
            "0x",
            "0xg",
        ):
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
                {
                    "chain_id": 20260723,
                    "height": 1,
                    "authenticated_peer_count": 2,
                    "finalized_timestamp": 1_800_000_000,
                    "quorum": "3/3",
                },
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

    def test_rejects_cross_source_peer_and_timestamp_drift(self) -> None:
        operational = normalize_snapshot(
            OPERATIONAL_LIVE,
            source="operational_api",
            require_safety=True,
        )
        cases = (
            ("peer_count", 1, "peer counts diverge"),
            ("timestamp", "0x6b49d201", "timestamps diverge"),
        )
        for field, value, message in cases:
            payload = {
                **EXPLORER_V4,
                "network": dict(EXPLORER_V4["network"]),
                "head": dict(EXPLORER_V4["head"]),
            }
            if field == "peer_count":
                payload["network"]["peer_count"] = value
                payload["network"]["peer_count_hex"] = hex(value)
            else:
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

    def test_rejects_wrong_exact_peer_and_quorum_contract(self) -> None:
        for field, value, message in (
            ("peer_count", 1, "peer count does not match"),
            ("signed_power", 4, "finality power does not match"),
            ("total_power", 4, "finality power does not match"),
        ):
            operational_payload = {
                **OPERATIONAL_LIVE,
                "network": dict(OPERATIONAL_LIVE["network"]),
                "recovery": dict(OPERATIONAL_LIVE["recovery"]),
            }
            explorer_payload = {
                **EXPLORER_V4,
                "network": dict(EXPLORER_V4["network"]),
                "head": dict(EXPLORER_V4["head"]),
            }
            if field == "peer_count":
                operational_payload["network"]["peers"] = str(value)
                operational_payload["recovery"]["rpcPeers"] = hex(value)
                explorer_payload["network"]["peer_count"] = value
                explorer_payload["network"]["peer_count_hex"] = hex(value)
            else:
                if field == "signed_power":
                    operational_payload["network"]["finality"] = (
                        f"{value} / {value}"
                    )
                    explorer_payload["head"]["signed_power"] = value
                    explorer_payload["head"]["total_power"] = value
                else:
                    operational_payload["network"]["finality"] = f"3 / {value}"
                    explorer_payload["head"]["total_power"] = value
            operational = normalize_snapshot(
                operational_payload,
                source="operational_api",
                require_safety=True,
            )
            explorer = normalize_snapshot(
                explorer_payload,
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

    def test_rejects_divergent_duplicate_chain_or_peer_evidence(self) -> None:
        bad_chain = {
            **EXPLORER_V4,
            "network": {
                **EXPLORER_V4["network"],
                "chain_id_decimal": 1,
            },
            "head": dict(EXPLORER_V4["head"]),
        }
        with self.assertRaisesRegex(ContinuityError, "chain_id evidence diverges"):
            normalize_snapshot(
                bad_chain,
                source="explorer_json",
                require_safety=True,
            )
        bad_peers = {
            **EXPLORER_V4,
            "network": {
                **EXPLORER_V4["network"],
                "peer_count_hex": "0x1",
            },
            "head": dict(EXPLORER_V4["head"]),
        }
        with self.assertRaisesRegex(
            ContinuityError, "authenticated_peer_count evidence diverges"
        ):
            normalize_snapshot(
                bad_peers,
                source="explorer_json",
                require_safety=True,
            )

    def test_rejects_camel_case_safety_true_or_missing(self) -> None:
        for field in ("mainnetChanged", "assetsMoved", "bridgeActivated"):
            unsafe = {
                "network": dict(OPERATIONAL_LIVE["network"]),
                "recovery": dict(OPERATIONAL_LIVE["recovery"]),
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
                "recovery": dict(OPERATIONAL_LIVE["recovery"]),
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
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
            {
                "operational": {
                    "finalized_height": 11,
                    "finalized_timestamp": 1_800_000_001,
                }
            },
        ]
        self.assertEqual(
            evaluate_observations(observations, require_advancement=True),
            "ACTIVE_ADVANCING",
        )

    def test_stable_window_is_read_only_when_advancement_not_required(self) -> None:
        observations = [
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
        ]
        self.assertEqual(
            evaluate_observations(observations, require_advancement=False),
            "ACTIVE_STABLE_READ_ONLY",
        )
        with self.assertRaisesRegex(ContinuityError, "did not advance"):
            evaluate_observations(observations, require_advancement=True)

    def test_rejects_height_regression(self) -> None:
        observations = [
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
            {
                "operational": {
                    "finalized_height": 9,
                    "finalized_timestamp": 1_800_000_001,
                }
            },
        ]
        with self.assertRaisesRegex(ContinuityError, "regressed"):
            evaluate_observations(observations, require_advancement=False)

    def test_rejects_timestamp_regression(self) -> None:
        observations = [
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_001,
                }
            },
            {
                "operational": {
                    "finalized_height": 10,
                    "finalized_timestamp": 1_800_000_000,
                }
            },
        ]
        with self.assertRaisesRegex(ContinuityError, "timestamp regressed"):
            evaluate_observations(observations, require_advancement=False)

    def test_rejects_stale_or_future_finalized_head(self) -> None:
        snapshot = normalize_snapshot(
            OPERATIONAL_LIVE,
            source="operational_api",
            require_safety=True,
        )
        with self.assertRaisesRegex(ContinuityError, "head is stale"):
            validate_freshness(
                snapshot,
                observed_at=1_800_000_301,
                max_age_seconds=300,
            )
        with self.assertRaisesRegex(ContinuityError, "in the future"):
            validate_freshness(
                snapshot,
                observed_at=1_799_999_939,
                max_age_seconds=300,
            )
        validate_freshness(
            snapshot,
            observed_at=1_800_000_300,
            max_age_seconds=300,
        )


if __name__ == "__main__":
    unittest.main()
