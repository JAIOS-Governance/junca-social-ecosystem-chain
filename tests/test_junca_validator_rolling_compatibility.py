import copy
import unittest

from jaios.social_ecosystem_chain.rolling_compatibility import (
    RollingCompatibilityError,
    evaluate_live_rollout_prefix,
    evaluate_recovery_head_compare,
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
    def live_prefix_evidence(self):
        value = evidence()
        validators = value["validators"]
        for index, validator in enumerate(validators, start=1):
            validator["instance_id"] = f"i-{index:017x}"
            validator["volume_id"] = value["rollback"]["validators"][
                index - 1
            ]["volume_id"]
        return {
            "target_version": value["target_version"],
            "target_ami_id": value["target_ami_id"],
            "previous_version": value["rollback"]["target_version"],
            "previous_ami_id": value["rollback"]["ami_id"],
            "update_order": value["update_order"],
            "evidence_updated_count": 0,
            "validators": validators,
            "evidence_validators": copy.deepcopy(validators),
            "rollback": value["rollback"],
            "requested_slot_epoch_seconds": value[
                "requested_slot_epoch_seconds"
            ],
            "observed_unix_time": value["observed_unix_time"],
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def recovery_head_evidence(self):
        base = "a" * 40
        head = "b" * 40
        return {
            "expected_base": base,
            "expected_head": head,
            "comparison": {
                "status": "ahead",
                "ahead_by": 1,
                "behind_by": 0,
                "total_commits": 1,
                "base_commit": {"sha": base},
                "merge_base_commit": {"sha": base},
                "commits": [{"sha": head}],
                "files": [
                    {
                        "filename": (
                            "scripts/junca_public_testnet_foundation.sh"
                        ),
                        "status": "modified",
                        "previous_filename": None,
                    }
                ],
            },
        }

    def test_recovery_head_accepts_only_allowlisted_descendant(self):
        value = self.recovery_head_evidence()
        decision = evaluate_recovery_head_compare(value)
        self.assertEqual(decision["state"], "RECOVERY_HEAD_ACCEPTED")
        self.assertEqual(
            decision["changed_files"],
            ["scripts/junca_public_testnet_foundation.sh"],
        )

        recovery_files = [
            ".github/workflows/junca-validator-foundation-release.yml",
            "docs/JUNCA_PUBLIC_TESTNET_RUNTIME_ACCEPTANCE_GATES.md",
            "docs/runbooks/junca-validator-rolling-update.md",
            "infra/aws/public-testnet/main.tf",
            "infra/aws/public-testnet/outputs.tf",
            "infra/aws/public-testnet/variables.tf",
            "jaios/social_ecosystem_chain/rolling_compatibility.py",
            "scripts/junca_live_rollout_prefix_gate.py",
            "scripts/junca_public_testnet_foundation.sh",
            "tests/test_junca_live_rollout_prefix_gate.py",
            "tests/test_junca_social_ecosystem_chain_aws_foundation.py",
            "tests/test_junca_validator_rolling_compatibility.py",
        ]
        value = self.recovery_head_evidence()
        value["comparison"]["files"] = [
            {
                "filename": filename,
                "status": "modified",
                "previous_filename": None,
            }
            for filename in recovery_files
        ]
        decision = evaluate_recovery_head_compare(value)
        self.assertEqual(decision["changed_files"], sorted(recovery_files))

        value["comparison"].update(
            {
                "status": "identical",
                "ahead_by": 0,
                "total_commits": 0,
                "commits": [],
                "files": [],
            }
        )
        value["expected_head"] = value["expected_base"]
        self.assertEqual(
            evaluate_recovery_head_compare(value)["state"],
            "RECOVERY_HEAD_ACCEPTED",
        )

    def test_recovery_head_uses_ordered_commits_not_head_commit(self):
        value = self.recovery_head_evidence()
        value["comparison"]["head_commit"] = {"sha": "c" * 40}
        self.assertEqual(
            evaluate_recovery_head_compare(value)["state"],
            "RECOVERY_HEAD_ACCEPTED",
        )
        del value["comparison"]["head_commit"]
        self.assertEqual(
            evaluate_recovery_head_compare(value)["state"],
            "RECOVERY_HEAD_ACCEPTED",
        )

    def test_recovery_head_rejects_invalid_ordered_commits(self):
        cases = (
            (
                [{"sha": "c" * 40}],
                1,
                "do not reach expected head",
            ),
            (
                [{"sha": "c" * 40}, {"sha": "b" * 40}],
                1,
                "do not reach expected head",
            ),
            (
                [{"sha": "b" * 40}, {"sha": "c" * 40}],
                2,
                "do not reach expected head",
            ),
            (
                [{"sha": "b" * 40}, {"sha": "b" * 40}],
                2,
                "invalid or duplicated",
            ),
        )
        for commits, ahead_by, message in cases:
            with self.subTest(commits=commits, ahead_by=ahead_by):
                value = self.recovery_head_evidence()
                value["comparison"]["commits"] = commits
                value["comparison"]["ahead_by"] = ahead_by
                value["comparison"]["total_commits"] = ahead_by
                with self.assertRaisesRegex(RollingCompatibilityError, message):
                    evaluate_recovery_head_compare(value)

    def test_recovery_head_rejects_divergence_and_unexpected_files(self):
        cases = (
            ("status", "diverged", "ahead of or identical"),
            ("behind_by", 1, "behind or diverged"),
            (
                "merge_base_commit",
                {"sha": "c" * 40},
                "exact merge base",
            ),
            (
                "files",
                [
                    {
                        "filename": "infra/aws/public-testnet/unsafe-new.tf",
                        "status": "modified",
                        "previous_filename": None,
                    }
                ],
                "outside the recovery allowlist",
            ),
            (
                "files",
                [
                    {
                        "filename": (
                            "scripts/junca_public_testnet_foundation.sh"
                        ),
                        "status": "renamed",
                        "previous_filename": "infra/aws/public-testnet/main.tf",
                    }
                ],
                "outside the recovery allowlist",
            ),
        )
        for field, invalid, message in cases:
            with self.subTest(field=field):
                value = self.recovery_head_evidence()
                value["comparison"][field] = invalid
                with self.assertRaisesRegex(RollingCompatibilityError, message):
                    evaluate_recovery_head_compare(value)

    def test_live_prefix_recovers_only_one_fully_bound_replacement(self):
        value = self.live_prefix_evidence()
        unchanged = evaluate_live_rollout_prefix(value)
        self.assertEqual(unchanged["live_updated_count"], 0)
        self.assertEqual(unchanged["recovered_uncommitted_count"], 0)

        validator = value["validators"][0]
        validator.update(
            {
                "instance_id": "i-0000000000000000a",
                "runtime_version": value["target_version"],
                "ami_id": value["target_ami_id"],
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": value["requested_slot_epoch_seconds"],
            }
        )
        for source in ("runtime_env", "health"):
            validator["finality_readback"][source].update(
                {
                    "automatic_finality_enabled": True,
                    "block_interval_seconds": 30,
                    "slot_epoch_seconds": value[
                        "requested_slot_epoch_seconds"
                    ],
                }
            )
        recovered = evaluate_live_rollout_prefix(value)
        self.assertEqual(recovered["evidence_updated_count"], 0)
        self.assertEqual(recovered["live_updated_count"], 1)
        self.assertEqual(recovered["recovered_uncommitted_count"], 1)
        self.assertEqual(recovered["next_validator"], "validator-02")

    def test_live_prefix_rejects_gap_two_ahead_and_suffix_drift(self):
        value = self.live_prefix_evidence()
        for index in (0, 1):
            validator = value["validators"][index]
            validator["instance_id"] = f"i-{index + 10:017x}"
            validator["runtime_version"] = value["target_version"]
            validator["ami_id"] = value["target_ami_id"]
        with self.assertRaisesRegex(RollingCompatibilityError, "one next"):
            evaluate_live_rollout_prefix(value)

        value = self.live_prefix_evidence()
        value["validators"][1]["instance_id"] = "i-0000000000000000f"
        with self.assertRaisesRegex(
            RollingCompatibilityError, "outside the recoverable"
        ):
            evaluate_live_rollout_prefix(value)

        value = self.live_prefix_evidence()
        value["validators"][1]["runtime_version"] = value["target_version"]
        value["validators"][1]["ami_id"] = value["target_ami_id"]
        value["validators"][1]["instance_id"] = "i-0000000000000000f"
        with self.assertRaisesRegex(RollingCompatibilityError, "order"):
            evaluate_live_rollout_prefix(value)

    def test_live_prefix_requires_exact_candidate_epoch_and_provenance(self):
        value = self.live_prefix_evidence()
        validator = value["validators"][0]
        validator.update(
            {
                "instance_id": "i-0000000000000000a",
                "runtime_version": value["target_version"],
                "ami_id": value["target_ami_id"],
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": value["requested_slot_epoch_seconds"] + 30,
            }
        )
        validator["finality_readback"]["runtime_env"].update(
            {
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": value["requested_slot_epoch_seconds"] + 30,
            }
        )
        validator["finality_readback"]["health"].update(
            {
                "automatic_finality_enabled": True,
                "block_interval_seconds": 30,
                "slot_epoch_seconds": value["requested_slot_epoch_seconds"] + 30,
            }
        )
        with self.assertRaisesRegex(RollingCompatibilityError, "epoch drifted"):
            evaluate_live_rollout_prefix(value)

        value = self.live_prefix_evidence()
        value["validators"][0]["volume_id"] = "vol-0000000000000000f"
        with self.assertRaisesRegex(RollingCompatibilityError, "volume binding"):
            evaluate_live_rollout_prefix(value)

        value = self.live_prefix_evidence()
        value["rollback"]["validators"][0]["head_height"] = 8
        value["rollback"]["validators"][0]["certificate_height"] = 8
        with self.assertRaisesRegex(RollingCompatibilityError, "rewind"):
            evaluate_live_rollout_prefix(value)

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

    def test_near_term_activation_window_requires_exact_3_of_3_contract(self):
        value = evidence()
        value["requested_slot_epoch_seconds"] = 2_000_000_000
        value["observed_unix_time"] = 1_999_999_850
        for validator in value["validators"]:
            validator["runtime_version"] = "v2"
            validator["ami_id"] = "ami-22222222222222222"
            validator["slot_epoch_seconds"] = 2_000_000_000
            validator["finality_readback"]["runtime_env"][
                "slot_epoch_seconds"
            ] = 2_000_000_000
            validator["finality_readback"]["health"][
                "slot_epoch_seconds"
            ] = 2_000_000_000

        with self.assertRaisesRegex(
            RollingCompatibilityError, "bounded safety window"
        ):
            evaluate_rolling_compatibility(value)

        value["finality_activation_contract"] = True
        self.assertEqual(
            evaluate_rolling_compatibility(value)["state"],
            "READY_FOR_FINALITY_ENABLE",
        )

        for remaining in (29, 211):
            with self.subTest(remaining=remaining):
                bounded = copy.deepcopy(value)
                bounded["observed_unix_time"] = (
                    bounded["requested_slot_epoch_seconds"] - remaining
                )
                with self.assertRaisesRegex(
                    RollingCompatibilityError, "bounded safety window"
                ):
                    evaluate_rolling_compatibility(bounded)

        partial = copy.deepcopy(value)
        partial["validators"][2]["runtime_version"] = "v1"
        partial["validators"][2]["ami_id"] = "ami-11111111111111111"
        partial["validators"][2]["slot_epoch_seconds"] = 0
        partial["validators"][2]["finality_readback"]["runtime_env"][
            "slot_epoch_seconds"
        ] = 0
        partial["validators"][2]["finality_readback"]["health"][
            "slot_epoch_seconds"
        ] = 0
        with self.assertRaisesRegex(
            RollingCompatibilityError, "exact 3/3 target runtime"
        ):
            evaluate_rolling_compatibility(partial)

        malformed = copy.deepcopy(value)
        malformed["finality_activation_contract"] = "true"
        with self.assertRaisesRegex(RollingCompatibilityError, "boolean"):
            evaluate_rolling_compatibility(malformed)

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
