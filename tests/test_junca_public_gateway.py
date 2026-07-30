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
        self.now = 1_800_000_060
        self.head_timestamp = 1_800_000_030
        certificate = {
            "schema_version": "junca-finality-certificate/v1",
            "chain_id": 20260723,
            "height": 7,
            "round": 0,
            "block_hash": "0x" + "ab" * 32,
            "certificate_hash": "0x" + "cd" * 32,
            "signed_power": 3,
            "total_power": 3,
            "validator_ids": [
                "validator-01",
                "validator-02",
                "validator-03",
            ],
            "vote_hashes": [
                "0x" + "01" * 32,
                "0x" + "02" * 32,
                "0x" + "03" * 32,
            ],
            "finality_status": "FINALIZED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        certificate_proof = {
            "schema_version": (
                "junca-public-finality-certificate-proof/v1"
            ),
            "certificate": certificate,
            "votes": [
                {
                    "chain_id": 20260723,
                    "height": 7,
                    "round": 0,
                    "block_hash": "0x" + "ab" * 32,
                    "validator_id": validator_id,
                    "signature": f"{index:02x}" * 64,
                }
                for index, validator_id in enumerate(
                    (
                        "validator-01",
                        "validator-02",
                        "validator-03",
                    ),
                    start=1,
                )
            ],
        }
        self.health = {
            "status": "healthy",
            "head_height": 7,
            "head_hash": "0x" + "ab" * 32,
            "head_timestamp": self.head_timestamp,
            "peer_count": 2,
            "automatic_finality_enabled": True,
            "automatic_finality_loop_running": True,
            "block_interval_seconds": 30,
            "slot_epoch_seconds": 1_800_000_000,
            "automatic_finality_last_successful_slot": 1,
            "automatic_finality_last_successful_height": 7,
            "health_gates": {
                "authenticated_peer_quorum": True,
                "automatic_finality": True,
                "current_three_of_three_certificate": True,
                "fresh_finalized_head": True,
            },
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "consensus": {
                "last_certificate_hash": "0x" + "cd" * 32,
                "head_height": 7,
                "required_vote_count": 3,
                "last_certificate": certificate,
                "last_certificate_proof": certificate_proof,
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
                    "timestamp": hex(self.head_timestamp),
                    "transactions": [],
                }
            else:
                result = "0x7"
            return UpstreamResponse(
                200,
                {"jsonrpc": "2.0", "id": payload["id"], "result": result},
            )

        self.runtime_artifact_commit = "12" * 20
        self.genesis_sha256 = "34" * 32
        self.node_artifact_sha256 = "56" * 32
        self.gateway = PublicGateway(
            transport=transport,
            runtime_artifact_commit=self.runtime_artifact_commit,
            genesis_sha256=self.genesis_sha256,
            node_artifact_sha256=self.node_artifact_sha256,
            clock=lambda: self.now,
        )

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
        self.assertEqual(body["validator"]["peer_count"], 2)
        self.assertTrue(body["read_only"])
        self.assertFalse(body["mainnet_changed"])
        self.assertFalse(body["assets_moved"])
        self.assertFalse(body["bridge_activated"])
        self.assertNotIn("consensus", body["validator"])

    def test_explorer_returns_only_certificate_backed_finalized_head(self) -> None:
        status, body = self.gateway.explorer()
        self.assertEqual(status, 200)
        self.assertEqual(body["schema_version"], "junca-public-explorer/v5")
        self.assertEqual(
            body["runtime_artifact"]["source_commit"],
            self.runtime_artifact_commit,
        )
        self.assertEqual(
            body["runtime_artifact"]["evidence_source"],
            "approved immutable validator runtime",
        )
        self.assertEqual(
            body["runtime_artifact"]["genesis_sha256"], self.genesis_sha256
        )
        self.assertEqual(
            body["runtime_artifact"]["node_artifact_sha256"],
            self.node_artifact_sha256,
        )
        self.assertIsInstance(body["observed_at"], str)
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
        self.assertEqual(
            body["head"]["certificate"]["certificate"][
                "validator_ids"
            ],
            ["validator-01", "validator-02", "validator-03"],
        )
        self.assertEqual(
            len(body["head"]["certificate"]["votes"]),
            3,
        )
        self.assertEqual(
            body["head"]["timestamp"],
            hex(self.head_timestamp),
        )
        self.assertEqual(body["head"]["parent_hash"], "0x" + "11" * 32)
        self.assertEqual(body["head"]["state_root"], "0x" + "22" * 32)
        self.assertEqual(body["head"]["transaction_count"], 0)
        self.assertFalse(body["mainnet_changed"])
        self.assertFalse(body["assets_moved"])
        self.assertFalse(body["bridge_activated"])
        html_status, document = self.gateway.explorer_html()
        self.assertEqual(html_status, 200)
        self.assertIn("Network Overview", document)
        self.assertIn("Finality Overview", document)
        self.assertIn("Latest Finalized Block", document)
        self.assertIn("Not Available Yet", document)
        self.assertIn("Public Testnet / No Monetary Value", document)
        self.assertIn("https://explorer.jaios-governance.org/", document)
        self.assertIn('href="https://jaios-governance.org/"', document)
        self.assertIn('href="https://chain.jaios-governance.org/"', document)
        self.assertIn("JAIOS Institutional Governance", document)
        self.assertIn("JUNCA Social Ecosystem Chain", document)
        self.assertIn("footer-destinations", document)
        self.assertIn("/junca-chain-logo.png", document)
        self.assertIn("/explorer-icon.png", document)
        self.assertIn("/manifest.webmanifest", document)
        self.assertNotIn("private", document.lower())

    def test_explorer_rejects_nonfinalized_or_mismatched_head(self) -> None:
        self.health["consensus"]["last_certificate"]["block_hash"] = "0x" + "00" * 32
        status, body = self.gateway.explorer()
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "syncing")
        self.assertIsNone(body["head"])

    def test_explorer_requires_complete_exact_certificate_proof(self) -> None:
        proof = self.health["consensus"]["last_certificate_proof"]
        self.health["consensus"]["last_certificate_proof"] = None
        status, body = self.gateway.explorer()
        self.assertEqual(status, 503)
        self.assertIsNone(body["head"])

        self.health["consensus"]["last_certificate_proof"] = proof
        proof["votes"][0]["signature"] = "00" * 63
        status, body = self.gateway.explorer()
        self.assertEqual(status, 503)
        self.assertIsNone(body["head"])

    def test_health_rejects_zero_or_one_peer_and_stale_head(self) -> None:
        for peer_count in (0, 1):
            self.health["peer_count"] = peer_count
            status, body = self.gateway.health()
            self.assertEqual(status, 503)
            self.assertEqual(body["status"], "unhealthy")
        self.health["peer_count"] = 2
        self.health["head_timestamp"] = self.now - 121
        self.health["slot_epoch_seconds"] = self.now - 151
        status, body = self.gateway.health()
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "unhealthy")

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
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "syncing")
        self.assertIsNone(body["head"])
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

    def test_runtime_artifact_commit_must_be_exact_lowercase_sha(self) -> None:
        for commit in ("pending", "A" * 40, "0" * 39, "0" * 41):
            with self.assertRaises(PublicGatewayError):
                PublicGateway(runtime_artifact_commit=commit)

    def test_runtime_artifact_digests_must_be_exact_lowercase_sha256(self) -> None:
        for digest in ("pending", "A" * 64, "0" * 63, "0" * 65):
            with self.assertRaises(PublicGatewayError):
                PublicGateway(genesis_sha256=digest)
            with self.assertRaises(PublicGatewayError):
                PublicGateway(node_artifact_sha256=digest)


if __name__ == "__main__":
    unittest.main()
