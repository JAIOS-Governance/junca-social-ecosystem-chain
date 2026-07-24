import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ERC20 = ROOT / "contracts/junca-social-ecosystem-chain/JuncaTestnetMintableERC20.sol"
ERC721 = ROOT / "contracts/junca-social-ecosystem-chain/JuncaTestnetMintableERC721.sol"


class MintableAssetTests(unittest.TestCase):
    def test_both_assets_are_adapter_only_and_paused(self):
        for contract in (ERC20, ERC721):
            content = contract.read_text()
            self.assertIn("address public immutable bridgeAdapter", content)
            self.assertIn("msg.sender != bridgeAdapter", content)
            self.assertIn("bool public paused = true", content)
            self.assertIn("JAIOS Institutional Governance", content)
            self.assertIn("Public Testnet / No Monetary Value", content)

    def test_erc20_supply_cap(self):
        content = ERC20.read_text()
        self.assertIn("uint256 public immutable maxSupply", content)
        self.assertIn("totalSupply + amount > maxSupply", content)

    def test_erc721_collection_cap_and_duplicate_token(self):
        content = ERC721.read_text()
        self.assertIn("uint256 public immutable collectionCap", content)
        self.assertIn("ownerOf[tokenId] != address(0)", content)
        self.assertIn("totalSupply >= collectionCap", content)

    def test_no_unsafe_primitives(self):
        for contract in (ERC20, ERC721):
            content = contract.read_text()
            for item in ("delegatecall", "selfdestruct", "tx.origin"):
                self.assertNotIn(item, content)


if __name__ == "__main__":
    unittest.main()
