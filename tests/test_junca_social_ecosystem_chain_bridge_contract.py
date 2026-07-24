import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/junca-social-ecosystem-chain/JuncaTestnetBridge.sol"
VERIFIER = ROOT / "scripts/verify_junca_testnet_bridge_contract.py"


class BridgeContractTests(unittest.TestCase):
    def test_contract_has_fail_closed_controls(self):
        content = CONTRACT.read_text()
        required = (
            "bool public paused = true",
            "processedMessage",
            "processedSourceTransaction",
            "processedSourceNonce",
            "RoutePaused",
            "RateLimitExceeded",
            "SECP256K1N_HALF",
            "nonReentrant",
        )
        for item in required:
            self.assertIn(item, content)

    def test_guardian_cannot_unpause(self):
        content = CONTRACT.read_text()
        self.assertIn("msg.sender != guardian || paused_ == false", content)

    def test_governance_transfer_is_two_step(self):
        content = CONTRACT.read_text()
        self.assertIn("proposeGovernance", content)
        self.assertIn("acceptGovernance", content)
        self.assertIn("pendingInstitutionalGovernance", content)

    def test_no_unsafe_execution_constructs(self):
        content = CONTRACT.read_text()
        for item in ("tx.origin", "delegatecall", "selfdestruct"):
            self.assertNotIn(item, content)

    def test_static_verifier_emits_pass_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            result = subprocess.run(
                [
                    "python",
                    str(VERIFIER),
                    "--contract",
                    str(CONTRACT),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["state"], "STATIC_VERIFIED")
            self.assertFalse(evidence["deployment_performed"])
            self.assertFalse(evidence["assets_moved"])


if __name__ == "__main__":
    unittest.main()
