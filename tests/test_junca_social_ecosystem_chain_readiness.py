from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import ChainReadinessError, REQUIRED_GATES, load_readiness


CONFIG = Path("config/junca_social_ecosystem_chain_readiness.json")


class ChainReadinessTests(unittest.TestCase):
    def test_canonical_candidate_is_blocked_fail_closed(self) -> None:
        readiness = load_readiness(CONFIG)
        self.assertEqual(readiness.state, "blocked")
        self.assertIn("reproducible-build", readiness.missing_gates)
        with self.assertRaisesRegex(ChainReadinessError, "release blocked"):
            readiness.assert_promotable()

    def test_all_verified_gates_are_ready(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["source_commit"] = "a" * 40
        raw["gates"] = {name: True for name in REQUIRED_GATES}
        readiness = self._load(raw)
        self.assertEqual(readiness.state, "ready")
        readiness.assert_promotable()

    def test_missing_gate_is_invalid(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        del raw["gates"]["rollback-package"]
        with self.assertRaisesRegex(ChainReadinessError, "gate set mismatch"):
            self._load(raw)

    def test_non_boolean_gate_is_invalid(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["gates"]["validator-quorum"] = "pending"
        with self.assertRaisesRegex(ChainReadinessError, "must be boolean"):
            self._load(raw)

    def test_former_brand_is_rejected(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["official_name"] = "JUNCA Global Chain"
        with self.assertRaisesRegex(ChainReadinessError, "official_name"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "readiness.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_readiness(path)


if __name__ == "__main__":
    unittest.main()
