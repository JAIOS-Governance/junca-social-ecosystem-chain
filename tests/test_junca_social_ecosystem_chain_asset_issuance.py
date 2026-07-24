import unittest

from jaios.social_ecosystem_chain.asset_issuance import (
    AssetIssuanceError,
    build_issuance_manifest,
)


ROLES = {
    "admin": "0x1111111111111111111111111111111111111111",
    "treasury": "0x2222222222222222222222222222222222222222",
    "pauser": "0x3333333333333333333333333333333333333333",
}


def token_spec():
    return {
        "asset_id": "partner-token",
        "asset_type": "fungible-token",
        "standard": "ERC-20",
        "name": "Partner Token",
        "symbol": "PTK",
        "chain_id": 20260723,
        "roles": dict(ROLES),
        "controls": {
            "mintable": False,
            "burnable": True,
            "pausable": True,
            "upgradeable": False,
            "multisig_required": True,
        },
        "decimals": 18,
        "initial_supply": 1000,
        "max_supply": 1000,
        "attestations": {
            "partner_authorized": True,
            "legal_review_complete": True,
            "security_review_complete": True,
            "metadata_rights_confirmed": True,
            "testnet_only": True,
        },
    }


class AssetIssuanceTests(unittest.TestCase):
    def test_builds_ready_deterministic_token_manifest(self):
        first = build_issuance_manifest(token_spec())
        second = build_issuance_manifest(token_spec())
        self.assertEqual(first.state, "TESTNET_READY")
        self.assertEqual(first.specification_digest, second.specification_digest)
        self.assertEqual(first.deployment_salt, second.deployment_salt)

    def test_missing_attestations_block_not_reject(self):
        value = token_spec()
        value["attestations"]["legal_review_complete"] = False
        value["attestations"]["security_review_complete"] = False
        result = build_issuance_manifest(value)
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual(
            result.blockers,
            ("legal_review_complete", "security_review_complete"),
        )

    def test_rejects_role_concentration(self):
        value = token_spec()
        value["roles"]["treasury"] = value["roles"]["admin"]
        with self.assertRaises(AssetIssuanceError):
            build_issuance_manifest(value)

    def test_rejects_unbounded_or_upgradeable_configuration(self):
        value = token_spec()
        value["initial_supply"] = value["max_supply"] + 1
        with self.assertRaises(AssetIssuanceError):
            build_issuance_manifest(value)
        value = token_spec()
        value["controls"]["upgradeable"] = True
        with self.assertRaises(AssetIssuanceError):
            build_issuance_manifest(value)

    def test_builds_nft_manifest_with_metadata_controls(self):
        value = token_spec()
        value.update({
            "asset_id": "partner-nft",
            "asset_type": "nft-collection",
            "standard": "ERC-721",
            "name": "Partner Membership",
            "symbol": "PMB",
            "max_supply": 10000,
            "base_uri": "ipfs://partner-metadata/",
        })
        value.pop("decimals")
        value.pop("initial_supply")
        result = build_issuance_manifest(value)
        self.assertTrue(result.releasable)

    def test_rejects_unsafe_metadata_uri_and_mainnet_target(self):
        value = token_spec()
        value["chain_id"] = 1
        with self.assertRaises(AssetIssuanceError):
            build_issuance_manifest(value)
        value = token_spec()
        value.update({
            "asset_type": "nft-collection",
            "standard": "ERC-721",
            "max_supply": 10,
            "base_uri": "javascript:alert(1)",
        })
        value.pop("decimals")
        value.pop("initial_supply")
        with self.assertRaises(AssetIssuanceError):
            build_issuance_manifest(value)


if __name__ == "__main__":
    unittest.main()
