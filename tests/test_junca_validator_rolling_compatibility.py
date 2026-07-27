import copy
import unittest

from jaios.social_ecosystem_chain.rolling_compatibility import (
    RollingCompatibilityError,
    evaluate_rolling_compatibility,
)


def evidence():
    validators = []
    rollback_validators = []
    for index, validator_id in enumerate(
        ("validator-01", "validator-02", "validator-03"), start=1
    ):
        validators.append(
            {
                "validator_id": validator_id,
                "runtime_version": "v1",
                "ami_id": "ami-11111111111111111",
                "healthy": True,
                "health_status": "healthy",
                "network": "Public Testnet / No Monetary Value",
                "chain_id": 20260723,
                "ssm_online": True,
                "service_active": True,
                "durable_mount_verified": True,
                "state_store_integrity": True,
                "head_height": 7,
                "head_hash": "0x" + "ab" * 32,
                "certificate_hash": "0x" + "cd" * 32,
                "durable_certificate_hash": "0x" + "cd" * 32,
                "certificate_height": 7,
                "certificate_block_hash": "0x" + "ab" * 32,
                "certificate_finality_status": "FINALIZED",
                "certificate_signed_power": 3,
                "certificate_total_power": 3,
                "certificate_validator_ids": [
                    "validator-01",
                    "validator-02",
                    "validator-03",
                ],
                "certificate_vote_hashes": [
                    "0x" + f"{offset:02x}" * 32 for offset in (1, 2, 3)
                ],
                "automatic_finality_enabled": False,
                "block_interval_seconds": 0,
                "slot_epoch_seconds": 0,
                "finality_readback": {
                    "runtime_env": {
                        "automatic_finality_enabled": False,
                        "block_interval_seconds": 0,
                        "slot_epoch_seconds": 0,
                    },
                    "health": {
                        "automatic_finality_enabled": False,
                        "block_interval_seconds": 0,
                        "slot_epoch_seconds": 0,
                    },
                    "health_supported": True,
                },
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            }
        )
        rollback_validators.append(
            {
                "validator_id": validator_id,
                "volume_id": f"vol-{index:017x}",
                "rollback_snapshot_id": f"snap-{index:017x}",
                "state_rewind_permitted": False,
                "head_height": 7,
                "head_hash": "0x" + "ab" * 32,
                "certificate_hash": "0x" + "cd" * 32,
                "certificate_height": 7,
                "certificate_block_hash": "0x" + "ab" * 32,
                "certificate_finality_status": "FINALIZED",
                "certificate_signed_power": 3,
                "certificate_total_power": 3,
                "certificate_validator_ids": [
                    "validator-01",
                    "validator-02",
                    "validator-03",
                ],
                "certificate_vote_hashes": [
                    "0x" + f"{offset:02x}" * 32 for offset in (1, 2, 3)
                ],
            }
        )
    return {
        "target_version": "v2",
        "target_ami_id": "ami-22222222222222222",
        "update_order": ["validator-01", "validator-02", "validator-03"],
        "validators": validators,
        "requested_slot_epoch_seconds": 2_000_000_000,
        "observed_unix_time": 1_999_994_000,
        "fallback_active": False,
        "rollback": {
            "target_version": "v1",
            "artifact_sha256": "a" * 64,
            "ami_id": "ami-11111111111111111",
            "rehearsal_passed": True,
            "automatic_finality_disabled": True,
            "no_state_rewind": True,
            "durable_volume_reused": True,
            "snapshot_restore_performed": False,
            "validators": rollback_validators,
        },
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class RollingCompatibilityTests(unittest.TestCase):
    def test_resumable_prefixes_zero_one_two_three_are_exact(self):
        expected = (
            ("READY_FOR_NEXT_VALIDATOR", "validator-01"),
            ("READY_FOR_NEXT_VALIDATOR", "validator-02"),
            ("READY_FOR_NEXT_VALIDATOR", "validator-03"),
            ("READY_FOR_SLOT_EPOCH", None),
        )
        for prefix, (state, next_validator) in enumerate(expected):
            value = evidence()
            for index in range(prefix):
                value["validators"][index]["runtime_version"] = "v2"
                value["validators"][index]["ami_id"] = (
                    "ami-22222222222222222"
                )
            decision = evaluate_rolling_compatibility(value)
            self.assertEqual(decision["updated_count"], prefix)
            self.assertEqual(decision["state"], state)
            self.assertEqual(decision["next_validator"], next_validator)

    def test_three_node_sequence_then_epoch_then_enable(self):
        value = evidence()
        for index, validator_id in enumerate(value["update_order"]):
            decision = evaluate_rolling_compatibility(value)
            self.assertEqual(decision["next_validator"], validator_id)
            value["validators"][index]["runtime_version"] = "v2"
            value["validators"][index]["ami_id"] = "ami-22222222222222222"
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"], "READY_FOR_SLOT_EPOCH"
        )
        for validator in value["validators"]:
            validator["slot_epoch_seconds"] = 2_000_000_000
            validator["finality_readback"]["runtime_env"][
                "slot_epoch_seconds"
            ] = 2_000_000_000
            validator["finality_readback"]["health"]["slot_epoch_seconds"] = (
                2_000_000_000
            )
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"],
            "READY_FOR_FINALITY_ENABLE",
        )
        for validator in value["validators"]:
            validator["automatic_finality_enabled"] = True
            validator["block_interval_seconds"] = 30
            validator["finality_readback"]["runtime_env"].update(
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                }
            )
            validator["finality_readback"]["health"].update(
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                }
            )
        self.assertEqual(evaluate_rolling_compatibility(value)["state"], "ACCEPTED")

    def test_quorum_and_head_disagreement_fail_closed(self):
        value = evidence()
        value["validators"][1]["service_active"] = False
        with self.assertRaisesRegex(RollingCompatibilityError, "service_active"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        for rollback in value["rollback"]["validators"]:
            rollback["head_height"] = 6
            rollback["certificate_height"] = 6
        value["validators"][2]["head_hash"] = "0x" + "00" * 32
        value["validators"][2]["certificate_block_hash"] = "0x" + "00" * 32
        with self.assertRaisesRegex(RollingCompatibilityError, "disagree"):
            evaluate_rolling_compatibility(value)

    def test_out_of_order_or_mixed_finality_fails_closed(self):
        value = evidence()
        value["validators"][1]["runtime_version"] = "v2"
        value["validators"][1]["ami_id"] = "ami-22222222222222222"
        with self.assertRaisesRegex(RollingCompatibilityError, "order"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["automatic_finality_enabled"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "mixed"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["ami_id"] = "ami-33333333333333333"
        with self.assertRaisesRegex(RollingCompatibilityError, "AMI binding"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][2]["runtime_version"] = "v2"
        value["validators"][2]["ami_id"] = "ami-22222222222222222"
        with self.assertRaisesRegex(RollingCompatibilityError, "order"):
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
        value = evidence()
        value["rollback"]["no_state_rewind"] = False
        with self.assertRaisesRegex(RollingCompatibilityError, "rollback"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["rollback"]["validators"][0]["state_rewind_permitted"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "rewind"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["rollback"]["validators"][1]["rollback_snapshot_id"] = (
            value["rollback"]["validators"][0]["rollback_snapshot_id"]
        )
        with self.assertRaisesRegex(RollingCompatibilityError, "distinct"):
            evaluate_rolling_compatibility(value)

    def test_per_validator_runtime_and_durable_state_health_is_required(self):
        fields = (
            "ssm_online",
            "service_active",
            "durable_mount_verified",
            "state_store_integrity",
        )
        for field in fields:
            value = evidence()
            value["validators"][0][field] = False
            with self.assertRaisesRegex(RollingCompatibilityError, field):
                evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["certificate_signed_power"] = 2
        with self.assertRaisesRegex(RollingCompatibilityError, "quorum proof"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["durable_certificate_hash"] = "0x" + "44" * 32
        with self.assertRaisesRegex(RollingCompatibilityError, "live and durable"):
            evaluate_rolling_compatibility(value)

    def test_head_may_advance_but_cannot_rewind_or_change_at_floor(self):
        value = evidence()
        for validator in value["validators"]:
            validator.update(
                {
                    "head_height": 8,
                    "head_hash": "0x" + "ef" * 32,
                    "certificate_hash": "0x" + "12" * 32,
                    "durable_certificate_hash": "0x" + "12" * 32,
                    "certificate_height": 8,
                    "certificate_block_hash": "0x" + "ef" * 32,
                }
            )
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"],
            "READY_FOR_NEXT_VALIDATOR",
        )
        value = evidence()
        value["rollback"]["validators"][0]["head_height"] = 8
        value["rollback"]["validators"][0]["certificate_height"] = 8
        with self.assertRaisesRegex(RollingCompatibilityError, "rewind"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        value["validators"][0]["certificate_hash"] = "0x" + "34" * 32
        value["validators"][0]["durable_certificate_hash"] = "0x" + "34" * 32
        with self.assertRaisesRegex(
            RollingCompatibilityError, "changed at rollback floor"
        ):
            evaluate_rolling_compatibility(value)

    def test_partial_epoch_and_premature_enable_fail_closed(self):
        value = evidence()
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
            validator["ami_id"] = "ami-22222222222222222"
        value["validators"][0]["slot_epoch_seconds"] = 2_000_000_000
        value["validators"][0]["finality_readback"]["runtime_env"][
            "slot_epoch_seconds"
        ] = 2_000_000_000
        value["validators"][0]["finality_readback"]["health"][
            "slot_epoch_seconds"
        ] = 2_000_000_000
        with self.assertRaisesRegex(RollingCompatibilityError, "slot epoch"):
            evaluate_rolling_compatibility(value)
        value = evidence()
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
            validator["ami_id"] = "ami-22222222222222222"
        value["validators"][0]["automatic_finality_enabled"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "mixed"):
            evaluate_rolling_compatibility(value)

    def test_network_finality_interval_and_target_health_are_fail_closed(self):
        value = evidence()
        value["validators"][0]["network"] = "Public Testnet"
        with self.assertRaisesRegex(RollingCompatibilityError, "binding"):
            evaluate_rolling_compatibility(value)

        value = evidence()
        value["validators"][0]["chain_id"] = 1
        with self.assertRaisesRegex(RollingCompatibilityError, "binding"):
            evaluate_rolling_compatibility(value)

        value = evidence()
        value["validators"][0]["block_interval_seconds"] = 30
        with self.assertRaisesRegex(RollingCompatibilityError, "block interval"):
            evaluate_rolling_compatibility(value)

    def test_legacy_finality_provenance_is_previous_runtime_only(self):
        value = evidence()
        value["validators"][0]["finality_readback"]["health"] = {
            "automatic_finality_enabled": None,
            "block_interval_seconds": None,
            "slot_epoch_seconds": None,
        }
        value["validators"][0]["finality_readback"]["health_supported"] = False
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"],
            "READY_FOR_NEXT_VALIDATOR",
        )

        value["validators"][0]["finality_readback"]["health"][
            "block_interval_seconds"
        ] = 0
        with self.assertRaisesRegex(
            RollingCompatibilityError, "legacy health provenance"
        ):
            evaluate_rolling_compatibility(value)

        value = evidence()
        value["validators"][0]["finality_readback"]["runtime_env"][
            "slot_epoch_seconds"
        ] = 30
        with self.assertRaisesRegex(
            RollingCompatibilityError, "runtime.env finality provenance"
        ):
            evaluate_rolling_compatibility(value)

        value = evidence()
        value["validators"][0]["runtime_version"] = "v2"
        value["validators"][0]["ami_id"] = "ami-22222222222222222"
        value["validators"][0]["finality_readback"]["health"] = {
            "automatic_finality_enabled": None,
            "block_interval_seconds": None,
            "slot_epoch_seconds": None,
        }
        value["validators"][0]["finality_readback"]["health_supported"] = False
        with self.assertRaisesRegex(
            RollingCompatibilityError, "target runtime finality health"
        ):
            evaluate_rolling_compatibility(value)

        value = evidence()
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
            validator["ami_id"] = "ami-22222222222222222"
            validator["slot_epoch_seconds"] = 2_000_000_000
            validator["automatic_finality_enabled"] = True
        with self.assertRaisesRegex(RollingCompatibilityError, "block interval"):
            evaluate_rolling_compatibility(value)

    def test_resume_epoch_expiry_tamper_and_safety_window_fail_closed(self):
        for observed_time in (
            2_000_000_000,
            1_999_999_500,
            1_999_990_000,
        ):
            value = evidence()
            value["observed_unix_time"] = observed_time
            with self.assertRaisesRegex(
                RollingCompatibilityError,
                "future canonical|bounded safety window",
            ):
                evaluate_rolling_compatibility(value)
        value = evidence()
        value["requested_slot_epoch_seconds"] = "2000000000"
        with self.assertRaisesRegex(RollingCompatibilityError, "future canonical"):
            evaluate_rolling_compatibility(value)


if __name__ == "__main__":
    unittest.main()
