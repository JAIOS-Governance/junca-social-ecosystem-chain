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
    evaluate_native_economics_decision,
    evaluate_native_token_genesis_plan,
)
from tests.test_jsec_native_token_genesis import CONFIG, canonical


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jsec_native_economics_apply_decision.py"


def valid_decision() -> dict[str, object]:
    return {
        "schema_version": "jsec-native-economics-decision/v1",
        "official_name": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "authority": ECONOMICS_AUTHORITY,
        "decision": "approved",
        "decision_record_id": "CEO-JSEC-ECONOMICS-2026-TEST-001",
        "approved_at": "2026-08-06T00:00:00Z",
        "authorization_evidence_sha256": "a" * 64,
        "definition": {
            "locked": True,
            "name": "JSEC Native Test",
            "symbol": "JSEC",
            "decimals": 18,
            "total_supply_base_units": 1_000_000,
            "supply_model": "fixed",
            "post_genesis_issuance": "disabled",
            "fee_model": "burn-and-reward",
        },
        "constraints": {
            "asset_class": "native-token",
            "issuance_event": "mainnet-genesis",
            "target_genesis_date": "2026-10-01",
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


class NativeEconomicsDecisionTests(unittest.TestCase):
    def test_verified_decision_is_bound_to_definition_and_authorization(self) -> None:
        decision = evaluate_native_economics_decision(valid_decision())
        evidence = decision.as_evidence()
        self.assertEqual(
            evidence["state"], "VERIFIED_CEO_NATIVE_ECONOMICS_DECISION"
        )
        self.assertEqual(evidence["authority"], ECONOMICS_AUTHORITY)
        self.assertEqual(len(evidence["approved_definition_sha256"]), 64)
        self.assertEqual(len(evidence["decision_record_sha256"]), 64)
        self.assertEqual(evidence["authorization_evidence_sha256"], "a" * 64)
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])

    def test_decision_applies_only_native_economics_gate(self) -> None:
        source = canonical()
        decision = evaluate_native_economics_decision(valid_decision())
        updated = apply_native_economics_decision(source, decision)
        plan = evaluate_native_token_genesis_plan(updated)

        self.assertTrue(updated["definition"]["locked"])
        self.assertEqual(updated["economics_approval"]["status"], "approved")
        self.assertEqual(
            updated["economics_approval"]["decision_record_sha256"],
            decision.decision_record_sha256,
        )
        self.assertTrue(updated["gates"]["native_economics_locked"])
        self.assertFalse(updated["gates"]["deterministic_genesis_allocations"])
        self.assertEqual(updated["milestones"][0]["status"], "completed")
        self.assertEqual(updated["allocations"], source["allocations"])
        self.assertEqual(updated["custody"], source["custody"])
        self.assertNotIn("native-token-definition", plan.blockers)
        self.assertNotIn("native-economics-approval", plan.blockers)
        self.assertIn("genesis-allocations", plan.blockers)
        self.assertFalse(updated["safety"]["mainnet_changed"])
        self.assertFalse(updated["safety"]["genesis_applied"])
        self.assertFalse(updated["safety"]["assets_moved"])
        self.assertFalse(updated["safety"]["bridge_activated"])

    def test_same_decision_is_idempotent_and_conflicting_input_is_rejected(self) -> None:
        decision = evaluate_native_economics_decision(valid_decision())
        first = apply_native_economics_decision(canonical(), decision)
        second = apply_native_economics_decision(first, decision)
        self.assertEqual(first, second)

        drifted = canonical()
        drifted["definition"]["symbol"] = "OTHER"
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "conflicts with definition.symbol",
        ):
            apply_native_economics_decision(drifted, decision)

    def test_decision_rejects_authority_constraint_safety_or_shadow_drift(self) -> None:
        cases = {
            "authority": lambda value: value.__setitem__("authority", "Other"),
            "contract": lambda value: value["constraints"].__setitem__(
                "contract_token_dependency", True
            ),
            "safety": lambda value: value["constraints"]["safety"].__setitem__(
                "mainnet_changed", True
            ),
            "shadow": lambda value: value.__setitem__("alternate_supply", 1),
            "timestamp": lambda value: value.__setitem__(
                "approved_at", "2026-08-06"
            ),
            "authorization": lambda value: value.__setitem__(
                "authorization_evidence_sha256", "bad"
            ),
            "secret": lambda value: value["definition"].__setitem__(
                "name", "private_key"
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                value = copy.deepcopy(valid_decision())
                mutate(value)
                with self.assertRaises(NativeTokenGenesisError):
                    evaluate_native_economics_decision(value)

    def test_plan_rejects_shadow_safety_fields(self) -> None:
        value = canonical()
        value["safety"]["alternate_activation"] = False
        with self.assertRaisesRegex(NativeTokenGenesisError, "safety field set"):
            evaluate_native_token_genesis_plan(value)

    def test_cli_writes_valid_non_activated_plan_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            decision_path = root / "decision.json"
            output_path = root / "plan.json"
            evidence_path = root / "evidence.json"
            decision_path.write_text(
                json.dumps(valid_decision(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                (
                    sys.executable,
                    str(SCRIPT),
                    "--plan",
                    str(CONFIG),
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
                evidence["state"], "APPLIED_TO_NON_ACTIVATED_GENESIS_PLAN"
            )
            self.assertEqual(
                evidence["output_plan_sha256"],
                evaluated.specification_digest,
            )
            self.assertIn("genesis-allocations", evidence["remaining_blockers"])
            self.assertFalse(evidence["mainnet_changed"])
            self.assertFalse(evidence["mainnet_activation_authorized"])


if __name__ == "__main__":
    unittest.main()
