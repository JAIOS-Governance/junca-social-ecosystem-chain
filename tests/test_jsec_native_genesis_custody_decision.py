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
    apply_native_genesis_allocation_decision,
    apply_native_genesis_custody_decision,
    evaluate_native_genesis_allocation_decision,
    evaluate_native_genesis_candidate,
    evaluate_native_genesis_custody_decision,
    evaluate_native_token_genesis_plan,
    native_economics_definition_digest,
    native_genesis_allocations_digest,
    native_genesis_custody_digest,
)
from tests.test_jsec_native_genesis_allocation_decision import (
    economics_approved_plan,
    valid_allocation_decision,
)
from tests.test_jsec_native_token_genesis import canonical, ready_plan


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jsec_native_genesis_custody_apply_decision.py"


def allocation_approved_plan() -> dict[str, object]:
    return apply_native_genesis_allocation_decision(
        economics_approved_plan(),
        evaluate_native_genesis_allocation_decision(
            valid_allocation_decision()
        ),
    )


def valid_custody_decision() -> dict[str, object]:
    plan = allocation_approved_plan()
    return {
        "schema_version": "jsec-native-genesis-custody-decision/v1",
        "official_name": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "authority": ECONOMICS_AUTHORITY,
        "decision": "approved",
        "decision_record_id": "CEO-JSEC-CUSTODY-2026-TEST-001",
        "approved_at": "2026-09-01T00:00:00Z",
        "authorization_evidence_sha256": "e" * 64,
        "approved_definition_sha256": native_economics_definition_digest(
            plan["definition"]
        ),
        "approved_allocations_sha256": native_genesis_allocations_digest(
            plan["allocations"]["accounts"]
        ),
        "custody": {
            "locked": True,
            "control_model": "institutional-multisig",
            "threshold": 2,
            "participants": [
                "0x" + ("3" * 40),
                "0x" + ("4" * 40),
                "0x" + ("5" * 40),
            ],
            "key_ceremony_evidence_sha256": "f" * 64,
        },
        "constraints": {
            "asset_class": "native-token",
            "issuance_event": "mainnet-genesis",
            "target_genesis_date": "2026-10-01",
            "contract_token_dependency": False,
            "contract_address": None,
            "secret_material_in_record": False,
            "safety": {
                "mainnet_changed": False,
                "genesis_applied": False,
                "assets_moved": False,
                "bridge_activated": False,
                "mainnet_activation_authorized": False,
            },
        },
    }


