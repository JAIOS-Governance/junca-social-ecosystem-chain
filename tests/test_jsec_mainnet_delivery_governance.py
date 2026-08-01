from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jaios.social_ecosystem_chain.mainnet_delivery_governance import (
    ACTIVE_CELL,
    ACTIVE_POSITION,
    MainnetDeliveryGovernanceError,
    evaluate_mainnet_delivery_cell,
    load_mainnet_delivery_cell,
)


CONFIG = Path("config/jsec_mainnet_delivery_cell_v1.json")


def specification() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def implementation_claim() -> dict[str, object]:
    return {
        "schema_version": "jsec-mainnet-delivery-claim/v1",
        "cell": ACTIVE_CELL,
        "phase": "development",
        "progress_type": "implementation",
        "source_commit": "a" * 40,
        "changed_paths": [
            "jaios/social_ecosystem_chain/native_token_genesis.py",
            "tests/test_jsec_native_token_genesis.py",
        ],
        "tests": {"passed": 12, "failed": 0},
        "next_unblocked_task": "compile the approved native economics into Genesis",
        "safety": {
            "mainnet_changed": False,
            "genesis_applied": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        },
    }


class MainnetDeliveryGovernanceTests(unittest.TestCase):
    def test_replacement_cell_is_active_and_target_date_does_not_move(self) -> None:
        cell = load_mainnet_delivery_cell()
        evidence = cell.as_evidence()
        self.assertEqual(evidence["active_cell"], ACTIVE_CELL)
        self.assertEqual(evidence["position"], ACTIVE_POSITION)
        self.assertEqual(evidence["prior_cell_status"], "disqualified")
        self.assertEqual(evidence["target_release_date"], "2026-10-01")
        self.assertTrue(evidence["public_testnet_must_remain_running"])
        self.assertFalse(evidence["safety"]["mainnet_changed"])
        self.assertFalse(evidence["safety"]["assets_moved"])
        self.assertFalse(evidence["safety"]["bridge_activated"])

    def test_monitoring_only_claim_is_governance_violation(self) -> None:
        claim = implementation_claim()
        claim["progress_type"] = "monitoring"
        with self.assertRaisesRegex(
            MainnetDeliveryGovernanceError, "governance violation"
        ):
            load_mainnet_delivery_cell().evaluate_progress_claim(claim)

    def test_progress_requires_implementation_path_and_passing_tests(self) -> None:
        cell = load_mainnet_delivery_cell()
        claim = implementation_claim()
        claim["changed_paths"] = ["evidence/monitoring.json"]
        with self.assertRaisesRegex(
            MainnetDeliveryGovernanceError, "implementation path"
        ):
            cell.evaluate_progress_claim(claim)

        claim = implementation_claim()
        claim["tests"] = {"passed": 11, "failed": 1}
        with self.assertRaisesRegex(MainnetDeliveryGovernanceError, "zero failures"):
            cell.evaluate_progress_claim(claim)

    def test_valid_implementation_claim_is_verified(self) -> None:
        result = load_mainnet_delivery_cell().evaluate_progress_claim(
            implementation_claim()
        )
        self.assertEqual(result["state"], "IMPLEMENTATION_PROGRESS_VERIFIED")
        self.assertFalse(result["monitoring_counted_as_progress"])
        self.assertEqual(result["tests"], {"passed": 12, "failed": 0})

    def test_cell_or_safety_drift_is_rejected(self) -> None:
        for mutation in ("cell", "safety"):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(specification())
                if mutation == "cell":
                    value["active_cell"]["name"] = "Former Cell"
                else:
                    value["safety"]["mainnet_changed"] = True
                with self.assertRaises(MainnetDeliveryGovernanceError):
                    evaluate_mainnet_delivery_cell(value)


if __name__ == "__main__":
    unittest.main()
