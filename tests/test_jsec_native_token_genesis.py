from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import unittest

from jaios.social_ecosystem_chain.native_token_genesis import (
    ECONOMICS_AUTHORITY,
    NativeTokenGenesisError,
    TARGET_GENESIS_DATE,
    evaluate_native_token_genesis_plan,
    load_native_token_genesis_plan,
    native_economics_definition_digest,
)


CONFIG = Path("config/jsec_native_token_genesis_plan_v1.json")


def canonical() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def ready_plan() -> dict[str, object]:
    value = canonical()
    value["definition"] = {
        "locked": True,
        "name": "JSEC Native Test",
        "symbol": "JSEC",
        "decimals": 18,
        "total_supply_base_units": 1_000_000,
        "supply_model": "fixed",
        "post_genesis_issuance": "disabled",
        "fee_model": "burn-and-reward",
    }
    value["economics_approval"] = {
        "authority": ECONOMICS_AUTHORITY,
        "status": "approved",
        "decision_record_id": "CEO-JSEC-ECONOMICS-2026-001",
        "approved_definition_sha256": native_economics_definition_digest(
            value["definition"]
        ),
        "decision_record_sha256": "b" * 64,
        "approved_at": "2026-08-06T00:00:00Z",
    }
    value["allocations"] = {
        "locked": True,
        "accounts": [
            {
                "address": "0x" + ("1" * 40),
                "amount_base_units": 600_000,
                "category": "treasury",
            },
            {
                "address": "0x" + ("2" * 40),
                "amount_base_units": 400_000,
                "category": "ecosystem",
            },
        ],
    }
    value["custody"] = {
        "locked": True,
        "control_model": "institutional-multisig",
        "threshold": 2,
        "participants": [
            "0x" + ("3" * 40),
            "0x" + ("4" * 40),
            "0x" + ("5" * 40),
        ],
        "key_ceremony_evidence_sha256": "a" * 64,
    }
    value["gates"] = {name: True for name in value["gates"]}
    for milestone in value["milestones"]:
        milestone["status"] = "completed"
    return value


