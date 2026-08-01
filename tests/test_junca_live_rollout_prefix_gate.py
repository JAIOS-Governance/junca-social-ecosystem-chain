from __future__ import annotations

import copy
import unittest

from scripts.junca_live_rollout_prefix_gate import (
    EvidenceBoundPrefixError,
    evaluate_evidence_bound_rolling_compatibility,
    evaluate_live_rollout_prefix_v2,
)
from tests.test_junca_validator_rolling_compatibility import evidence


TARGET = "b" * 64
PREVIOUS = "a" * 64
EMERGENCY = "c" * 64
TARGET_AMI = "ami-22222222222222222"
PREVIOUS_AMI = "ami-11111111111111111"
EMERGENCY_AMI = "ami-33333333333333333"
TARGET_EPOCH = 2_000_000_000
OBSERVED_TIME = TARGET_EPOCH - 6_000


class EvidenceBoundLivePrefixTests(unittest.TestCase):
    def fixture(self):
        value = evidence()
        value["target_version"] = TARGET
        value["target_ami_id"] = TARGET_AMI
        value["rollback"]["target_version"] = PREVIOUS
        value["rollback"]["artifact_sha256"] = PREVIOUS
        value["rollback"]["ami_id"] = PREVIOUS_AMI
        value["requested_slot_epoch_seconds"] = TARGET_EPOCH
        value["observed_unix_time"] = OBSERVED_TIME
        for index, validator in enumerate(value["validators"], start=1):
            validator["runtime_version"] = PREVIOUS
            validator["ami_id"] = PREVIOUS_AMI
            validator["instance_id"] = f"i-{index:017x}"
            validator["volume_id"] = value["rollback"]["validators"][
                index - 1
            ]["volume_id"]
        value["previous_version"] = PREVIOUS
        value["previous_ami_id"] = PREVIOUS_AMI
        value["evidence_updated_count"] = 0
        value["evidence_validators"] = copy.deepcopy(value["validators"])
        value["fallback_active"] = False
        return value

    @staticmethod
    def set_finality(
        validator,
        *,
        enabled: bool,
        interval: int,
        epoch: int,
    ):
        validator.update(
            {
                "automatic_finality_enabled": enabled,
                "block_interval_seconds": interval,
                "slot_epoch_seconds": epoch,
            }
        )
        for source in ("runtime_env", "health"):
            validator["finality_readback"][source].update(
                {
                    "automatic_finality_enabled": enabled,
                    "block_interval_seconds": interval,
                    "slot_epoch_seconds": epoch,
                }
            )

    def set_target(
        self,
        validator,
        *,
        instance_id: str,
        enabled: bool = True,
        interval: int = 30,
        epoch: int = TARGET_EPOCH,
    ):
        validator.update(
            {
                "instance_id": instance_id,
                "runtime_version": TARGET,
                "ami_id": TARGET_AMI,
            }
        )
        self.set_finality(
            validator,
            enabled=enabled,
            interval=interval,
            epoch=epoch,
        )

    def set_heterogeneous_emergency_baseline(self, value):
        for item in (
            value["validators"][0],
            value["evidence_validators"][0],
        ):
            item["runtime_version"] = EMERGENCY
            item["ami_id"] = EMERGENCY_AMI
            self.set_finality(
                item,
                enabled=True,
                interval=30,
                epoch=1_900_000_000,
            )

    def test_accepts_heterogeneous_evidence_bound_start(self):
        value = self.fixture()
        self.set_heterogeneous_emergency_baseline(value)

        decision = evaluate_live_rollout_prefix_v2(value)
        self.assertEqual(decision["state"], "EVIDENCE_BOUND_PREFIX_ACCEPTED")
        self.assertEqual(decision["live_updated_count"], 0)
        self.assertEqual(decision["next_validator"], "validator-01")
        self.assertEqual(
            decision["baseline_bindings"][0]["runtime_version"], EMERGENCY
        )
        self.assertEqual(
            decision["baseline_bindings"][0]["ami_id"], EMERGENCY_AMI
        )
        self.assertTrue(
            decision["baseline_bindings"][0][
                "automatic_finality_enabled"
            ]
        )

    def test_accepts_target_runtime_repaired_in_place_on_bound_old_ami(self):
        value = self.fixture()
        for item in (
            value["validators"][0],
            value["evidence_validators"][0],
        ):
            item["runtime_version"] = TARGET
            item["ami_id"] = EMERGENCY_AMI

        decision = evaluate_live_rollout_prefix_v2(value)

        self.assertEqual(decision["live_updated_count"], 0)
        self.assertEqual(decision["next_validator"], "validator-01")
        self.assertFalse(
            decision["baseline_bindings"][0]["target_runtime"]
        )
        self.assertEqual(
            decision["baseline_bindings"][0]["runtime_version"], TARGET
        )
        self.assertEqual(
            decision["baseline_bindings"][0]["ami_id"], EMERGENCY_AMI
        )

    def test_rejects_target_runtime_on_unbound_old_ami(self):
        value = self.fixture()
        value["evidence_validators"][0]["runtime_version"] = TARGET
        value["evidence_validators"][0]["ami_id"] = EMERGENCY_AMI
        value["validators"][0]["runtime_version"] = TARGET

        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "AMI binding mismatch"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_accepts_one_next_target_replacement(self):
        value = self.fixture()
        baseline = value["evidence_validators"][0]
        baseline["runtime_version"] = EMERGENCY
        baseline["ami_id"] = EMERGENCY_AMI
        self.set_target(
            value["validators"][0],
            instance_id="i-0000000000000000a",
        )

        decision = evaluate_live_rollout_prefix_v2(value)
        self.assertEqual(decision["live_updated_count"], 1)
        self.assertEqual(decision["recovered_uncommitted_count"], 1)
        self.assertEqual(decision["next_validator"], "validator-02")
        self.assertFalse(decision["baseline_bindings"][0]["target_runtime"])
        self.assertTrue(decision["promoted_bindings"][0]["target_runtime"])
        self.assertEqual(
            decision["promoted_bindings"][0]["instance_id"],
            "i-0000000000000000a",
        )
        self.assertEqual(
            decision["promoted_bindings"][1]["instance_id"],
            value["evidence_validators"][1]["instance_id"],
        )

    def test_accepts_quiesced_uncommitted_target_replacement(self):
        value = self.fixture()
        self.set_target(
            value["validators"][0],
            instance_id="i-0000000000000000a",
            enabled=False,
            interval=0,
            epoch=0,
        )
        decision = evaluate_live_rollout_prefix_v2(value)
        self.assertEqual(decision["live_updated_count"], 1)

    def test_accepts_committed_target_prefix_only_without_drift(self):
        value = self.fixture()
        value["evidence_updated_count"] = 1
        for source in (
            value["evidence_validators"][0],
            value["validators"][0],
        ):
            self.set_target(
                source,
                instance_id="i-0000000000000000a",
                enabled=False,
                interval=0,
                epoch=0,
            )
        decision = evaluate_live_rollout_prefix_v2(value)
        self.assertEqual(decision["live_updated_count"], 1)
        self.assertEqual(decision["recovered_uncommitted_count"], 0)

    def test_rejects_committed_target_finality_drift(self):
        value = self.fixture()
        value["evidence_updated_count"] = 1
        self.set_target(
            value["evidence_validators"][0],
            instance_id="i-0000000000000000a",
            enabled=False,
            interval=0,
            epoch=0,
        )
        self.set_target(
            value["validators"][0],
            instance_id="i-0000000000000000a",
            enabled=False,
            interval=0,
            epoch=TARGET_EPOCH,
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError,
            "committed target finality state drifted",
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_unknown_runtime_not_bound_to_baseline_or_target(self):
        value = self.fixture()
        value["validators"][0]["runtime_version"] = "d" * 64
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "unexpected runtime version"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_non_target_ami_drift_from_evidence(self):
        value = self.fixture()
        value["validators"][0]["ami_id"] = EMERGENCY_AMI
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "evidence AMI binding mismatch"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_target_inside_uncommitted_evidence_suffix(self):
        value = self.fixture()
        self.set_target(
            value["evidence_validators"][0],
            instance_id=value["evidence_validators"][0]["instance_id"],
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "evidence prefix does not match"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_non_target_finality_drift(self):
        value = self.fixture()
        self.set_finality(
            value["validators"][0],
            enabled=True,
            interval=30,
            epoch=1_900_000_000,
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "finality state drifted"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_target_without_instance_replacement(self):
        value = self.fixture()
        self.set_target(
            value["validators"][0],
            instance_id=value["evidence_validators"][0]["instance_id"],
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "did not replace"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_gap_in_target_prefix(self):
        value = self.fixture()
        self.set_target(
            value["validators"][1],
            instance_id="i-0000000000000000f",
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "update order is not contiguous"
        ):
            evaluate_live_rollout_prefix_v2(value)

    def test_rejects_state_volume_boundary_drift(self):
        value = self.fixture()
        value["validators"][0]["volume_id"] = "vol-99999999999999999"
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "rollback volume binding mismatch"
        ):
            evaluate_live_rollout_prefix_v2(value)


class EvidenceBoundRollingLifecycleTests(EvidenceBoundLivePrefixTests):
    def rolling_fixture(self):
        value = self.fixture()
        self.set_heterogeneous_emergency_baseline(value)
        for validator in value["validators"]:
            self.set_finality(
                validator,
                enabled=False,
                interval=0,
                epoch=0,
            )
        return value

    def test_quiesced_heterogeneous_start_is_ready_for_validator_one(self):
        value = self.rolling_fixture()
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_NEXT_VALIDATOR")
        self.assertEqual(decision["updated_count"], 0)
        self.assertEqual(decision["next_validator"], "validator-01")
        self.assertEqual(
            decision["baseline_bindings"][0]["runtime_version"], EMERGENCY
        )

    def test_repaired_target_runtime_on_old_ami_starts_before_validator_one(self):
        value = self.fixture()
        for item in (
            value["validators"][0],
            value["evidence_validators"][0],
        ):
            item["runtime_version"] = TARGET
            item["ami_id"] = EMERGENCY_AMI
            self.set_finality(item, enabled=False, interval=0, epoch=0)
        for item in value["validators"][1:]:
            self.set_finality(item, enabled=False, interval=0, epoch=0)

        decision = evaluate_evidence_bound_rolling_compatibility(value)

        self.assertEqual(decision["state"], "READY_FOR_NEXT_VALIDATOR")
        self.assertEqual(decision["updated_count"], 0)
        self.assertEqual(decision["next_validator"], "validator-01")

    def test_one_target_is_ready_for_validator_two(self):
        value = self.rolling_fixture()
        self.set_target(
            value["validators"][0],
            instance_id="i-0000000000000000a",
            enabled=False,
            interval=0,
            epoch=0,
        )
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_NEXT_VALIDATOR")
        self.assertEqual(decision["updated_count"], 1)
        self.assertEqual(decision["next_validator"], "validator-02")

    def test_three_quiesced_targets_are_ready_for_slot_epoch(self):
        value = self.rolling_fixture()
        for index, validator in enumerate(value["validators"], start=10):
            self.set_target(
                validator,
                instance_id=f"i-{index:017x}",
                enabled=False,
                interval=0,
                epoch=0,
            )
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_SLOT_EPOCH")
        self.assertEqual(decision["updated_count"], 3)
        self.assertIsNone(decision["next_validator"])

    def test_three_epoch_configured_targets_are_ready_for_enable(self):
        value = self.rolling_fixture()
        for index, validator in enumerate(value["validators"], start=10):
            self.set_target(
                validator,
                instance_id=f"i-{index:017x}",
                enabled=False,
                interval=0,
                epoch=TARGET_EPOCH,
            )
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_FINALITY_ENABLE")

    def test_three_enabled_targets_are_accepted(self):
        value = self.rolling_fixture()
        for index, validator in enumerate(value["validators"], start=10):
            self.set_target(
                validator,
                instance_id=f"i-{index:017x}",
                enabled=True,
                interval=30,
                epoch=TARGET_EPOCH,
            )
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "ACCEPTED")

    def test_activation_contract_binds_prior_baseline_and_exact_3_of_3(self):
        value = self.rolling_fixture()
        activation_epoch = TARGET_EPOCH + 300
        value.update(
            {
                "evidence_updated_count": 3,
                "requested_slot_epoch_seconds": activation_epoch,
                "baseline_slot_epoch_seconds": TARGET_EPOCH,
                "observed_unix_time": activation_epoch - 180,
                "finality_activation_contract": True,
            }
        )
        for index in range(3):
            instance_id = f"i-{index + 10:017x}"
            self.set_target(
                value["evidence_validators"][index],
                instance_id=instance_id,
                enabled=True,
                interval=30,
                epoch=TARGET_EPOCH,
            )
            self.set_target(
                value["validators"][index],
                instance_id=instance_id,
                enabled=False,
                interval=0,
                epoch=activation_epoch,
            )

        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_FINALITY_ENABLE")

        enabled = copy.deepcopy(value)
        for validator in enabled["validators"]:
            self.set_finality(
                validator,
                enabled=True,
                interval=30,
                epoch=activation_epoch,
            )
        self.assertEqual(
            evaluate_evidence_bound_rolling_compatibility(enabled)["state"],
            "ACCEPTED",
        )

        for remaining in (29, 211):
            with self.subTest(remaining=remaining):
                bounded = copy.deepcopy(value)
                bounded["observed_unix_time"] = activation_epoch - remaining
                with self.assertRaisesRegex(
                    EvidenceBoundPrefixError, "bounded safety window"
                ):
                    evaluate_evidence_bound_rolling_compatibility(bounded)

        partial = copy.deepcopy(value)
        partial["evidence_updated_count"] = 2
        partial["evidence_validators"][2] = copy.deepcopy(
            self.rolling_fixture()["evidence_validators"][2]
        )
        partial["validators"][2] = copy.deepcopy(
            self.rolling_fixture()["validators"][2]
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "exact 3/3 target runtime"
        ):
            evaluate_evidence_bound_rolling_compatibility(partial)

        malformed = copy.deepcopy(value)
        malformed["finality_activation_contract"] = "true"
        with self.assertRaisesRegex(EvidenceBoundPrefixError, "boolean"):
            evaluate_evidence_bound_rolling_compatibility(malformed)

        live_prefix = copy.deepcopy(value)
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError, "only in rolling mode"
        ):
            evaluate_live_rollout_prefix_v2(live_prefix)

    def test_resume_target_prefix_can_continue(self):
        value = self.rolling_fixture()
        value["evidence_updated_count"] = 1
        for source in (
            value["evidence_validators"][0],
            value["validators"][0],
        ):
            self.set_target(
                source,
                instance_id="i-0000000000000000a",
                enabled=False,
                interval=0,
                epoch=0,
            )
        decision = evaluate_evidence_bound_rolling_compatibility(value)
        self.assertEqual(decision["state"], "READY_FOR_NEXT_VALIDATOR")
        self.assertEqual(decision["updated_count"], 1)
        self.assertEqual(decision["baseline_updated_count"], 1)

    def test_rejects_non_target_runtime_ami_or_instance_drift(self):
        cases = (
            ("runtime_version", "d" * 64, "runtime drifted"),
            ("ami_id", EMERGENCY_AMI, "AMI binding mismatch"),
            ("instance_id", "i-0000000000000000f", "instance drifted"),
        )
        for field, invalid, message in cases:
            with self.subTest(field=field):
                value = self.rolling_fixture()
                value["validators"][1][field] = invalid
                with self.assertRaisesRegex(
                    EvidenceBoundPrefixError,
                    message,
                ):
                    evaluate_evidence_bound_rolling_compatibility(value)

    def test_rejects_target_without_instance_replacement(self):
        value = self.rolling_fixture()
        self.set_target(
            value["validators"][0],
            instance_id=value["evidence_validators"][0]["instance_id"],
            enabled=False,
            interval=0,
            epoch=0,
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError,
            "did not replace",
        ):
            evaluate_evidence_bound_rolling_compatibility(value)

    def test_rejects_mixed_finality_during_rollout(self):
        value = self.rolling_fixture()
        self.set_target(
            value["validators"][0],
            instance_id="i-0000000000000000a",
            enabled=True,
            interval=30,
            epoch=TARGET_EPOCH,
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError,
            "must remain quiesced",
        ):
            evaluate_evidence_bound_rolling_compatibility(value)

    def test_rejects_mixed_finality_after_three_targets(self):
        value = self.rolling_fixture()
        for index, validator in enumerate(value["validators"], start=10):
            self.set_target(
                validator,
                instance_id=f"i-{index:017x}",
                enabled=False,
                interval=0,
                epoch=TARGET_EPOCH,
            )
        self.set_finality(
            value["validators"][2],
            enabled=True,
            interval=30,
            epoch=TARGET_EPOCH,
        )
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError,
            "mixed or non-canonical",
        ):
            evaluate_evidence_bound_rolling_compatibility(value)

    def test_rejects_fallback_activation(self):
        value = self.rolling_fixture()
        value["fallback_active"] = True
        with self.assertRaisesRegex(
            EvidenceBoundPrefixError,
            "fallback",
        ):
            evaluate_evidence_bound_rolling_compatibility(value)


if __name__ == "__main__":
    unittest.main()
