from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.sdk_contract import (
    ApplicationIntegrationContract,
    SdkContractError,
    SdkRequest,
    build_capabilities,
)


GENESIS = "0x" + ("11" * 32)
PAYLOAD = "0x" + ("22" * 32)


class SdkContractTests(unittest.TestCase):
    def _node(self, **overrides):
        values = {
            "protocol_version": "1.0.0",
            "api_version": "1.1.0",
            "network_profile": "mainnet-candidate",
            "chain_id": 20260723,
            "genesis_hash": GENESIS,
            "capabilities": ("address-query", "finalized-blocks", "transactions"),
        }
        values.update(overrides)
        return build_capabilities(**values)

    def _contract(self):
        return ApplicationIntegrationContract(
            application_id="junca-platform-app",
            required_protocol_major=1,
            required_api_major=1,
            required_capabilities=("finalized-blocks", "transactions"),
            allowed_network_profiles=("mainnet-candidate", "public-testnet"),
        )

    def test_application_contract_accepts_compatible_node(self) -> None:
        result = self._contract().evaluate(self._node())

        self.assertTrue(result["compatible"])
        self.assertEqual(result["missing_capabilities"], [])

    def test_missing_capability_and_wrong_major_fail_compatibility(self) -> None:
        missing = self._contract().evaluate(
            self._node(capabilities=("finalized-blocks",))
        )
        wrong_major = self._contract().evaluate(
            self._node(api_version="2.0.0")
        )

        self.assertFalse(missing["compatible"])
        self.assertEqual(missing["missing_capabilities"], ["transactions"])
        self.assertFalse(wrong_major["compatible"])

    def test_request_hash_binds_chain_genesis_and_payload(self) -> None:
        base = SdkRequest(
            request_id="request-001",
            application_id="junca-platform-app",
            method="submit-transaction",
            chain_id=20260723,
            genesis_hash=GENESIS,
            api_version="1.1.0",
            payload_hash=PAYLOAD,
        )
        changed_chain = SdkRequest(
            **{**base.__dict__, "chain_id": 20260724}
        )
        changed_payload = SdkRequest(
            **{**base.__dict__, "payload_hash": "0x" + ("33" * 32)}
        )

        self.assertNotEqual(base.request_hash, changed_chain.request_hash)
        self.assertNotEqual(base.request_hash, changed_payload.request_hash)

    def test_capability_identifiers_fail_closed(self) -> None:
        with self.assertRaisesRegex(SdkContractError, "capabilities"):
            build_capabilities(
                protocol_version="1.0.0",
                api_version="1.0.0",
                network_profile="mainnet-candidate",
                chain_id=20260723,
                genesis_hash=GENESIS,
                capabilities=("INVALID CAPABILITY",),
            )


if __name__ == "__main__":
    unittest.main()
