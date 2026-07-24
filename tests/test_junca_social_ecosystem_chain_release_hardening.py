import json
import random
import tempfile
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.bridge_build_bundle import build_deployment_bundle
from jaios.social_ecosystem_chain.bridge_protocol import BridgeMessage, BridgeProtocol, BridgeProtocolError
from jaios.social_ecosystem_chain.rpc_acceptance import RpcAcceptanceError, run_rpc_acceptance
from jaios.social_ecosystem_chain.rpc_connector import ReadOnlyRpcConnector
from jaios.social_ecosystem_chain.signature_quorum import SignatureQuorumError, aggregate_signature_quorum
from jaios.social_ecosystem_chain.signing_boundary import SigningRequest, SigningResult


ROOT = Path(__file__).resolve().parents[1]


class ReleaseHardeningTests(unittest.TestCase):
    def test_signature_quorum_is_key_distinct_and_deterministic(self):
        request = SigningRequest("a" * 64, "b" * 64, "bsc-testnet", "bridge-relayer-attestation", "kms://testnet/a")
        results = [
            SigningResult(request.request_digest, f"kms://testnet/{key}", char * 130, True)
            for key, char in (("b", "b"), ("a", "a"), ("c", "c"))
        ]
        first = aggregate_signature_quorum(request, results, threshold=2)
        second = aggregate_signature_quorum(request, reversed(results), threshold=2)
        self.assertEqual(first.aggregate_digest, second.aggregate_digest)
        self.assertEqual(first.key_resources, ("kms://testnet/a", "kms://testnet/b"))

    def test_signature_quorum_rejects_duplicate_key(self):
        request = SigningRequest("a" * 64, "b" * 64, "bsc-testnet", "bridge-relayer-attestation", "kms://testnet/a")
        result = SigningResult(request.request_digest, "kms://testnet/a", "a" * 130, True)
        with self.assertRaises(SignatureQuorumError):
            aggregate_signature_quorum(request, [result, result], threshold=2)

    def test_rpc_acceptance_and_regression_rejection(self):
        replies = iter(["0x10", "0x11", {"number": "0x11", "hash": "0x" + "a" * 64}])

        def transport(endpoint, payload, headers, timeout):
            request = json.loads(payload)
            return json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": next(replies)}).encode()

        evidence = run_rpc_acceptance(ReadOnlyRpcConnector("bsc-testnet", transport=transport))
        self.assertEqual(evidence.second_height, 17)
        self.assertFalse(evidence.write_methods_exposed)

        regressing = iter(["0x11", "0x10"])

        def bad_transport(endpoint, payload, headers, timeout):
            request = json.loads(payload)
            return json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": next(regressing)}).encode()

        with self.assertRaises(RpcAcceptanceError):
            run_rpc_acceptance(ReadOnlyRpcConnector("bsc-testnet", transport=bad_transport))

    def test_randomized_rate_limit_invariant(self):
        random.seed(20260723)
        for _ in range(100):
            per_tx = random.randint(1, 10_000)
            daily = random.randint(per_tx, per_tx * 20)
            protocol = BridgeProtocol(
                route_digest="a" * 64,
                allowed_networks=["junca-public-testnet", "bsc-testnet"],
                relayer_ids=["a", "b", "c"],
                threshold=2,
                required_confirmations=1,
                per_transaction_limit=per_tx,
                daily_limit=daily,
                paused=False,
            )
            self.assertLessEqual(protocol.per_transaction_limit, protocol.daily_limit)
            message = BridgeMessage(
                route_digest="a" * 64,
                direction="junca-public-testnet->bsc-testnet",
                source_network="junca-public-testnet",
                destination_network="bsc-testnet",
                nonce=1,
                source_transaction="b" * 64,
                source_block=1,
                asset_type="fungible",
                source_asset="source",
                destination_asset="destination",
                sender="sender",
                recipient="recipient",
                value=per_tx + 1,
            )
            record = protocol.observe(message)
            record.confirmations = 1
            record.state = record.state.ATTESTED
            with self.assertRaises(BridgeProtocolError):
                protocol.prepare_execution(message.digest)

    def test_deployment_bundle_from_compiler_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for source in (
                "JuncaTestnetBridge",
                "JuncaBridgeAssetAdapter",
                "JuncaTestnetMintableERC20",
                "JuncaTestnetMintableERC721",
            ):
                (output / f"fixture_{source}.abi").write_text("[]")
                (output / f"fixture_{source}.bin").write_text("00")
            bundle = build_deployment_bundle(ROOT / "contracts/junca-social-ecosystem-chain", output)
            self.assertEqual(bundle.evidence["state"], "BUILD_EVIDENCE_READY")
            self.assertFalse(bundle.evidence["deployment_performed"])


if __name__ == "__main__":
    unittest.main()
