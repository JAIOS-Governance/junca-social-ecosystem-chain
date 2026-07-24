import copy
import json
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.interoperability import (
    InteroperabilityError,
    build_interoperability_manifest,
    load_interoperability_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
BSC = ROOT / "config/junca_social_ecosystem_chain_bsc_interoperability.pending.json"
TRON = ROOT / "config/junca_social_ecosystem_chain_tron_interoperability.pending.json"


class InteroperabilityTests(unittest.TestCase):
    def test_pending_routes_are_valid_but_blocked(self):
        for path in (BSC, TRON):
            manifest = load_interoperability_manifest(path)
            self.assertEqual(manifest.state, "BLOCKED")
            self.assertEqual(len(manifest.blockers), 5)
            self.assertEqual(len(manifest.digest), 64)

    def test_digest_is_deterministic(self):
        first = load_interoperability_manifest(BSC)
        second = load_interoperability_manifest(BSC)
        self.assertEqual(first.digest, second.digest)

    def test_all_attestations_make_route_ready(self):
        value = json.loads(BSC.read_text())
        value["attestations"] = {key: True for key in value["attestations"]}
        self.assertEqual(build_interoperability_manifest(value).state, "TESTNET_READY")

    def test_rejects_mainnet_and_untrusted_rpc(self):
        value = json.loads(BSC.read_text())
        value["destination_network"] = "bsc-mainnet"
        with self.assertRaises(InteroperabilityError):
            build_interoperability_manifest(value)
        value = json.loads(BSC.read_text())
        value["rpc_url"] = "https://attacker.example/rpc"
        with self.assertRaises(InteroperabilityError):
            build_interoperability_manifest(value)

    def test_rejects_unpaused_route(self):
        value = json.loads(TRON.read_text())
        value["controls"]["paused"] = False
        with self.assertRaises(InteroperabilityError):
            build_interoperability_manifest(value)

    def test_rejects_wrong_governance_and_notice(self):
        original = json.loads(BSC.read_text())
        for key, bad in (("governance", "CEO"), ("notice", "production")):
            value = copy.deepcopy(original)
            value[key] = bad
            with self.assertRaises(InteroperabilityError):
                build_interoperability_manifest(value)

    def test_rejects_bad_tron_address(self):
        value = json.loads(TRON.read_text())
        value["destination_contract"] = "TInvalid"
        with self.assertRaises(InteroperabilityError):
            build_interoperability_manifest(value)


if __name__ == "__main__":
    unittest.main()
