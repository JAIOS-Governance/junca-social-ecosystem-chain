import copy
import unittest

from jaios.social_ecosystem_chain.rolling_compatibility import (
    RollingCompatibilityError,
    evaluate_rolling_compatibility,
)


def evidence():
    validators = []
    for validator_id in ("validator-01", "validator-02", "validator-03"):
        validators.append(
            {
                "validator_id": validator_id,
                "runtime_version": "v1",
                "healthy": True,
                "head_height": 7,
                "head_hash": "0x" + "ab" * 32,
                "automatic_finality_enabled": False,
                "slot_epoch_seconds": None,
            }
        )
    return {
        "target_version": "v2",
        "update_order": ["validator-01", "validator-02", "validator-03"],
        "validators": validators,
        "requested_slot_epoch_seconds": 2_000_000_000,
        "observed_unix_time": 1_900_000_000,
        "fallback_active": False,
        "rollback": {
            "target_version": "v1",
            "artifact_sha256": "a" * 64,
            "rehearsal_passed": True,
            "automatic_finality_disabled": True,
        },
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class RollingCompatibilityTests(unittest.TestCase):
    def test_three_node_sequence_then_epoch_then_enable(self):
        value = evidence()
        for index, validator_id in enumerate(value["update_order"]):
            decision = evaluate_rolling_compatibility(value)
            self.assertEqual(decision["next_validator"], validator_id)
            value["validators"][index]["runtime_version"] = "v2"
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"], "READY_FOR_SLOT_EPOCH"
        )
        for validator in value["validators"]:
            validator["slot_epoch_seconds"] = 2_000_000_000
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"],
            "READY_FOR_FINALITY_ENABLE",
        )
        for validator in value["validators"]:
            validator["automatic_finality_enabled"] = True
        self.assertEqual(evaluate_rolling_compatibility(value)["state"], "ACCEPTED")

    def test_quorum_and_head_disagreement_fail_closed(self):
        value = evidence()
        value["validators"][1]["healthy"] = False
        value["validators"][2]["healthy"] = False
        with self.assertRaisesRegex(RollingCompatibilityError, "quorum"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][2]["head_hash"] = "0x" + "00" * 32
        with self.assertRaisesRegex(RollingCompatibilityError, "disagree"):
            evaluate_rolling_compatibility(value)

    def test_out_of_order_or_mixed_finality_fails_closed(self):
        value = evidence()
        value["validators"][1]["runtime_version"] = "v2"
        with self.assertRaisesRegex(RollingCompatibilityError, "order"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["automatic_finality_enabled"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "mixed"):
            evaluate_rolling_compatibility(value)

    def test_fallback_rollback_and_boundary_drift_fail_closed(self):
        cases = (
            ("fallback_active", True, "fallback"),
            ("mainnet_changed", True, "mainnet_changed"),
        )
        for field, invalid, message in cases:
            value = evidence()
            value[field] = invalid
            with self.assertRaisesRegex(RollingCompatibilityError, message):
                evaluate_rolling_compatibility(value)
        value = evidence()
        value["rollback"]["rehearsal_passed"] = False
        with self.assertRaisesRegex(RollingCompatibilityError, "rollback"):
            evaluate_rolling_compatibility(value)

    def test_partial_epoch_and_premature_enable_fail_closed(self):
        value = evidence()
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
        value["validators"][0]["slot_epoch_seconds"] = 2_000_000_000
        with self.assertRaisesRegex(RollingCompatibilityError, "slot epoch"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
        value["validators"][0]["automatic_finality_enabled"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "mixed"):
            evaluate_rolling_compatibility(value)


if __name__ == "__main__":
    unittest.main()
