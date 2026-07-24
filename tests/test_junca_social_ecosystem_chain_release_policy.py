from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import ChainReleasePolicyError, load_release_policy


POLICY_PATH = Path("config/junca_social_ecosystem_chain_release_policy.json")


class JuncaSocialEcosystemChainReleasePolicyTests(unittest.TestCase):
    def test_canonical_policy_uses_institutional_governance(self) -> None:
        policy = load_release_policy(POLICY_PATH)

        self.assertEqual(policy.release_model, "institutional-governance")
        self.assertEqual(policy.governance_entity, "JAIOS Institutional Governance")
        self.assertEqual(policy.issuance_management, "JAIOS Institutional Governance")
        self.assertEqual(policy.testnet_label, "Public Testnet / No Monetary Value")
        self.assertEqual(policy.source_repository, "juncaGlobal/junca-Project")
        self.assertEqual(policy.brand, "JUNCA Social Ecosystem Chain")
        self.assertEqual(policy.testnet_strategy, "new-genesis")
        self.assertEqual(
            policy.mainnet_strategy,
            "snapshot-audit-before-continuity-decision",
        )
        self.assertEqual(policy.as_evidence()["release_status"], "pending-runtime-evidence")

    def test_personal_control_release_model_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["release_model"] = "ceo-sovereign"
        with self.assertRaisesRegex(ChainReleasePolicyError, "personal-control"):
            self._load(raw)

    def test_personal_control_operator_wording_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["authority"]["operator_model"] = "ceo-controlled"
        with self.assertRaisesRegex(ChainReleasePolicyError, "personal-control"):
            self._load(raw)

    def test_ambiguous_governance_entity_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["authority"]["public_governance_entity"] = "management"
        with self.assertRaisesRegex(ChainReleasePolicyError, "public_governance_entity"):
            self._load(raw)

    def test_inaccurate_decentralization_claim_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["public_representation"]["decentralization_claims"] = "unrestricted"
        with self.assertRaisesRegex(ChainReleasePolicyError, "decentralization_claims"):
            self._load(raw)

    def test_former_team_dependency_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["authority"]["former_team_dependency"] = "required"
        with self.assertRaisesRegex(ChainReleasePolicyError, "former_team_dependency"):
            self._load(raw)

    def test_legacy_key_reuse_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["asset_policy"]["legacy_keys"] = "allowed"
        with self.assertRaisesRegex(ChainReleasePolicyError, "legacy_keys"):
            self._load(raw)

    def test_sensitive_fields_are_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["authority"]["private_key"] = "not-a-real-key"
        with self.assertRaisesRegex(ChainReleasePolicyError, "sensitive field"):
            self._load(raw)

    def test_missing_release_control_is_rejected(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["required_controls"].remove("rollback-package")
        with self.assertRaisesRegex(ChainReleasePolicyError, "rollback-package"):
            self._load(raw)

    def test_legacy_chain_id_reuse_requires_later_decision(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["network_strategy"]["reuse_legacy_chain_id_before_decision"] = True
        with self.assertRaisesRegex(ChainReleasePolicyError, "chain IDs"):
            self._load(raw)

    def test_former_brand_is_rejected_as_current_brand(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        raw["network_strategy"]["brand"] = "JUNCA Global Chain"
        with self.assertRaisesRegex(ChainReleasePolicyError, "brand"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "policy.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_release_policy(path)


if __name__ == "__main__":
    unittest.main()