class NativeGenesisCustodyDecisionTests(unittest.TestCase):
    def test_verified_decision_binds_prior_approvals_and_ceremony(self) -> None:
        decision = evaluate_native_genesis_custody_decision(
            valid_custody_decision()
        )
        evidence = decision.as_evidence()
        self.assertEqual(
            evidence["state"],
            "VERIFIED_CEO_GENESIS_CUSTODY_DECISION",
        )
        self.assertEqual(evidence["authority"], ECONOMICS_AUTHORITY)
        self.assertEqual(evidence["control_model"], "institutional-multisig")
        self.assertEqual(evidence["threshold"], 2)
        self.assertEqual(evidence["participant_count"], 3)
        self.assertEqual(len(evidence["approved_custody_sha256"]), 64)
        self.assertEqual(len(evidence["decision_record_sha256"]), 64)
        self.assertFalse(evidence["secret_material_in_record"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["genesis_applied"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])

    def test_decision_applies_only_custody_gate_and_milestone(self) -> None:
        source = allocation_approved_plan()
        decision = evaluate_native_genesis_custody_decision(
            valid_custody_decision()
        )
        updated = apply_native_genesis_custody_decision(source, decision)
        plan = evaluate_native_token_genesis_plan(updated)

        self.assertTrue(updated["custody"]["locked"])
        self.assertEqual(updated["custody_approval"]["status"], "approved")
        self.assertEqual(
            updated["custody_approval"]["approved_custody_sha256"],
            decision.approved_custody_sha256,
        )
        self.assertTrue(updated["gates"]["custody_key_ceremony"])
        self.assertFalse(updated["gates"]["independent_security_review"])
        self.assertFalse(updated["gates"]["disaster_recovery_rehearsal"])
        self.assertEqual(updated["milestones"][2]["status"], "completed")
        self.assertNotIn("institutional-custody", plan.blockers)
        self.assertNotIn("institutional-custody-approval", plan.blockers)
        self.assertIn("independent_security_review", plan.blockers)
        self.assertFalse(updated["safety"]["mainnet_changed"])
        self.assertFalse(updated["safety"]["genesis_applied"])
        self.assertFalse(updated["safety"]["assets_moved"])
        self.assertFalse(updated["safety"]["bridge_activated"])
        self.assertFalse(updated["safety"]["mainnet_activation_authorized"])

    def test_decision_requires_approved_allocations(self) -> None:
        decision = evaluate_native_genesis_custody_decision(
            valid_custody_decision()
        )
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "requires locked Genesis allocations",
        ):
            apply_native_genesis_custody_decision(
                economics_approved_plan(),
                decision,
            )
        with self.assertRaises(NativeTokenGenesisError):
            apply_native_genesis_custody_decision(canonical(), decision)

    def test_same_decision_is_idempotent_and_conflict_is_rejected(self) -> None:
        decision = evaluate_native_genesis_custody_decision(
            valid_custody_decision()
        )
        first = apply_native_genesis_custody_decision(
            allocation_approved_plan(),
            decision,
        )
        second = apply_native_genesis_custody_decision(first, decision)
        self.assertEqual(first, second)

        conflict = allocation_approved_plan()
        conflict["custody"] = {
            "locked": True,
            "control_model": "institutional-multisig",
            "threshold": 2,
            "participants": [
                "0x" + ("6" * 40),
                "0x" + ("7" * 40),
                "0x" + ("8" * 40),
            ],
            "key_ceremony_evidence_sha256": "a" * 64,
        }
        conflict["custody_approval"] = {
            "authority": ECONOMICS_AUTHORITY,
            "status": "approved",
            "decision_record_id": "CEO-JSEC-CUSTODY-CONFLICT",
            "approved_definition_sha256": native_economics_definition_digest(
                conflict["definition"]
            ),
            "approved_allocations_sha256": native_genesis_allocations_digest(
                conflict["allocations"]["accounts"]
            ),
            "approved_custody_sha256": native_genesis_custody_digest(
                conflict["custody"]
            ),
            "decision_record_sha256": "b" * 64,
            "approved_at": "2026-09-01T00:00:00Z",
        }
        conflict["gates"]["custody_key_ceremony"] = True
        conflict["milestones"][2]["status"] = "completed"
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "conflicts with existing custody",
        ):
            apply_native_genesis_custody_decision(conflict, decision)

        prefilled = allocation_approved_plan()
        prefilled["custody"]["participants"] = [
            "0x" + ("6" * 40),
            "0x" + ("7" * 40),
            "0x" + ("8" * 40),
        ]
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "conflicts with existing custody",
        ):
            apply_native_genesis_custody_decision(prefilled, decision)

    def test_decision_rejects_drift_shadow_fields_and_secrets(self) -> None:
        cases = {
            "authority": lambda value: value.__setitem__("authority", "Other"),
            "participant_order": lambda value: value["custody"][
                "participants"
            ].reverse(),
            "threshold": lambda value: value["custody"].__setitem__(
                "threshold", 4
            ),
            "definition": lambda value: value.__setitem__(
                "approved_definition_sha256", "bad"
            ),
            "allocations": lambda value: value.__setitem__(
                "approved_allocations_sha256", "bad"
            ),
            "safety": lambda value: value["constraints"]["safety"].__setitem__(
                "assets_moved", True
            ),
            "shadow": lambda value: value.__setitem__("alternate_custody", {}),
            "secret": lambda value: value["custody"].__setitem__(
                "secret_value", "prohibited"
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                value = copy.deepcopy(valid_custody_decision())
                mutate(value)
                with self.assertRaises(NativeTokenGenesisError):
                    evaluate_native_genesis_custody_decision(value)

    def test_plan_rejects_custody_approval_digest_drift(self) -> None:
        decision = evaluate_native_genesis_custody_decision(
            valid_custody_decision()
        )
        value = apply_native_genesis_custody_decision(
            allocation_approved_plan(),
            decision,
        )
        value["custody"]["participants"][2] = "0x" + ("9" * 40)
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "custody digest does not match",
        ):
            evaluate_native_token_genesis_plan(value)

    def test_candidate_rejects_custody_approval_drift(self) -> None:
        plan = evaluate_native_token_genesis_plan(ready_plan())
        candidate = plan.genesis_candidate()
        candidate["custody_approval"]["approved_custody_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            NativeTokenGenesisError,
            "custody digest does not match",
        ):
            evaluate_native_genesis_candidate(candidate)

    def test_cli_writes_valid_non_activated_plan_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "allocation-approved-plan.json"
            decision_path = root / "custody-decision.json"
            output_path = root / "plan.json"
            evidence_path = root / "evidence.json"
            plan_path.write_text(
                json.dumps(allocation_approved_plan(), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            decision_path.write_text(
                json.dumps(valid_custody_decision(), indent=2, sort_keys=True)
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
                "institutional-custody",
                evidence["remaining_blockers"],
            )
            self.assertIn(
                "independent_security_review",
                evidence["remaining_blockers"],
            )
            self.assertFalse(evidence["mainnet_changed"])
            self.assertFalse(evidence["mainnet_activation_authorized"])

    def test_cli_rejects_input_output_aliasing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            decision_path = root / "decision.json"
            evidence_path = root / "evidence.json"
            plan_path.write_text("{}\n", encoding="utf-8")
            decision_path.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                (
                    sys.executable,
                    str(SCRIPT),
                    "--plan",
                    str(plan_path),
                    "--decision",
                    str(decision_path),
                    "--output",
                    str(plan_path),
                    "--evidence-output",
                    str(evidence_path),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must be distinct", result.stderr)


if __name__ == "__main__":
    unittest.main()
