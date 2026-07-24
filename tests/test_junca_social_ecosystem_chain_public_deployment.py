import unittest

from jaios.social_ecosystem_chain.public_deployment import (
    PublicDeploymentError,
    evaluate_public_deployment,
    load_public_deployment,
)


def accepted_specification():
    return {
        "environment": "public-testnet",
        "chain_id": 6699,
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "release_commit": "a" * 40,
        "validators": [
            {
                "id": f"validator-{index:02d}",
                "signer_secret_resource": (
                    f"projects/junca-testnet/secrets/validator-{index:02d}/versions/1"
                ),
            }
            for index in range(1, 4)
        ],
        "endpoints": {
            "rpc": "https://rpc.testnet.example.com",
            "explorer": "https://explorer.testnet.example.com",
            "health": "https://status.testnet.example.com/health",
        },
        "attestations": {
            "dns_tls_verified": True,
            "validator_quorum_verified": True,
            "rpc_acceptance_verified": True,
            "explorer_parity_verified": True,
            "monitoring_verified": True,
            "rollback_verified": True,
            "security_review_approved": True,
        },
    }


class PublicDeploymentTests(unittest.TestCase):
    def test_pending_specification_is_blocked(self):
        evidence = load_public_deployment(
            "config/junca_social_ecosystem_chain_public_deployment.pending.json"
        )
        self.assertEqual(evidence.state, "BLOCKED")
        self.assertEqual(len(evidence.blockers), 13)
        self.assertFalse(evidence.evidence["assets_moved"])

    def test_complete_specification_is_deterministically_accepted(self):
        specification = accepted_specification()
        first = evaluate_public_deployment(specification)
        second = evaluate_public_deployment(specification)
        self.assertEqual(first.state, "ACCEPTED")
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.blockers, ())

    def test_rejects_literal_or_malformed_signer_resource(self):
        specification = accepted_specification()
        specification["validators"][0]["signer_secret_resource"] = "0x" + "1" * 64
        with self.assertRaises(PublicDeploymentError):
            evaluate_public_deployment(specification)

    def test_rejects_insecure_or_private_endpoint(self):
        specification = accepted_specification()
        specification["endpoints"]["rpc"] = "http://127.0.0.1:8545"
        with self.assertRaises(PublicDeploymentError):
            evaluate_public_deployment(specification)

    def test_rejects_personal_governance_representation(self):
        specification = accepted_specification()
        specification["governance"] = "CEO"
        with self.assertRaises(PublicDeploymentError):
            evaluate_public_deployment(specification)


if __name__ == "__main__":
    unittest.main()
