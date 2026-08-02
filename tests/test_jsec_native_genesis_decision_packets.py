from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jaios.social_ecosystem_chain.native_token_genesis import (
    evaluate_native_token_genesis_plan,
    native_genesis_allocations_digest,
    native_genesis_custody_digest,
)
from tests.test_jsec_native_genesis_custody_decision import (
    allocation_approved_plan,
)
from tests.test_jsec_native_token_genesis import canonical, ready_plan


ROOT = Path(__file__).resolve().parents[1]
ALLOCATION_SCRIPT = (
    ROOT / "scripts" / "jsec_native_genesis_allocation_decision_packet.py"
)
CUSTODY_SCRIPT = (
    ROOT / "scripts" / "jsec_native_genesis_custody_decision_packet.py"
)


class NativeGenesisDecisionPacketTests(unittest.TestCase):
    def test_canonical_packets_fail_closed_without_inventing_values(self) -> None:
        plan = evaluate_native_token_genesis_plan(canonical())

        allocation = plan.allocation_decision_packet()
        self.assertEqual(allocation["status"], "approval_required")
        self.assertEqual(allocation["allocations"]["accounts"], [])
        self.assertIsNone(allocation["candidate_allocations_sha256"])
        self.assertIn("approved_native_economics", allocation["missing_decisions"])
        self.assertIn("allocations.accounts", allocation["missing_decisions"])

        custody = plan.custody_decision_packet()
        self.assertEqual(custody["status"], "approval_required")
        self.assertEqual(custody["custody"]["participants"], [])
        self.assertIsNone(custody["custody"]["threshold"])
        self.assertIsNone(custody["candidate_custody_sha256"])
        self.assertFalse(custody["constraints"]["secret_material_in_record"])
        self.assertIn("approved_native_economics", custody["missing_decisions"])
        self.assertIn(
            "approved_genesis_allocations",
            custody["missing_decisions"],
        )

    def test_allocation_packet_binds_approved_accounts(self) -> None:
        plan = evaluate_native_token_genesis_plan(allocation_approved_plan())
        packet = plan.allocation_decision_packet()
        self.assertEqual(packet["status"], "approved")
        self.assertEqual(packet["missing_decisions"], [])
        self.assertEqual(
            packet["candidate_allocations_sha256"],
            native_genesis_allocations_digest(plan.allocations),
        )
        self.assertEqual(
            packet["candidate_allocations_sha256"],
            packet["approved_allocations_sha256"],
        )
        self.assertFalse(packet["constraints"]["mainnet_changed"])
        self.assertFalse(packet["constraints"]["bridge_activated"])

    def test_custody_packet_binds_only_public_approved_material(self) -> None:
        plan = evaluate_native_token_genesis_plan(ready_plan())
        packet = plan.custody_decision_packet()
        self.assertEqual(packet["status"], "approved")
        self.assertEqual(packet["missing_decisions"], [])
        self.assertEqual(
            packet["candidate_custody_sha256"],
            native_genesis_custody_digest(plan.custody),
        )
        self.assertEqual(
            packet["candidate_custody_sha256"],
            packet["approved_custody_sha256"],
        )
        rendered = json.dumps(packet, sort_keys=True).lower()
        for marker in ("private_key", "mnemonic", "seed_phrase"):
            self.assertNotIn(marker, rendered)
        self.assertFalse(packet["constraints"]["genesis_applied"])
        self.assertFalse(packet["constraints"]["assets_moved"])

    def test_packet_clis_write_canonical_approval_required_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(canonical(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for script, output_name in (
                (ALLOCATION_SCRIPT, "allocation.json"),
                (CUSTODY_SCRIPT, "custody.json"),
            ):
                with self.subTest(script=script.name):
                    output_path = root / output_name
                    result = subprocess.run(
                        (
                            sys.executable,
                            str(script),
                            "--plan",
                            str(plan_path),
                            "--output",
                            str(output_path),
                        ),
                        cwd=ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    packet = json.loads(output_path.read_text(encoding="utf-8"))
                    self.assertEqual(packet["status"], "approval_required")
                    self.assertFalse(packet["constraints"]["mainnet_changed"])

    def test_packet_clis_require_approved_fail_closed(self) -> None:
        for script in (ALLOCATION_SCRIPT, CUSTODY_SCRIPT):
            with self.subTest(script=script.name):
                result = subprocess.run(
                    (sys.executable, str(script), "--require-approved"),
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("approval is still required", result.stderr)


if __name__ == "__main__":
    unittest.main()
