import unittest

from jaios.social_ecosystem_chain.infrastructure_plan import (
    InfrastructurePlanError,
    build_infrastructure_plan,
)


def specification():
    return {
        "environment": "public-testnet",
        "release_commit": "a" * 40,
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "failure_domains": ["a", "b", "c"],
    }


class InfrastructurePlanTests(unittest.TestCase):
    def test_builds_deterministic_separated_topology(self):
        first = build_infrastructure_plan(specification())
        second = build_infrastructure_plan(specification())
        self.assertEqual(first.digest, second.digest)
        validators = first.plan["topology"]["validators"]
        self.assertEqual(len(validators), 3)
        self.assertEqual(len({node["failure_domain"] for node in validators}), 3)
        self.assertTrue(all(not node["public_rpc"] for node in validators))

    def test_public_gateway_is_tls_readonly_and_rate_limited(self):
        gateway = build_infrastructure_plan(specification()).plan["topology"][
            "public_rpc_gateway"
        ]
        self.assertEqual(gateway["ingress"], ["443/tcp"])
        self.assertTrue(gateway["tls_required"])
        self.assertTrue(gateway["rate_limit_required"])
        self.assertIn("eth_sendRawTransaction", gateway["unsafe_rpc_methods_denied"])

    def test_release_boundary_is_non_deploying(self):
        boundary = build_infrastructure_plan(specification()).plan["release_boundary"]
        self.assertFalse(boundary["automatic_deployment"])
        self.assertFalse(boundary["mainnet_changed"])
        self.assertFalse(boundary["assets_moved"])

    def test_rejects_collocated_validators(self):
        payload = specification()
        payload["failure_domains"] = ["a", "a", "b"]
        with self.assertRaises(InfrastructurePlanError):
            build_infrastructure_plan(payload)

    def test_rejects_noninstitutional_governance(self):
        payload = specification()
        payload["governance"] = "CEO"
        with self.assertRaises(InfrastructurePlanError):
            build_infrastructure_plan(payload)


if __name__ == "__main__":
    unittest.main()