class NativeTokenGenesisTests(unittest.TestCase):
    def test_canonical_plan_locks_october_target_without_activation(self) -> None:
        plan = load_native_token_genesis_plan(CONFIG)
        evidence = plan.as_evidence(date(2026, 8, 1))
        self.assertEqual(plan.target_date, TARGET_GENESIS_DATE)
        self.assertEqual(evidence["target_genesis_date"], "2026-10-01")
        self.assertTrue(evidence["target_date_locked"])
        self.assertEqual(evidence["schedule_state"], "ON_TRACK")
        self.assertEqual(
            evidence["next_milestone"],
            {
                "id": "native_economics_constitution",
                "due_date": "2026-08-07",
            },
        )
        self.assertFalse(evidence["contract_token_dependency"])
        self.assertNotIn("bridge_dependency", evidence)
        self.assertNotIn("bridge_dependency", canonical())
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["genesis_applied"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])
        self.assertFalse(evidence["mainnet_activation_authorized"])
        packet = plan.economics_decision_packet()
        self.assertEqual(packet["status"], "approval_required")
        self.assertEqual(packet["authority_required"], ECONOMICS_AUTHORITY)
        self.assertEqual(
            packet["missing_decisions"],
            [
                "name",
                "symbol",
                "decimals",
                "total_supply_base_units",
                "supply_model",
                "post_genesis_issuance",
                "fee_model",
            ],
        )
        self.assertFalse(packet["constraints"]["mainnet_changed"])
        self.assertFalse(packet["constraints"]["assets_moved"])
        self.assertFalse(packet["constraints"]["bridge_activated"])

    def test_overdue_milestone_fails_schedule_gate_without_date_shift(self) -> None:
        plan = load_native_token_genesis_plan(CONFIG)
        as_of = date(2026, 8, 8)
        self.assertEqual(plan.schedule_state(as_of), "AT_RISK")
        self.assertEqual(
            plan.overdue_milestones(as_of),
            ("native_economics_constitution",),
        )
        with self.assertRaisesRegex(NativeTokenGenesisError, "AT_RISK"):
            plan.assert_on_track(as_of)
        self.assertEqual(plan.target_date, TARGET_GENESIS_DATE)

    def test_rejects_target_or_milestone_date_slippage(self) -> None:
        for mutate in ("target", "milestone"):
            with self.subTest(mutate=mutate):
                value = canonical()
                if mutate == "target":
                    value["target_genesis_date"] = "2026-11-30"
                else:
                    value["milestones"][0]["due_date"] = "2026-08-08"
                with self.assertRaises(NativeTokenGenesisError):
                    evaluate_native_token_genesis_plan(value)

    def test_rejects_contract_token_dependency(self) -> None:
        value = canonical()
        value["contract_token_dependency"] = True
        with self.assertRaises(NativeTokenGenesisError):
            evaluate_native_token_genesis_plan(value)

    def test_gate_cannot_pass_without_underlying_evidence(self) -> None:
        cases = (
            "native_economics_locked",
            "deterministic_genesis_allocations",
            "custody_key_ceremony",
        )
        for gate in cases:
            with self.subTest(gate=gate):
                value = canonical()
                value["gates"][gate] = True
                with self.assertRaises(NativeTokenGenesisError):
                    evaluate_native_token_genesis_plan(value)

    def test_ready_plan_is_ceremony_ready_but_does_not_activate_mainnet(self) -> None:
        plan = evaluate_native_token_genesis_plan(ready_plan())
        plan.assert_ready_for_genesis_ceremony()
        evidence = plan.as_evidence(date(2026, 10, 1))
        self.assertEqual(evidence["schedule_state"], "READY_FOR_CEREMONY")
        self.assertEqual(evidence["blockers"], [])
        self.assertFalse(evidence["mainnet_activation_authorized"])
        self.assertFalse(evidence["genesis_applied"])
        self.assertFalse(evidence["assets_moved"])
        self.assertEqual(evidence["native_economics"]["status"], "approved")

    def test_approved_plan_compiles_deterministic_non_activated_genesis(self) -> None:
        first = evaluate_native_token_genesis_plan(ready_plan()).genesis_candidate()
        second = evaluate_native_token_genesis_plan(ready_plan()).genesis_candidate()
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "jsec-native-genesis-candidate/v1")
        self.assertEqual(first["target_genesis_date"], "2026-10-01")
        self.assertEqual(first["definition"]["symbol"], "JSEC")
        self.assertEqual(
            sum(item["amount_base_units"] for item in first["allocations"]),
            first["definition"]["total_supply_base_units"],
        )
        self.assertEqual(len(first["allocations_sha256"]), 64)
        self.assertEqual(len(first["custody_sha256"]), 64)
        self.assertFalse(first["safety"]["mainnet_changed"])
        self.assertFalse(first["safety"]["genesis_applied"])
        self.assertFalse(first["safety"]["assets_moved"])
        self.assertFalse(first["safety"]["bridge_activated"])

    def test_unapproved_plan_cannot_compile_genesis_candidate(self) -> None:
        with self.assertRaisesRegex(NativeTokenGenesisError, "ceremony blocked"):
            load_native_token_genesis_plan(CONFIG).genesis_candidate()

    def test_economics_approval_is_bound_to_exact_definition(self) -> None:
        value = ready_plan()
        value["definition"]["decimals"] = 8
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "definition digest does not match",
        ):
            evaluate_native_token_genesis_plan(value)

    def test_rejects_shadow_economics_fields(self) -> None:
        value = canonical()
        value["definition"]["hidden_mint_policy"] = "enabled"
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "definition field set mismatch",
        ):
            evaluate_native_token_genesis_plan(value)

        value = canonical()
        value["economics_approval"]["alternate_authority"] = "unapproved"
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "approval field set mismatch",
        ):
            evaluate_native_token_genesis_plan(value)

    def test_rejects_locked_economics_without_ceo_approval(self) -> None:
        value = canonical()
        value["definition"] = ready_plan()["definition"]
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "requires approved economics",
        ):
            evaluate_native_token_genesis_plan(value)

    def test_supply_and_allocations_must_match_exactly(self) -> None:
        value = ready_plan()
        value["allocations"]["accounts"][0]["amount_base_units"] += 1
        with self.assertRaisesRegex(NativeTokenGenesisError, "equal native total supply"):
            evaluate_native_token_genesis_plan(value)

    def test_completed_milestone_requires_gate_evidence(self) -> None:
        value = canonical()
        value["milestones"][3]["status"] = "completed"
        with self.assertRaisesRegex(NativeTokenGenesisError, "lacks gate evidence"):
            evaluate_native_token_genesis_plan(value)

    def test_secret_material_markers_are_rejected(self) -> None:
        value = canonical()
        value["custody"]["private_key"] = "prohibited"
        with self.assertRaisesRegex(NativeTokenGenesisError, "secret material"):
            evaluate_native_token_genesis_plan(value)

    def test_input_mutation_does_not_change_locked_schedule(self) -> None:
        value = ready_plan()
        duplicate = copy.deepcopy(value)
        duplicate["custody"]["participants"][1] = duplicate["custody"]["participants"][0]
        with self.assertRaisesRegex(NativeTokenGenesisError, "unique"):
            evaluate_native_token_genesis_plan(duplicate)


if __name__ == "__main__":
    unittest.main()
