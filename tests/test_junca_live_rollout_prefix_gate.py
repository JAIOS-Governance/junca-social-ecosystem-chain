from __future__ import annotations

import copy
import unittest

from scripts.junca_live_rollout_prefix_gate import (
    EvidenceBoundPrefixError,
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
        return value

    @staticmethod
    def set_target(validator, *, instance_id: str):
        validator.update(
            {
                "instance_id": instance_id,
                "runtime_version": TARGET,
                "ami_id": TARGET_AMI,
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": TARGET_EPOCH,
            }
        )
        for source in ("runtime_env", "health"):
            validator["finality_readback"][source].update(
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                    "slot_epoch_seconds": TARGET_EPOCH,
                }
            )

    def test_accepts_heterogeneous_evidence_bound_start(self):
        value = self.fixture()
        current = value["validators"][0]
        baseline = value["evidence_validators"][0]
        for item in (current, baseline):
            item["runtime_version"] = EMERGENCY
            item["ami_id"] = EMERGENCY_AMI
            item["automatic_finality_enabled"] = True
            item["block_interval_seconds"] = 30
            item["slot_epoch_seconds"] = 1_900_000_000
            for source in ("runtime_env", "health"):
                item["finality_readback"][source].update(
                    {
                        "automatic_finality_enabled": True,
                        "block_interval_seconds": 30,
                        "slot_epoch_seconds": 1_900_000_000,
                    }
                )

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

    def test_accepts_one_next_target_replacement(self):
        value = self.fixture()
        baseline = value["evidence_validators"][0]
        baseline["runtime_version"] = EMERGENCY
        baseline["ami_id"] = EMERGENCY_AMI
        self.set_target(
            value["validators"][0], instance_id="i-0000000000000000a"
        )

        decision = evaluate_live_rollout_prefix_v2(value)
        self.assertEqual(decision["live_updated_count"], 1)
        self.assertEqual(decision["recovered_uncommitted_count"], 1)
        self.assertEqual(decision["next_validator"], "validator-02")

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
        value["validators"][0]["automatic_finality_enabled"] = True
        value["validators"][0]["block_interval_seconds"] = 30
        value["validators"][0]["slot_epoch_seconds"] = 1_900_000_000
        for source in ("runtime_env", "health"):
            value["validators"][0]["finality_readback"][source].update(
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                    "slot_epoch_seconds": 1_900_000_000,
                }
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
            value["validators"][1], instance_id="i-0000000000000000f"
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


if __name__ == "__main__":
    unittest.main()
