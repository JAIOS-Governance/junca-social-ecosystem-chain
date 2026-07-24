from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_testnet_release_gate.py"
spec = importlib.util.spec_from_file_location("public_testnet_release_gate", SCRIPT)
assert spec and spec.loader
release_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_gate)

BOUNDARY = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
    "bridge_route": "PAUSED",
}


def identity() -> dict:
    return {
        "official_chain_name": release_gate.CHAIN_NAME,
        "governance": release_gate.GOVERNANCE,
        "network_label": release_gate.NETWORK_LABEL,
        "chain_id": "20260724",
        "genesis_hash": "0xcanonical-genesis",
        "source_commit": "a" * 40,
        "release_boundary": dict(BOUNDARY),
    }


def accepted_evidence() -> tuple[dict, dict, dict]:
    binding = identity() | {
        "status": "AWS_BINDING_READBACK_VERIFIED",
        "aws": {"failure_domains": ["ap-northeast-1a", "ap-northeast-1c", "ap-northeast-1d"]},
        "validator_signers": [
            {"resource_arn": "arn:aws:kms:ap-northeast-1:123456789012:key/validator-01"},
            {"resource_arn": "arn:aws:kms:ap-northeast-1:123456789012:key/validator-02"},
            {"resource_arn": "arn:aws:kms:ap-northeast-1:123456789012:key/validator-03"},
        ],
    }
    runtime = identity() | {
        "validator_quorum": "3/3",
        "public_endpoints": {
            "rpc": "https://rpc.jaios-governance.org",
            "explorer": "https://explorer.jaios-governance.org",
            "health": "https://health.jaios-governance.org",
        },
        "gates": {gate: True for gate in (
            "https", "tls", "dns", "chain_id", "genesis_identity", "advancing_head",
            "finalized_head", "validator_quorum", "peer_connectivity", "rpc_envelope",
            "unsafe_rpc_rejection", "rate_limit", "explorer_parity", "health",
            "monitoring", "restart_recovery", "rollback_readiness",
        )},
    }
    rollback = identity() | {
        "gates": {gate: True for gate in (
            "endpoint_withdrawal", "bridge_pause", "logs_audit", "checkpoint",
            "binary_restore", "genesis_restore", "snapshot_restore", "quorum_recovery",
            "read_only_endpoint_recovery", "explorer_parity_recovery",
        )},
    }
    return binding, runtime, rollback


class PublicTestnetReleaseGateTest(unittest.TestCase):
    def test_accepts_only_complete_canonical_evidence(self) -> None:
        binding, runtime, rollback = accepted_evidence()
        decision = release_gate.evaluate(binding, runtime, rollback)
        self.assertTrue(decision["accepted"])
        self.assertEqual(decision["decision"], "PUBLIC_TESTNET_ACCEPTED")
        self.assertEqual(decision["failure_count"], 0)

    def test_rejects_unsafe_rpc_and_noncanonical_endpoint(self) -> None:
        binding, runtime, rollback = accepted_evidence()
        runtime["gates"]["unsafe_rpc_rejection"] = False
        runtime["public_endpoints"]["rpc"] = "http://validator.internal:8545"
        decision = release_gate.evaluate(binding, runtime, rollback)
        self.assertFalse(decision["accepted"])
        self.assertIn("runtime.gates.unsafe_rpc_rejection:not_passed", decision["failures"])
        self.assertIn("endpoint.rpc:canonical_https_mismatch", decision["failures"])

    def test_rejects_chain_identity_mismatch(self) -> None:
        binding, runtime, rollback = accepted_evidence()
        rollback["genesis_hash"] = "0xwrong-genesis"
        decision = release_gate.evaluate(binding, runtime, rollback)
        self.assertFalse(decision["accepted"])
        self.assertIn("chain_identity:mismatch", decision["failures"])

    def test_rejects_source_commit_mismatch(self) -> None:
        binding, runtime, rollback = accepted_evidence()
        rollback["source_commit"] = "b" * 40
        decision = release_gate.evaluate(binding, runtime, rollback)
        self.assertFalse(decision["accepted"])
        self.assertIn("source_commit:mismatch", decision["failures"])

    def test_rejects_mainnet_asset_or_bridge_change(self) -> None:
        binding, runtime, rollback = accepted_evidence()
        binding["release_boundary"]["mainnet_changed"] = True
        runtime["release_boundary"]["assets_moved"] = True
        rollback["release_boundary"]["bridge_activated"] = True
        decision = release_gate.evaluate(binding, runtime, rollback)
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["release_boundary"], BOUNDARY)
        self.assertGreaterEqual(decision["failure_count"], 3)


if __name__ == "__main__":
    unittest.main()
