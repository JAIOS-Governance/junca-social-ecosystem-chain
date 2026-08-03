from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jaios.social_ecosystem_chain.native_token_genesis import (
    ECONOMICS_AUTHORITY,
    NativeTokenGenesisError,
    apply_native_economics_decision,
    apply_native_genesis_allocation_decision,
    evaluate_native_economics_decision,
    evaluate_native_genesis_allocation_decision,
    evaluate_native_token_genesis_plan,
    native_economics_definition_digest,
)
from tests.test_jsec_native_economics_decision import valid_decision
from tests.test_jsec_native_token_genesis import CONFIG, canonical


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jsec_native_genesis_allocation_apply_decision.py"


def economics_approved_plan() -> dict[str, object]:
    return apply_native_economics_decision(
        canonical(),
        evaluate_native_economics_decision(valid_decision()),
    )


def valid_allocation_decision() -> dict[str, object]:
    definition = valid_decision()["definition"]
    return {
        "schema_version": "jsec-native-genesis-allocation-decision/v1",
        "official_name": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "authority": ECONOMICS_AUTHORITY,
        "decision": "approved",
        "decision_record_id": "CEO-JSEC-ALLOCATIONS-2026-TEST-001",
        "approved_at": "2026-08-20T00:00:00Z",
        "authorization_evidence_sha256": "d" * 64,
        "approved_definition_sha256": native_economics_definition_digest(
            definition
        ),
        "allocations": [
            {
                "address": "0x" + ("1" * 40),
                "amount_base_units": 600_000,
                "category": "treasury-test",
            },
            {
                "address": "0x" + ("2" * 40),
                "amount_base_units": 400_000,
                "category": "ecosystem-test",
            },
        ],
        "constraints": {
            "asset_class": "native-token",
            "issuance_event": "mainnet-genesis",
            "target_genesis_date": "2026-10-01",
            "total_supply_base_units": 1_000_000,
            "contract_token_dependency": False,
            "contract_address": None,
            "safety": {
                "mainnet_changed": False,
                "genesis_applied": False,
                "assets_moved": False,
                "bridge_activated": False,
                "mainnet_activation_authorized": False,
            },
        },
    }


class NativeGenesisAllocationDecisionTests(unittest.TestCase):
    def test_verified_decision_binds_definition_accounts_and_authorization(
        self,
    ) -> None:
        decision = evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        )
        evidence = decision.as_evidence()
        self.assertEqual(
            evidence["state"],
            "VERIFIED_CEO_GENESIS_ALLOCATION_DECISION",
        )
        self.assertEqual(evidence["authority"], ECONOMICS_AUTHORITY)
        self.assertEqual(evidence["allocation_count"], 2)
        self.assertEqual(evidence["total_supply_base_units"], 1_000_000)
        self.assertEqual(len(evidence["approved_allocations_sha256"]), 64)
        self.assertEqual(len(evidence["decision_record_sha256"]), 64)
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["genesis_applied"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])

    def test_decision_applies_only_deterministic_allocation_gate(self) -> None:
        source = economics_approved_plan()
        decision = evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        )
        updated = apply_native_genesis_allocation_decision(source, decision)
        plan = evaluate_native_token_genesis_plan(updated)

        self.assertTrue(updated["allocations"]["locked"])
        self.assertEqual(updated["allocations"]["status"], "approved")
        self.assertEqual(
            updated["allocations"]["decision_record_sha256"],
            decision.decision_record_sha256,
        )
        self.assertTrue(
            updated["gates"]["deterministic_genesis_allocations"]
        )
        self.assertFalse(updated["gates"]["custody_key_ceremony"])
        self.assertEqual(updated["milestones"][1]["status"], "completed")
        self.assertEqual(updated["custody"], source["custody"])
        self.assertNotIn("genesis-allocations", plan.blockers)
        self.assertIn("institutional-custody", plan.blockers)
        self.assertFalse(updated["safety"]["mainnet_changed"])
        self.assertFalse(updated["safety"]["genesis_applied"])
        self.assertFalse(updated["safety"]["assets_moved"])
        self.assertFalse(updated["safety"]["bridge_activated"])

    def test_decision_requires_approved_native_economics(self) -> None:
        decision = evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        )
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "requires locked native economics",
        ):
            apply_native_genesis_allocation_decision(canonical(), decision)

    def test_same_decision_is_idempotent_and_conflict_is_rejected(self) -> None:
        decision = evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        )
        first = apply_native_genesis_allocation_decision(
            economics_approved_plan(),
            decision,
        )
        second = apply_native_genesis_allocation_decision(first, decision)
        self.assertEqual(first, second)

        conflict = economics_approved_plan()
        conflict["allocations"]["accounts"] = [
            {
                "address": "0x" + ("3" * 40),
                "amount_base_units": 1_000_000,
                "category": "conflict-test",
            }
        ]
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "conflicts with existing accounts",
        ):
            apply_native_genesis_allocation_decision(conflict, decision)

    def test_decision_rejects_drift_shadow_fields_and_secret_markers(self) -> None:
        cases = {
            "authority": lambda value: value.__setitem__("authority", "Other"),
            "order": lambda value: value["allocations"].reverse(),
            "total": lambda value: value["constraints"].__setitem__(
                "total_supply_base_units", 999_999
            ),
            "definition": lambda value: value.__setitem__(
                "approved_definition_sha256", "bad"
            ),
            "safety": lambda value: value["constraints"]["safety"].__setitem__(
                "assets_moved", True
            ),
            "shadow": lambda value: value.__setitem__(
                "alternate_allocation", []
            ),
            "secret": lambda value: value["allocations"][0].__setitem__(
                "category", "private_key"
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                value = copy.deepcopy(valid_allocation_decision())
                mutate(value)
                with self.assertRaises(NativeTokenGenesisError):
                    evaluate_native_genesis_allocation_decision(value)

    def test_plan_rejects_allocation_approval_digest_drift(self) -> None:
        decision = evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        )
        value = apply_native_genesis_allocation_decision(
            economics_approved_plan(),
            decision,
        )
        value["allocations"]["accounts"][0]["category"] = "tampered"
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "allocation digest does not match",
        ):
            evaluate_native_token_genesis_plan(value)

    def test_cli_writes_valid_non_activated_plan_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "economics-approved-plan.json"
            decision_path = root / "allocation-decision.json"
            output_path = root / "plan.json"
            evidence_path = root / "evidence.json"
            plan_path.write_text(
                json.dumps(
                    economics_approved_plan(),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            decision_path.write_text(
                json.dumps(
                    valid_allocation_decision(),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                (
                    sys.executable,
                    str(SCRIPT),
                    "--plan",
                    str(plan_path),
                    "--decision",
                    str(decision_path),
                    "--output",
                    str(output_path),
                    "--evidence-output",
                    str(evidence_path),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(output_path.read_text(encoding="utf-8"))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evaluated = evaluate_native_token_genesis_plan(output)
            self.assertEqual(
                evidence["state"],
                "APPLIED_TO_NON_ACTIVATED_GENESIS_PLAN",
            )
            self.assertEqual(
                evidence["output_plan_sha256"],
                evaluated.specification_digest,
            )
            self.assertNotIn(
                "genesis-allocations",
                evidence["remaining_blockers"],
            )
            self.assertIn(
                "institutional-custody",
                evidence["remaining_blockers"],
            )
            self.assertFalse(evidence["mainnet_changed"])
            self.assertFalse(evidence["mainnet_activation_authorized"])


if __name__ == "__main__":
    unittest.main()
