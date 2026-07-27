import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "junca_public_testnet_endpoint_test.py"
)
SPEC = importlib.util.spec_from_file_location("junca_endpoint_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
endpoint_test = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = endpoint_test
SPEC.loader.exec_module(endpoint_test)


class PublicTestnetEndpointAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []

    def transport(self, method, url, payload):
        self.calls.append((method, url, payload))
        if url == endpoint_test.HEALTH_URL:
            return endpoint_test.HttpResponse(
                200,
                {
                    "schema_version": "junca-public-gateway-health/v1",
                    "status": "healthy",
                    "read_only": True,
                    "mainnet_changed": False,
                    "assets_moved": False,
                    "bridge_activated": False,
                },
            )
        if url == endpoint_test.EXPLORER_URL:
            return endpoint_test.HttpResponse(
                200,
                {
                    "schema_version": "junca-public-explorer/v2",
                    "status": "ready",
                    "finalized_only": True,
                    "read_only": True,
                    "network": {
                        "chain_id": "0x1352773",
                        "chain_id_decimal": 20260723,
                        "client_version": (
                            "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
                        ),
                        "peer_count": 2,
                        "peer_count_hex": "0x2",
                    },
                    "head": {
                        "height": 7,
                        "hash": "0x" + "ab" * 32,
                        "certificate_hash": "0x" + "cd" * 32,
                        "signed_power": 3,
                        "total_power": 3,
                        "timestamp": "0x1234",
                        "state_root": "0x" + "22" * 32,
                        "transaction_count": 0,
                    },
                    "mainnet_changed": False,
                    "assets_moved": False,
                    "bridge_activated": False,
                },
            )
        if payload["method"] in endpoint_test.UNSAFE_RPC_METHODS:
            return endpoint_test.HttpResponse(
                403,
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32601, "message": "method not found"},
                },
            )
        safe_results = {
            "eth_chainId": "0x1352773",
            "eth_blockNumber": "0x7",
            "eth_getBlockByNumber": {
                "number": "0x7",
                "hash": "0x" + "ab" * 32,
                "timestamp": "0x1234",
                "stateRoot": "0x" + "22" * 32,
                "transactions": [],
            },
            "net_peerCount": "0x2",
            "web3_clientVersion": (
                "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
            ),
        }
        return endpoint_test.HttpResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": safe_results[payload["method"]],
            },
        )

    def test_complete_contract_passes_without_external_network(self):
        report = endpoint_test.run_acceptance(self.transport)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["health"], "PASS")
        self.assertEqual(report["checks"]["explorer"]["finalized_height"], 7)
        self.assertEqual(
            report["checks"]["safe_rpc"]["methods"],
            sorted(endpoint_test.SAFE_RPC_METHODS),
        )
        expected_calls = (
            2
            + len(endpoint_test.SAFE_RPC_METHODS)
            + len(endpoint_test.UNSAFE_RPC_METHODS)
        )
        self.assertEqual(len(self.calls), expected_calls)

    def test_boundary_drift_fails_closed_before_rpc_checks(self):
        def drifted_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.HEALTH_URL:
                body = dict(response.body)
                body["assets_moved"] = True
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError, "assets_moved must be false"
        ):
            endpoint_test.run_acceptance(drifted_transport)
        self.assertEqual(len(self.calls), 1)

    def test_nonfinalized_explorer_fails_closed(self):
        def syncing_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body.update({"status": "syncing", "head": None})
                return endpoint_test.HttpResponse(503, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 200"):
            endpoint_test.run_acceptance(syncing_transport)
        self.assertEqual(len(self.calls), 2)

    def test_legacy_database_without_certificate_body_fails_closed(self):
        def legacy_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body.update({"status": "syncing", "head": None})
                return endpoint_test.HttpResponse(503, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 200"):
            endpoint_test.run_acceptance(legacy_transport)
        self.assertEqual(len(self.calls), 2)

    def test_explorer_v1_cannot_pass_v2_rollout_gate(self):
        def v1_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body["schema_version"] = "junca-public-explorer/v1"
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "v2 schema is required"):
            endpoint_test.run_acceptance(v1_transport)

    def test_missing_certificate_body_projection_fails_closed(self):
        def incomplete_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body["head"] = dict(body["head"])
                body["head"]["certificate_hash"] = None
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError, "finalized certificate is missing"
        ):
            endpoint_test.run_acceptance(incomplete_transport)

    def test_unsafe_method_must_be_rejected_with_exact_contract(self):
        def permissive_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if (
                url == endpoint_test.RPC_URL
                and payload["method"] == "eth_sendTransaction"
            ):
                return endpoint_test.HttpResponse(
                    200,
                    {"jsonrpc": "2.0", "id": payload["id"], "result": "0xunsafe"},
                )
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 403"):
            endpoint_test.run_acceptance(permissive_transport)

    def test_safe_rpc_envelope_mismatch_fails(self):
        def mismatched_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if (
                url == endpoint_test.RPC_URL
                and payload["method"] == "eth_chainId"
            ):
                return endpoint_test.HttpResponse(
                    200, {"jsonrpc": "2.0", "id": "wrong", "result": "0x1"}
                )
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "id mismatch"):
            endpoint_test.run_acceptance(mismatched_transport)


if __name__ == "__main__":
    unittest.main()
