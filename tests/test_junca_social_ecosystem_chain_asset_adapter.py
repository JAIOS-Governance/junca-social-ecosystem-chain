import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/junca-social-ecosystem-chain/JuncaBridgeAssetAdapter.sol"


class AssetAdapterTests(unittest.TestCase):
    def test_adapter_is_bridge_only_and_paused(self):
        content = CONTRACT.read_text()
        self.assertIn("address public immutable bridge", content)
        self.assertIn("if (msg.sender != bridge) revert Unauthorized()", content)
        self.assertIn("bool public paused = true", content)

    def test_asset_allowlist_and_address_bounds(self):
        content = CONTRACT.read_text()
        self.assertIn("mapping(address => AssetPolicy) public assetPolicy", content)
        self.assertIn("uint256(encoded) >> 160 != 0", content)
        self.assertIn("policy.enabled", content)

    def test_guardian_cannot_unpause(self):
        self.assertIn(
            "msg.sender != guardian || paused_ == false",
            CONTRACT.read_text(),
        )

    def test_no_arbitrary_call_primitives(self):
        content = CONTRACT.read_text()
        for item in ("delegatecall", "selfdestruct", "tx.origin"):
            self.assertNotIn(item, content)


if __name__ == "__main__":
    unittest.main()
