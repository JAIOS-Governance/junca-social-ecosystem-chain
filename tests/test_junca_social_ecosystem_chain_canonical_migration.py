from __future__ import annotations

import json
from pathlib import Path
import unittest


class CanonicalMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = json.loads(
            Path("governance/canonical-migration.json").read_text(encoding="utf-8")
        )

    def test_destination_and_source_provenance_are_exact(self) -> None:
        self.assertEqual(
            self.record["destination_repository"],
            "https://github.com/JAIOS-Governance/junca-social-ecosystem-chain",
        )
        self.assertEqual(
            self.record["source_main_sha"],
            "9366de4b603231daddb1276adbd574d923b63ac0",
        )
        self.assertIn(
            "a8500bc45f4c7239a6f12e67bf532c648db57fcf",
            self.record["source_merge_commits"],
        )

    def test_governance_and_public_notice_are_exact(self) -> None:
        self.assertEqual(
            self.record["governance"], "JAIOS Institutional Governance"
        )
        self.assertEqual(
            self.record["network_notice"], "Public Testnet / No Monetary Value"
        )

    def test_release_boundary_remains_fail_closed(self) -> None:
        self.assertEqual(
            self.record["release_boundary"],
            {
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
                "cloud_binding_ready": False,
            },
        )

    def test_non_chain_scopes_are_explicitly_excluded(self) -> None:
        excluded = set(self.record["excluded_scopes"])
        self.assertTrue({"voice-admin", "mailing", "kids-drawing"} <= excluded)


if __name__ == "__main__":
    unittest.main()
