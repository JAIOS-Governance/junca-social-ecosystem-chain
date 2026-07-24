from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import ChainArchitectureError, load_scale_profile


PROFILE_PATH = Path("config/junca_social_ecosystem_chain_scalability_profile.json")


class JuncaSocialEcosystemChainArchitectureTests(unittest.TestCase):
    def test_sovereign_v2_profile_scales_beyond_legacy(self) -> None:
        profile = load_scale_profile(PROFILE_PATH)

        self.assertEqual(profile.generation, "sovereign-v2")
        self.assertEqual(profile.sustained_tps_target, 2_000)
        self.assertEqual(profile.burst_tps_target, 5_000)
        self.assertEqual(profile.validators, 9)
        self.assertEqual(profile.validator_quorum, 7)
        self.assertEqual(len(profile.extension_boundaries), 8)
        self.assertEqual(
            profile.as_evidence()["performance_status"],
            "target-not-yet-benchmarked",
        )

    def test_missing_extension_boundary_is_rejected(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw["extension_architecture"]["boundaries"].remove("bridge-adapter")

        with self.assertRaisesRegex(ChainArchitectureError, "bridge-adapter"):
            self._load(raw)

    def test_unverified_performance_cannot_be_claimed(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw["verification_gates"]["public_slo_claim_allowed"] = True

        with self.assertRaisesRegex(ChainArchitectureError, "public_slo_claim_allowed"):
            self._load(raw)

    def test_under_scaled_topology_is_rejected(self) -> None:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        raw["production_topology"]["rpc_nodes"] = 2

        with self.assertRaisesRegex(ChainArchitectureError, "topology"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "profile.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_scale_profile(path)


if __name__ == "__main__":
    unittest.main()
