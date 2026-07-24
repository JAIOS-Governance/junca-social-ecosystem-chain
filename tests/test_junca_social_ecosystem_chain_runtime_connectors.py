import json
import tempfile
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.bridge_deployment import (
    BridgeDeploymentError,
    build_bridge_deployment_manifest,
    load_bridge_deployment_manifest,
)
from jaios.social_ecosystem_chain.rpc_connector import ReadOnlyRpcConnector, RpcConnectorError
from jaios.social_ecosystem_chain.signing_boundary import (
    ExternalSignerBoundary,
    SigningBoundaryError,
    SigningRequest,
)


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "config/junca_social_ecosystem_chain_bridge_deployment.pending.json"


class RuntimeConnectorTests(unittest.TestCase):
    def test_read_only_rpc_success_and_write_rejection(self):
        def transport(endpoint, payload, headers, timeout):
            request = json.loads(payload)
            return json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": "0x10"}).encode()

        connector = ReadOnlyRpcConnector("bsc-testnet", transport=transport)
        self.assertEqual(connector.call("eth_blockNumber", []).result, "0x10")
        with self.assertRaises(RpcConnectorError):
            connector.call("eth_sendRawTransaction", ["0x00"])

    def test_rpc_rejects_untrusted_endpoint_and_mismatched_id(self):
        with self.assertRaises(RpcConnectorError):
            ReadOnlyRpcConnector("bsc-testnet", endpoint="https://attacker.example")
        connector = ReadOnlyRpcConnector(
            "tron-shasta",
            transport=lambda *args: b'{"jsonrpc":"2.0","id":99,"result":"0x1"}',
        )
        with self.assertRaises(RpcConnectorError):
            connector.call("eth_blockNumber", [])

    def test_keyless_signing_boundary(self):
        provider = ExternalSignerBoundary(lambda key, digest: b"a" * 65, "kms://testnet/")
        request = SigningRequest(
            message_digest="a" * 64,
            route_digest="b" * 64,
            network="bsc-testnet",
            purpose="bridge-relayer-attestation",
            key_resource="kms://testnet/relayer-a/v1",
        )
        result = provider.sign(request)
        self.assertTrue(result.cryptographic_verification)
        self.assertEqual(len(result.signature), 130)

    def test_signing_rejects_raw_or_wrong_key_resource(self):
        provider = ExternalSignerBoundary(lambda key, digest: b"a" * 65, "kms://testnet/")
        request = SigningRequest(
            message_digest="a" * 64,
            route_digest="b" * 64,
            network="bsc-testnet",
            purpose="bridge-relayer-attestation",
            key_resource="raw-private-key",
        )
        with self.assertRaises(SigningBoundaryError):
            provider.sign(request)

    def test_pending_deployment_is_blocked(self):
        manifest = load_bridge_deployment_manifest(DEPLOYMENT)
        self.assertEqual(manifest.state, "BLOCKED")
        self.assertIn("contract_addresses_bound", manifest.blockers)

    def test_ready_requires_all_attestations_and_addresses(self):
        value = json.loads(DEPLOYMENT.read_text())
        for index, item in enumerate(value["contracts"].values(), 1):
            item["address"] = "0x" + f"{index:040x}"
        value["attestations"] = {key: True for key in value["attestations"]}
        self.assertEqual(
            build_bridge_deployment_manifest(value).state,
            "TESTNET_DEPLOYMENT_READY",
        )


if __name__ == "__main__":
    unittest.main()
