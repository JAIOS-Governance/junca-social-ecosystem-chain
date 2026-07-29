from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "scripts/junca_public_testnet_foundation.sh"


class RollingVolumeLineageReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = FOUNDATION.read_text(encoding="utf-8")
        cls.rolling = cls.script.split(
            "write_rolling_compatibility_evidence() {", 1
        )[1].split("\n}\n\nwrite_rolling_resume_evidence()", 1)[0]

    def test_rolling_observations_read_current_retained_volumes(self) -> None:
        self.assertIn(
            ".validator_state_volume_readback.value[]", self.rolling
        )
        self.assertIn(
            "artifacts/rolling-foundation-outputs.json", self.rolling
        )
        self.assertIn(
            'select(.validator_id == $validator_id)', self.rolling
        )
        self.assertIn(
            'test("^vol-[0-9a-f]{8,17}$")', self.rolling
        )

    def test_current_volume_must_equal_rollback_volume(self) -> None:
        current = self.rolling.index(
            ".validator_state_volume_readback.value[]"
        )
        rollback = self.rolling.index("artifacts/rollback-rehearsal.json")
        equality = self.rolling.index(
            'test "$state_volume_id" = "$rollback_volume_id"'
        )
        enrichment = self.rolling.index(
            "'. + {volume_id: $volume_id}'"
        )
        aggregation = self.rolling.index(
            "jq -s '.' artifacts/rolling-validator-{1,2,3}.json"
        )
        self.assertLess(current, equality)
        self.assertLess(rollback, equality)
        self.assertLess(equality, enrichment)
        self.assertLess(enrichment, aggregation)

    def test_each_observation_is_enriched_before_gate_input(self) -> None:
        for required in (
            'observation_path="artifacts/rolling-validator-$((index + 1)).json"',
            'enriched_observation_path="${observation_path%.json}.enriched.json"',
            'jq --arg volume_id "$state_volume_id"',
            "'. + {volume_id: $volume_id}'",
            'mv "$enriched_observation_path" "$observation_path"',
            "--slurpfile validators artifacts/rolling-validators.json",
            "python scripts/junca_live_rollout_prefix_gate.py",
            "--mode rolling",
        ):
            self.assertIn(required, self.rolling)

    def test_no_volume_identity_is_synthesized_or_rewritten(self) -> None:
        self.assertNotIn("aws ec2 create-volume", self.rolling)
        self.assertNotIn("aws ec2 attach-volume", self.rolling)
        self.assertNotIn("aws ec2 detach-volume", self.rolling)
        self.assertNotIn("terraform import", self.rolling)
        self.assertNotIn("terraform state", self.rolling)


if __name__ == "__main__":
    unittest.main()
