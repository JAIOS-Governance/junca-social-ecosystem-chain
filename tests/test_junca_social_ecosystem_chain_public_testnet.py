from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.public_testnet import (
    PublicTestnetError,
    load_public_testnet_plan,
)


PLAN = Path("config/junca_social_ecosystem_chain_public_testnet.json")


class PublicTestnetPlanTests(unittest.TestCase):
    def test_canonical_plan_is_public_preview(self) -> None:
        plan = load_public_testnet_plan(PLAN)
        self.assertEqual(plan.release_stage, "public-preview")
        self.assertEqual(plan.audience, "public-technical-evaluation")
        self.assertEqual(plan.validator_count, 3)
        self.assertEqual(plan.issuance_management, "JAIOS Institutional Governance")
        self.assertEqual(plan.validator_quorum, 3)
        self.assertFalse(plan.mainnet)
        self.assertFalse(plan.monetary_value)
        self.assertEqual(plan.as_evidence()["deployment_status"], "pending-runtime-evidence")

    def test_investor_label_is_rejected(self) -> None:
        raw = json.loads(PLAN.read_text(encoding="utf-8"))
        raw["release_stage"] = "investor-preview"
        with self.assertRaisesRegex(PublicTestnetError, "release_stage"):
            self._load(raw)

    def test_mainnet_misrepresentation_is_rejected(self) -> None:
        raw = json.loads(PLAN.read_text(encoding="utf-8"))
        raw["mainnet"] = True
        with self.assertRaisesRegex(PublicTestnetError, "mainnet"):
            self._load(raw)

    def test_legacy_key_reuse_is_rejected(self) -> None:
        raw = json.loads(PLAN.read_text(encoding="utf-8"))
        raw["legacy_key_reuse"] = True
        with self.assertRaisesRegex(PublicTestnetError, "legacy key"):
            self._load(raw)

    def test_missing_public_service_is_rejected(self) -> None:
        raw = json.loads(PLAN.read_text(encoding="utf-8"))
        del raw["services"]["faucet"]
        with self.assertRaisesRegex(PublicTestnetError, "services"):
            self._load(raw)

    def test_premature_gate_promotion_is_rejected(self) -> None:
        raw = json.loads(PLAN.read_text(encoding="utf-8"))
        raw["launch_gates"]["validator_quorum_verified"] = True
        with self.assertRaisesRegex(PublicTestnetError, "launch gates"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "plan.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_public_testnet_plan(path)


if __name__ == "__main__":
    unittest.main()
