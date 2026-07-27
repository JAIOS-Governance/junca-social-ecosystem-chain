from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.soak_acceptance import (
    SLOT_COUNT,
    SoakAcceptanceError,
    SoakScenario,
    run_soak_simulation,
    write_soak_evidence,
)


class SoakAcceptanceTests(unittest.TestCase):
    def test_deterministic_24_hour_failure_scenario_passes(self) -> None:
        first = run_soak_simulation()
        second = run_soak_simulation()
        self.assertEqual(first, second)
        self.assertEqual(first["result"], "PASS")
        self.assertEqual(first["simulation"]["slot_count"], 2880)
        self.assertEqual(first["simulation"]["duration_seconds"], 86_400)
        self.assertEqual(first["simulation"]["stalled_slots"], 20)
        self.assertEqual(first["simulation"]["finalized_height"], SLOT_COUNT - 20)
        self.assertTrue(all(first["checks"].values()))
        self.assertFalse(first["mainnet_changed"])
        self.assertFalse(first["assets_moved"])
        self.assertFalse(first["bridge_activated"])

    def test_evidence_digest_binds_exact_payload(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory, "soak.json")
            evidence = write_soak_evidence(path)
            saved = json.loads(path.read_text())
            digest = saved.pop("evidence_sha256")
            expected = hashlib.sha256(
                json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self.assertEqual(digest, expected)
            self.assertEqual(evidence["evidence_sha256"], digest)

    def test_invalid_scenario_fails_closed(self) -> None:
        with self.assertRaisesRegex(SoakAcceptanceError, "order"):
            run_soak_simulation(
                SoakScenario(restart_slot=1000, loss_start_slot=900)
            )


if __name__ == "__main__":
    unittest.main()
