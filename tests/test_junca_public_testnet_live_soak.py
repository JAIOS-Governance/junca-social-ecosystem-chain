from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "junca_public_testnet_live_soak.py"
SPEC = importlib.util.spec_from_file_location("live_soak", SCRIPT)
assert SPEC and SPEC.loader
soak = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = soak
SPEC.loader.exec_module(soak)

COMMIT = "a" * 40
NODE = "b" * 64
GENESIS = "c" * 64
AMI = "ami-0123456789abcdef0"


def observations(start: datetime, base_height: int):
    result = []
    for index in range(soak.OBSERVATIONS_PER_SEGMENT):
        observed = start + timedelta(seconds=index * soak.OBSERVATION_INTERVAL_SECONDS)
        height = base_height + index
        result.append(
            {
                "observed_at": observed.isoformat(),
                "normalized": {
                    "height": height,
                    "timestamp_decimal": 1_800_000_000 + height * 30,
                    "signed_power": 3,
                    "total_power": 3,
                    "peer_count": 2,
                },
            }
        )
    return result


def segment(index: int):
    start = datetime(2026, 7, 27, tzinfo=timezone.utc) + timedelta(
        hours=4 * (index - 1)
    )
    packet = {
        "schema_version": "junca-public-testnet-live-acceptance-packet/v1",
        "status": "PASS",
        "observations": observations(
            start, (index - 1) * soak.OBSERVATIONS_PER_SEGMENT
        ),
        "release_boundary": dict(soak.BOUNDARY),
    }
    return soak.build_segment(
        packet,
        segment_index=index,
        source_commit=COMMIT,
        node_artifact_sha256=NODE,
        genesis_sha256=GENESIS,
        ami_id=AMI,
    )


class LiveSoakTests(unittest.TestCase):
    def test_exact_six_segments_accept_with_provenance(self):
        result = soak.aggregate_segments(
            [segment(index) for index in range(1, 7)],
            source_commit=COMMIT,
            node_artifact_sha256=NODE,
            genesis_sha256=GENESIS,
            ami_id=AMI,
            foundation_run_id="123",
            public_release_run_id="456",
            final_runtime_readback_sha256="d" * 64,
        )
        self.assertTrue(result["accepted"], result["failures"])
        self.assertGreaterEqual(result["duration_seconds"], 86_400)
        self.assertEqual(result["provenance"]["foundation_run_id"], "123")

    def test_candidate_drift_and_gap_fail_closed(self):
        segments = [segment(index) for index in range(1, 7)]
        segments[2]["candidate_binding"]["ami_id"] = "ami-11111111111111111"
        segments[4]["observed_from"] = "2026-07-28T12:00:00Z"
        result = soak.aggregate_segments(
            segments,
            source_commit=COMMIT,
            node_artifact_sha256=NODE,
            genesis_sha256=GENESIS,
            ami_id=AMI,
        )
        self.assertFalse(result["accepted"])
        self.assertIn("segment.candidate_binding:mismatch", result["failures"])
        self.assertIn("segments:continuity_gap", result["failures"])

    def test_workflows_are_segmented_automated_and_deployment_frozen(self):
        workflow = (
            ROOT / ".github/workflows/junca-public-testnet-live-soak.yml"
        ).read_text(encoding="utf-8")
        segment_workflow = (
            ROOT
            / ".github/workflows/junca-public-testnet-live-soak-segment.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('group: junca-public-testnet-aws-foundation', workflow)
        self.assertIn('"JUNCA Public Testnet Release"', workflow)
        self.assertIn(
            '.path == ".github/workflows/junca-public-testnet-release.yml"',
            workflow,
        )
        self.assertEqual(workflow.count("junca-public-testnet-live-soak-segment.yml"), 6)
        self.assertIn("timeout-minutes: 270", segment_workflow)
        self.assertNotIn("terraform apply", workflow.lower())
        self.assertNotIn("aws ec2 run-instances", workflow.lower())


if __name__ == "__main__":
    unittest.main()
