import copy
import json
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.repository_governance import (
    RepositoryGovernanceError,
    evaluate_repository_boundary,
    load_repository_boundary,
    scan_public_identity,
)


BOUNDARY_PATH = Path("governance/repository-boundary.json")


def boundary():
    return json.loads(BOUNDARY_PATH.read_text())


class RepositoryGovernanceTests(unittest.TestCase):
    def test_pending_owner_binding_is_fail_closed(self):
        evidence = load_repository_boundary()
        self.assertEqual(evidence["state"], "BLOCKED")
        self.assertEqual(evidence["blockers"], ["repository_owner_binding"])
        self.assertFalse(evidence["corporate_ownership_represented"])
        self.assertFalse(evidence["personal_control_represented"])

    def test_verified_jaios_owner_binding_is_ready(self):
        specification = boundary()
        specification["repository_owner_binding"] = "JAIOS"
        evidence = evaluate_repository_boundary(specification)
        self.assertEqual(evidence["state"], "READY")
        self.assertEqual(evidence["blockers"], [])

    def test_rejects_company_or_personal_ownership(self):
        for key in (
            "corporate_ownership_represented",
            "personal_control_represented",
        ):
            specification = copy.deepcopy(boundary())
            specification[key] = True
            with self.subTest(key=key), self.assertRaises(
                RepositoryGovernanceError
            ):
                evaluate_repository_boundary(specification)

    def test_rejects_mainnet_or_asset_boundary_change(self):
        for key in ("mainnet_changed", "assets_moved", "bridge_activated"):
            specification = copy.deepcopy(boundary())
            specification["release_boundary"][key] = True
            with self.subTest(key=key), self.assertRaises(
                RepositoryGovernanceError
            ):
                evaluate_repository_boundary(specification)

    def test_detects_prohibited_public_identity(self):
        findings = scan_public_identity("This is a CEO-controlled chain.")
        self.assertEqual(findings, ("CEO-controlled",))
        self.assertEqual(scan_public_identity("JAIOS Institutional Governance"), ())


if __name__ == "__main__":
    unittest.main()
