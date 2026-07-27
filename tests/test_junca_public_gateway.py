import unittest

from jaios.social_ecosystem_chain.public_gateway import (
    ALLOWED_METHODS,
    PublicGateway,
    PublicGatewayError,
    UpstreamResponse,
)


class PublicGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        self.health = {
            "status": "healthy",
            "head_height": 7,
            "head_hash": "0x" + "ab" * 32,
            "consensus": {
                "last_certificate_hash": "0x" + "cd" * 32,
                "last_certificate": {
                    "finality_status": "FINALIZED",
                    "height": 7,
                    "block_hash": "0x" + "ab" * 32,
                    "signed_power": 3,
                    "total_power": 3,
                },
            },
        }

        def transport(upstream, payload):
            self.calls.append((upstream, payload))
            if payload["method"] == "junca_health":
                result = self.health
            elif payload["method"] == "eth_chainId":
                result = "0x1352773"
            elif payload["method"] == "net_peerCount":
                result = "0x2"
            elif payload["method"] == "web3_clientVersion":
                result = "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
            elif payload["method"] == "eth_getBlockByNumber":
                result = {
                    "number": "0x7",
                    "hash": "0x" + "ab" * 32,
                    "parentHash": "0x" + "11" * 32,
                    "stateRoot": "0x" + "22" * 32,
                    "timestamp": "0x1234",
                    "transactions": [],
                }
            else:
                result = "0x7"
            return UpstreamResponse(
                200,
                {"jsonrpc": "2.0", "id": payload["id"], "result": result},
            )

        self.gateway = PublicGateway(transport=transport)

    def test_only_explicit_read_only_methods_are_forwarded(self) -> None:
        for method in sorted(ALLOWED_METHODS):
            status, body = self.gateway.rpc(
                {"jsonrpc": "2.0", "id": method, "method": method, "params": []}
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["id"], method)
        self.assertEqual(len(self.calls), len(ALLOWED_METHODS))

    def test_unsafe_and_unknown_methods_fail_closed_without_upstream_call(self) -> None:
        for method in (
            "eth_sendRawTransaction",
            "eth_sendTransaction",
            "admin_peers",
            "debug_traceBlock",
            "junca_health",
            "junca_propose",
            "junca_submitVote",
            "junca_broadcastVote",
            "unknown_method",
        ):
            before = len(self.calls)
            status, body = self.gateway.rpc(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": []}
            )
            self.assertEqual(status, 403)
            self.assertEqual(body["error"]["code"], -32601)
            self.assertEqual(len(self.calls), before)

    def test_invalid_envelopes_fail_closed(self) -> None:
        for payload in (
            None,
            {},
            {"jsonrpc": "1.0", "method": "eth_chainId", "params": []},
            {"jsonrpc": "2.0", "method": "eth_chainId"},
        ):
            status, body = self.gateway.rpc(payload)
            self.assertEqual(status, 400)
            self.assertEqual(body["error"]["code"], -32600)
        self.assertEqual(self.calls, [])

    def test_health_is_redacted_and_keeps_release_boundaries_false(self) -> None:
        status, body = self.gateway.health()
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "healthy")
        self.assertTrue(body["read_only"])
        self.assertFalse(body["mainnet_changed"])
        self.assertFalse(body["assets_moved"])
        self.assertFalse(body["bridge_activated"])
        self.assertNotIn("consensus", body["validator"])

    def test_explorer_returns_only_certificate_backed_finalized_head(self) -> None:
        status, body = self.gateway.explorer()
        self.assertEqual(status, 200)
        self.assertEqual(body["schema_version"], "junca-public-explorer/v2")
        self.assertTrue(body["finalized_only"])
        self.assertTrue(body["read_only"])
        self.assertEqual(body["network"]["chain_id"], "0x1352773")
        self.assertEqual(body["network"]["chain_id_decimal"], 20260723)
        self.assertEqual(body["network"]["peer_count"], 2)
        self.assertEqual(body["network"]["peer_count_hex"], "0x2")
        self.assertEqual(
            body["network"]["client_version"],
            "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1",
        )
        self.assertEqual(body["head"]["height"], 7)
        self.assertEqual(body["head"]["signed_power"], 3)
        self.assertEqual(body["head"]["timestamp"], "0x1234")
        self.assertEqual(body["head"]["state_root"], "0x" + "22" * 32)
        self.assertEqual(body["head"]["transaction_count"], 0)
        self.assertFalse(body["mainnet_changed"])
        self.assertFalse(body["assets_moved"])
        self.assertFalse(body["bridge_activated"])
        html_status, document = self.gateway.explorer_html()
        self.assertEqual(html_status, 200)
        self.assertIn("Finalized height", document)
        self.assertIn("Public Testnet / No Monetary Value", document)
        self.assertNotIn("private", document.lower())

    def test_explorer_rejects_nonfinalized_or_mismatched_head(self) -> None:
        self.health["consensus"]["last_certificate"]["block_hash"] = "0x" + "00" * 32
        status, body = self.gateway.explorer()
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "syncing")
        self.assertIsNone(body["head"])

    def test_explorer_does_not_expose_unverified_block_metadata(self) -> None:
        original_transport = self.gateway._transport

        def mismatched_block(upstream, payload):
            response = original_transport(upstream, payload)
            if payload["method"] == "eth_getBlockByNumber":
                return UpstreamResponse(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "hash": "0x" + "00" * 32,
                            "stateRoot": "private-value-must-not-leak",
                            "timestamp": "0x9999",
                            "transactions": ["0xsecret"],
                        },
                    },
                )
            return response

        self.gateway._transport = mismatched_block
        status, body = self.gateway.explorer()
        self.assertEqual(status, 200)
        self.assertIsNone(body["head"]["timestamp"])
        self.assertIsNone(body["head"]["state_root"])
        self.assertIsNone(body["head"]["transaction_count"])
        self.assertNotIn("private-value-must-not-leak", str(body))

    def test_upstream_must_remain_loopback_http(self) -> None:
        for upstream in (
            "https://127.0.0.1:8545/",
            "http://10.67.16.10:8545/",
            "http://example.com:8545/",
            "http://127.0.0.1/",
            "http://127.0.0.1:8545/rpc",
        ):
            with self.assertRaises(PublicGatewayError):
                PublicGateway(upstream)


if __name__ == "__main__":
    unittest.main()
