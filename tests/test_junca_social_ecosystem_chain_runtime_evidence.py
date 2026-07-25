import copy
import unittest

from jaios.social_ecosystem_chain.runtime_acceptance_v2 import UNSAFE_METHODS
from jaios.social_ecosystem_chain.runtime_evidence import (
    LiveRuntimeEvidenceError,
    build_live_runtime_evidence,
    evaluate_live_runtime_acceptance,
)


VALIDATORS = ["validator-1", "validator-2", "validator-3"]
DIGESTS = ["1" * 64, "2" * 64, "3" * 64]


def policy():
    return {
        "chain_id": 20260723,
        "genesis_identity": "a" * 64,
        "validator_ids": VALIDATORS,
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def runtime():
    return {
        "schema_version": "junca-live-validator-runtime/v1",
        "chain_id": 20260723,
        "head_height": 102,
        "signer_bindings": [
            {"validator_id": validator, "key_resource_digest": digest}
            for validator, digest in zip(VALIDATORS, DIGESTS)
        ],
        "private_key_material_accepted": False,
        "governance": "JAIOS Institutional Governance",
        "network": "Public Testnet / No Monetary Value",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def blocks():
    return [
        {
            "schema_version": "junca-live-validator-finalization/v1",
            "height": height,
            "block_hash": f"{height:064x}",
            "state_root": f"{height + 1000:064x}",
            "certificate_hash": f"{height + 2000:064x}",
            "signed_power": 3,
            "total_power": 3,
            "finality_status": "FINALIZED",
            "governance": "JAIOS Institutional Governance",
            "network": "Public Testnet / No Monetary Value",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        for height in (100, 102)
    ]


def operations():
    return {
        "https_verified": True,
        "tls_certificate_verified": True,
        "dns_verified": True,
        "genesis_identity": "a" * 64,
        "peer_count": 2,
        "rpc": {
            "response_id_matches": True,
            "jsonrpc": "2.0",
            "envelope_verified": True,
            "rejected_methods": sorted(UNSAFE_METHODS),
            "rate_limit_verified": True,
        },
        "explorer": {"head": 102, "finalized_only": True},
        "health": {"ok": True},
        "monitoring": {
            "validator_quorum": True,
            "rpc_head_lag": True,
            "disk_capacity": True,
            "external_health": True,
        },
        "restart_recovery_verified": True,
        "rollback_readiness_verified": True,
        "public_metadata": {
            "governance": "JAIOS Institutional Governance",
            "notice": "Public Testnet / No Monetary Value",
        },
    }


class LiveRuntimeEvidenceTests(unittest.TestCase):
    def test_live_chain_evidence_drives_all_acceptance_gates(self):
        result = evaluate_live_runtime_acceptance(
            policy=policy(),
            validator_runtime=runtime(),
            finalized_blocks=blocks(),
            operational_observations=operations(),
        )
        self.assertEqual(result.state, "ACCEPTED")
        self.assertEqual(result.failed_gates, ())

    def test_bundle_is_deterministic_and_contains_no_signer_resource(self):
        first = build_live_runtime_evidence(
            policy=policy(),
            validator_runtime=runtime(),
            finalized_blocks=blocks(),
            operational_observations=operations(),
        )
        second = build_live_runtime_evidence(
            policy=policy(),
            validator_runtime=runtime(),
            finalized_blocks=blocks(),
            operational_observations=operations(),
        )
        self.assertEqual(first.source_digest, second.source_digest)
        self.assertNotIn("kms://", str(first.as_dict()))

    def test_rejects_non_advancing_or_unfinalized_chain_evidence(self):
        values = blocks()
        values[1]["height"] = values[0]["height"]
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "strictly advance"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=runtime(),
                finalized_blocks=values,
                operational_observations=operations(),
            )
        values = blocks()
        values[1]["finality_status"] = "PENDING"
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "not finalized"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=runtime(),
                finalized_blocks=values,
                operational_observations=operations(),
            )

    def test_rejects_signer_mismatch_secret_fields_and_weak_quorum(self):
        value = runtime()
        value["signer_bindings"][2]["validator_id"] = "unknown"
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "do not match"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=value,
                finalized_blocks=blocks(),
                operational_observations=operations(),
            )
        value = runtime()
        value["signer_bindings"][0]["key_resource"] = "kms://must-not-leak"
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "secret-bearing"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=value,
                finalized_blocks=blocks(),
                operational_observations=operations(),
            )
        values = blocks()
        values[1]["signed_power"] = 2
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "strict quorum"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=runtime(),
                finalized_blocks=values,
                operational_observations=operations(),
            )

    def test_rejects_operational_override_of_chain_evidence(self):
        value = operations()
        value["validator_ids"] = ["forged-1", "forged-2", "forged-3"]
        with self.assertRaisesRegex(LiveRuntimeEvidenceError, "conflicts"):
            build_live_runtime_evidence(
                policy=policy(),
                validator_runtime=runtime(),
                finalized_blocks=blocks(),
                operational_observations=value,
            )

    def test_operational_failure_remains_blocked(self):
        value = copy.deepcopy(operations())
        value["restart_recovery_verified"] = False
        result = evaluate_live_runtime_acceptance(
            policy=policy(),
            validator_runtime=runtime(),
            finalized_blocks=blocks(),
            operational_observations=value,
        )
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("restart_recovery", result.failed_gates)


if __name__ == "__main__":
    unittest.main()
