from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "junca_public_testnet_runtime_acceptance_packet.py"
)
SPEC = importlib.util.spec_from_file_location("junca_runtime_packet", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime_packet = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_packet
SPEC.loader.exec_module(runtime_packet)


def _observation(
    index: int,
    *,
    height: int,
    block_hash: str,
    timestamp: int,
    certificate_hash: str,
) -> dict[str, object]:
    return {
        "index": index,
        "observed_at": f"2026-07-27T00:0{index}:00+00:00",
        "accepted": True,
        "failures": [],
        "normalized": {
            "height": height,
            "hash": block_hash,
            "timestamp": hex(timestamp),
            "timestamp_decimal": timestamp,
            "state_root": f"state-{height}",
            "certificate_hash": certificate_hash,
            "signed_power": 3,
            "total_power": 3,
            "peer_count": 2,
        },
    }


class RuntimeAcceptancePacketTests(TestCase):
    def _build(self, observations):
        with (
            patch.object(
                runtime_packet,
                "_unsafe_rejection",
                return_value={"accepted": True, "methods": {}},
            ),
            patch.object(
                runtime_packet,
                "_scan_redirect",
                return_value={"accepted": True},
            ),
        ):
            return runtime_packet.build_packet(observations, 30)

    def test_accepts_three_advancing_finalized_heads(self):
        packet = self._build(
            [
                _observation(
                    1,
                    height=10,
                    block_hash="hash-10",
                    timestamp=100,
                    certificate_hash="certificate-10",
                ),
                _observation(
                    2,
                    height=11,
                    block_hash="hash-11",
                    timestamp=130,
                    certificate_hash="certificate-11",
                ),
                _observation(
                    3,
                    height=12,
                    block_hash="hash-12",
                    timestamp=160,
                    certificate_hash="certificate-12",
                ),
            ]
        )

        self.assertEqual(packet["status"], "PASS")
        self.assertEqual(packet["failures"], [])

    def test_rejects_stalled_head_and_mutable_same_hash_metadata(self):
        packet = self._build(
            [
                _observation(
                    1,
                    height=1,
                    block_hash="same-hash",
                    timestamp=100,
                    certificate_hash="same-certificate",
                ),
                _observation(
                    2,
                    height=1,
                    block_hash="same-hash",
                    timestamp=101,
                    certificate_hash="same-certificate",
                ),
                _observation(
                    3,
                    height=1,
                    block_hash="same-hash",
                    timestamp=101,
                    certificate_hash="same-certificate",
                ),
            ]
        )

        self.assertEqual(packet["status"], "FAIL")
        self.assertIn("block:same_hash_metadata_changed", packet["failures"])
        self.assertIn("head:not_advancing_each_observation", packet["failures"])
        self.assertIn(
            "certificate:not_advancing_each_observation",
            packet["failures"],
        )
