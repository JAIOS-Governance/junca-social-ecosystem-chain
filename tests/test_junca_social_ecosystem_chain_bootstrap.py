from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import (
    ChainBootstrapError,
    load_build_contract,
    load_testnet_bootstrap,
)


BUILD_PATH = Path("config/junca_social_ecosystem_chain_build_manifest.json")
BOOTSTRAP_PATH = Path("config/junca_social_ecosystem_chain_testnet_bootstrap.json")


class JuncaSocialEcosystemChainBootstrapTests(unittest.TestCase):
    def test_canonical_build_contract_is_pinned_to_legacy_source(self) -> None:
        contract = load_build_contract(BUILD_PATH)

        self.assertEqual(
            contract.commit,
            "a3e47b6a96c36378606764c35cfcdb2de97cb685",
        )
        self.assertEqual(contract.tag, "v0.2.8")
        self.assertEqual(contract.build_status, "pending-toolchain")
        self.assertEqual(contract.as_evidence()["contract_status"], "valid")

    def test_public_release_cannot_bypass_build_gates(self) -> None:
        raw = json.loads(BUILD_PATH.read_text(encoding="utf-8"))
        raw["release_gates"]["public_release_allowed"] = True

        with self.assertRaisesRegex(ChainBootstrapError, "public_release_allowed"):
            self._load(raw, load_build_contract)

    def test_sovereign_testnet_is_scaled_and_private(self) -> None:
        plan = load_testnet_bootstrap(BOOTSTRAP_PATH)

        self.assertEqual(plan.release_stage, "private-bootstrap")
        self.assertEqual(plan.chain_id_status, "private-candidate")
        self.assertEqual(plan.validator_count, 9)
        self.assertEqual(plan.validator_quorum, 7)
        self.assertEqual(plan.bootnode_count, 5)
        self.assertEqual(plan.rpc_node_count, 6)
        self.assertEqual(
            plan.as_evidence()["deployment_status"],
            "pending-new-infrastructure-and-keys",
        )

    def test_unregistered_chain_id_cannot_be_public(self) -> None:
        raw = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
        raw["chain_identity"]["public_use_allowed"] = True

        with self.assertRaisesRegex(ChainBootstrapError, "public_use_allowed"):
            self._load(raw, load_testnet_bootstrap)

    def test_legacy_key_reuse_is_rejected(self) -> None:
        raw = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
        raw["custody"]["legacy_key_reuse"] = True

        with self.assertRaisesRegex(ChainBootstrapError, "legacy_key_reuse"):
            self._load(raw, load_testnet_bootstrap)

    def test_quorum_must_exceed_seventy_five_percent(self) -> None:
        raw = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
        raw["topology"]["validator_quorum"] = 6

        with self.assertRaisesRegex(ChainBootstrapError, "quorum"):
            self._load(raw, load_testnet_bootstrap)

    @staticmethod
    def _load(raw: dict[str, object], loader):
        with TemporaryDirectory() as directory:
            path = Path(directory, "config.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return loader(path)


if __name__ == "__main__":
    unittest.main()
