import copy
import unittest

from jaios.social_ecosystem_chain.canonical_binding import (
    CanonicalBindingError,
    evaluate_canonical_binding,
    load_canonical_binding,
)
from jaios.social_ecosystem_chain.rollback_acceptance import (
    evaluate_rollback_acceptance,
)
from jaios.social_ecosystem_chain.runtime_acceptance_v2 import (
    UNSAFE_METHODS,
    evaluate_runtime_acceptance_v2,
)


def ready_binding():
    return {
        "official_name": "JUNCA Social Ecosystem Chain",
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "environment": "public-testnet",
        "provider": "google-cloud",
        "account_scope": "organizations/example",
        "project_id": "junca-testnet-example",
        "region": "example-region",
        "network_id": "networks/junca-testnet",
        "dns_zone": "managedZones/junca-testnet",
        "failure_domains": ["zone-a", "zone-b", "zone-c"],
        "state_backend_resource": "buckets/junca-testnet-state",
        "deployment_principal_resource": "serviceAccounts/deployer",
        "signer_resources": ["kms/key/1", "kms/key/2", "kms/key/3"],
        "release_commit": "8ee00768536aa54df6d83f47283dd6d5fd7ddcc6",
        "billing_active": True,
        "identity_authenticated": True,
        "dns_zone_authoritative": True,
        "secret_resources_present": True,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def runtime_policy():
    return {
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "chain_id": 6699,
        "genesis_identity": "a" * 64,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def runtime_observations():
    return {
        "https_verified": True,
        "tls_certificate_verified": True,
        "dns_verified": True,
        "chain_id": 6699,
        "genesis_identity": "a" * 64,
        "head_samples": [100, 102],
        "finalized_head_samples": [99, 101],
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "peer_count": 2,
        "rpc": {
            "response_id_matches": True,
            "jsonrpc": "2.0",
            "envelope_verified": True,
            "rejected_methods": sorted(UNSAFE_METHODS),
            "rate_limit_verified": True,
        },
        "explorer": {"head": 101, "finalized_only": True},
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


class CanonicalBindingTests(unittest.TestCase):
    def test_pending_binding_is_blocked_without_raw_values(self):
        evidence = load_canonical_binding(
            "config/junca_social_ecosystem_chain_cloud_binding.pending.json"
        )
        self.assertEqual(evidence.state, "BLOCKED")
        self.assertFalse(evidence.evidence["project_bound"])
        self.assertNotIn("project_id", evidence.evidence)
        self.assertFalse(evidence.evidence["mainnet_changed"])

    def test_complete_binding_is_ready_and_deterministic(self):
        first = evaluate_canonical_binding(ready_binding())
        second = evaluate_canonical_binding(ready_binding())
        self.assertEqual(first.state, "READY")
        self.assertEqual(first.binding_fingerprint, second.binding_fingerprint)
        self.assertEqual(first.evidence["signer_resource_count"], 3)

    def test_secret_material_field_is_rejected(self):
        binding = ready_binding()
        binding["private_key"] = "forbidden"
        with self.assertRaises(CanonicalBindingError):
            evaluate_canonical_binding(binding)

    def test_mainnet_or_asset_boundary_cannot_change(self):
        for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
            binding = ready_binding()
            binding[boundary] = True
            with self.assertRaises(CanonicalBindingError):
                evaluate_canonical_binding(binding)


class RuntimeAcceptanceTests(unittest.TestCase):
    def test_complete_runtime_acceptance_is_accepted(self):
        evidence = evaluate_runtime_acceptance_v2(
            runtime_policy(), runtime_observations()
        )
        self.assertEqual(evidence.state, "ACCEPTED")
        self.assertEqual(evidence.failed_gates, ())

    def test_every_unsafe_method_is_required(self):
        observations = runtime_observations()
        observations["rpc"]["rejected_methods"].remove("eth_sendRawTransaction")
        evidence = evaluate_runtime_acceptance_v2(runtime_policy(), observations)
        self.assertEqual(evidence.state, "BLOCKED")
        self.assertIn("unsafe_rpc_rejection", evidence.failed_gates)

    def test_failed_tls_dns_or_rate_limit_blocks_acceptance(self):
        for path in ("tls", "dns", "rate"):
            observations = runtime_observations()
            if path == "tls":
                observations["tls_certificate_verified"] = False
            elif path == "dns":
                observations["dns_verified"] = False
            else:
                observations["rpc"]["rate_limit_verified"] = False
            evidence = evaluate_runtime_acceptance_v2(runtime_policy(), observations)
            self.assertEqual(evidence.state, "BLOCKED")


class RollbackAcceptanceTests(unittest.TestCase):
    def test_non_production_rollback_rehearsal_is_accepted(self):
        evidence = {
            "public_endpoint_withdrawal": True,
            "bridge_pause_maintained": True,
            "logs_and_audit_preserved": True,
            "last_finalized_checkpoint_saved": True,
            "binary_and_genesis_restored": True,
            "validator_quorum_reverified": True,
            "readonly_endpoint_restored": True,
            "explorer_parity_reverified": True,
            "non_production_rehearsal": True,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        result = evaluate_rollback_acceptance(evidence)
        self.assertEqual(result.state, "ACCEPTED")
        mutated = copy.deepcopy(evidence)
        mutated["validator_quorum_reverified"] = False
        self.assertEqual(evaluate_rollback_acceptance(mutated).state, "BLOCKED")


if __name__ == "__main__":
    unittest.main()

