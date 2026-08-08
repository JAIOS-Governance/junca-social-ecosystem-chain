from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.upgrade_governance import (
    GovernedUpgrade,
    UpgradeGovernanceError,
    UpgradeProposal,
    UpgradeState,
)


HASH_A = "0x" + ("11" * 32)
HASH_B = "0x" + ("22" * 32)
HASH_C = "0x" + ("33" * 32)
HASH_D = "0x" + ("44" * 32)
HASH_E = "0x" + ("55" * 32)
HASH_F = "0x" + ("66" * 32)
HASH_G = "0x" + ("77" * 32)


class UpgradeGovernanceTests(unittest.TestCase):
    def _proposal(self) -> UpgradeProposal:
        return UpgradeProposal(
            proposal_id="mainnet-upgrade-001",
            source_sha=HASH_A,
            artifact_digest=HASH_B,
            genesis_or_config_digest=HASH_C,
            protocol_version_from="junca-mainnet/v1",
            protocol_version_to="junca-mainnet/v2",
            activation_height=100_000,
            migration_digest=HASH_D,
            rollback_digest=HASH_E,
        )

    def test_independent_reviews_rehearsal_and_ceo_gate(self) -> None:
        upgrade = GovernedUpgrade(self._proposal())

        for role, digest in (
            ("protocol", HASH_A),
            ("security", HASH_B),
            ("release", HASH_C),
            ("recovery", HASH_D),
        ):
            upgrade.add_review(role, digest)

        self.assertEqual(upgrade.state, UpgradeState.REVIEWED)
        upgrade.record_rehearsal(HASH_F)
        upgrade.schedule(100_000)
        self.assertFalse(upgrade.activation_authorized)
        upgrade.record_ceo_final_approval(True)

        self.assertTrue(upgrade.activation_authorized)
        self.assertEqual(upgrade.state, UpgradeState.ACTIVATION_READY)

    def test_missing_review_blocks_rehearsal(self) -> None:
        upgrade = GovernedUpgrade(self._proposal())
        upgrade.add_review("protocol", HASH_A)

        with self.assertRaisesRegex(UpgradeGovernanceError, "reviews"):
            upgrade.record_rehearsal(HASH_F)

    def test_activation_height_is_immutable(self) -> None:
        upgrade = GovernedUpgrade(self._proposal())
        for role, digest in (
            ("protocol", HASH_A),
            ("security", HASH_B),
            ("release", HASH_C),
            ("recovery", HASH_D),
        ):
            upgrade.add_review(role, digest)
        upgrade.record_rehearsal(HASH_F)

        with self.assertRaisesRegex(UpgradeGovernanceError, "differs"):
            upgrade.schedule(100_001)

    def test_rejection_is_terminal(self) -> None:
        upgrade = GovernedUpgrade(self._proposal())
        upgrade.reject("security acceptance failed")

        with self.assertRaisesRegex(UpgradeGovernanceError, "terminal"):
            upgrade.add_review("protocol", HASH_G)

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = GovernedUpgrade(self._proposal()).as_evidence()

        self.assertFalse(evidence["activation_authorized"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
