import unittest

from jaios.social_ecosystem_chain.runtime_acceptance import (
    REQUIRED_GOVERNANCE,
    REQUIRED_NOTICE,
    RuntimeAcceptanceError,
    UNSAFE_RPC_METHODS,
    evaluate_runtime_acceptance,
)


V = [
    "0x1111111111111111111111111111111111111111",
    "0x2222222222222222222222222222222222222222",
    "0x3333333333333333333333333333333333333333",
]


def policy():
    return {
        "chain_id": 20260723,
        "validator_addresses": V,
        "governance": REQUIRED_GOVERNANCE,
        "notice": REQUIRED_NOTICE,
    }


def observations():
    return {
        "chain_id": 20260723,
        "head_samples": [
            {"number": 100, "timestamp": 1000},
            {"number": 102, "timestamp": 1004},
        ],
        "validator_signers": V,
        "peer_count": 2,
        "rpc": {
            "url": "https://rpc.testnet.example.org",
            "rejected_methods": sorted(UNSAFE_RPC_METHODS),
        },
        "explorer": {
            "url": "https://explorer.testnet.example.org",
            "head": 102,
        },
        "public_metadata": {
            "governance": REQUIRED_GOVERNANCE,
            "notice": REQUIRED_NOTICE,
        },
    }


class RuntimeAcceptanceTests(unittest.TestCase):
    def test_accepts_complete_runtime_evidence(self):
        result = evaluate_runtime_acceptance(policy(), observations())
        self.assertTrue(result.accepted)
        self.assertEqual(result.reasons, ())
        self.assertEqual(len(result.evidence_digest), 64)

    def test_blocks_static_head_and_missing_rpc_rejections(self):
        value = observations()
        value["head_samples"][1] = {"number": 100, "timestamp": 1000}
        value["rpc"]["rejected_methods"] = ["admin_addPeer"]
        result = evaluate_runtime_acceptance(policy(), value)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("head_advancing", result.reasons)
        self.assertIn("unsafe_rpc_rejected", result.reasons)

    def test_blocks_explorer_mismatch_and_wrong_public_label(self):
        value = observations()
        value["explorer"]["head"] = 101
        value["public_metadata"]["governance"] = "CEO"
        result = evaluate_runtime_acceptance(policy(), value)
        self.assertFalse(result.gates["explorer_head_parity"])
        self.assertFalse(result.gates["institutional_governance"])

    def test_rejects_duplicate_validators(self):
        value = policy()
        value["validator_addresses"] = [V[0], V[0], V[2]]
        with self.assertRaises(RuntimeAcceptanceError):
            evaluate_runtime_acceptance(value, observations())

    def test_digest_is_deterministic(self):
        first = evaluate_runtime_acceptance(policy(), observations())
        second = evaluate_runtime_acceptance(policy(), observations())
        self.assertEqual(first.evidence_digest, second.evidence_digest)


if __name__ == "__main__":
    unittest.main()
