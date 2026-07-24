from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from jaios.social_ecosystem_chain import (
    ChainHealthError,
    ChainHealthProbe,
    ChainHealthStatus,
    load_network_specs,
    make_dashboard_probe,
)
from jaios.social_ecosystem_chain.health import DashboardStatus


NOW = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)


class FakeRpc:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(
        self,
        _endpoint: str,
        method: str,
        _params: list[object],
        _timeout: float,
    ) -> object:
        self.calls.append(method)
        value = self.responses[method]
        if isinstance(value, BaseException):
            raise value
        return value


class JuncaSocialEcosystemChainHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = load_network_specs(
            Path("config/junca_social_ecosystem_chain_networks.json")
        )[0]

    def test_healthy_network_collects_complete_evidence(self) -> None:
        transport = FakeRpc({
            "eth_chainId": "0x29c",
            "eth_blockNumber": "0x1234",
            "eth_getBlockByNumber": {"timestamp": hex(int(NOW.timestamp()) - 5)},
            "net_peerCount": "0x4",
            "web3_clientVersion": "junca/v0.2.8/linux-amd64/go1.17",
        })
        report = ChainHealthProbe(
            transport=transport,
            clock=lambda: NOW,
        ).probe(self.spec)

        self.assertEqual(report.status, ChainHealthStatus.HEALTHY)
        self.assertEqual(report.endpoints[0].block_number, 0x1234)
        self.assertEqual(report.endpoints[0].block_age_seconds, 5)
        self.assertEqual(report.endpoints[0].peer_count, 4)
        self.assertEqual(
            transport.calls,
            [
                "eth_chainId",
                "eth_blockNumber",
                "eth_getBlockByNumber",
                "net_peerCount",
                "web3_clientVersion",
            ],
        )

    def test_wrong_chain_id_fails_closed_before_other_queries(self) -> None:
        transport = FakeRpc({"eth_chainId": "0x1"})
        report = ChainHealthProbe(
            transport=transport,
            clock=lambda: NOW,
        ).probe(self.spec)

        endpoint = report.endpoints[0]
        self.assertEqual(report.status, ChainHealthStatus.UNHEALTHY)
        self.assertEqual(endpoint.failure_type, "CHAIN_ID_MISMATCH")
        self.assertEqual(transport.calls, ["eth_chainId"])

    def test_stale_head_is_unhealthy(self) -> None:
        transport = FakeRpc({
            "eth_chainId": "0x29c",
            "eth_blockNumber": "0x1234",
            "eth_getBlockByNumber": {"timestamp": hex(int(NOW.timestamp()) - 301)},
            "net_peerCount": "0x4",
            "web3_clientVersion": "junca/v0.2.8",
        })
        report = ChainHealthProbe(
            transport=transport,
            clock=lambda: NOW,
        ).probe(self.spec)

        self.assertEqual(report.status, ChainHealthStatus.UNHEALTHY)
        self.assertEqual(report.endpoints[0].failure_type, "STALE_HEAD")

    def test_zero_peers_is_degraded(self) -> None:
        transport = FakeRpc({
            "eth_chainId": "0x29c",
            "eth_blockNumber": "0x1234",
            "eth_getBlockByNumber": {"timestamp": hex(int(NOW.timestamp()) - 5)},
            "net_peerCount": "0x0",
            "web3_clientVersion": "junca/v0.2.8",
        })
        report = ChainHealthProbe(
            transport=transport,
            clock=lambda: NOW,
        ).probe(self.spec)

        self.assertEqual(report.status, ChainHealthStatus.DEGRADED)
        self.assertEqual(report.endpoints[0].failure_type, "NO_PEERS")

    def test_http_failure_does_not_expose_response_body(self) -> None:
        failure = HTTPError(
            "https://user:secret@rpc.example.invalid?token=secret",
            502,
            "secret upstream detail",
            hdrs=None,
            fp=None,
        )
        report = ChainHealthProbe(
            transport=FakeRpc({"eth_chainId": failure}),
            clock=lambda: NOW,
        ).probe(self.spec)

        endpoint = report.endpoints[0]
        self.assertEqual(endpoint.failure_type, "HTTP_502")
        self.assertEqual(endpoint.summary, "RPC endpoint returned HTTP 502")
        evidence = json.dumps(report.as_evidence())
        self.assertNotIn("secret", evidence)

    def test_dashboard_adapter_preserves_unhealthy_state(self) -> None:
        probe = ChainHealthProbe(
            transport=FakeRpc({"eth_chainId": "0x1"}),
            clock=lambda: NOW,
        )
        result = make_dashboard_probe(self.spec, probe=probe)("tenant-a")

        self.assertEqual(result.status, DashboardStatus.UNHEALTHY)
        self.assertEqual(result.metrics["expected_chain_id"], 668)

    def test_configuration_rejects_credentials_and_duplicate_chain_ids(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory, "networks.json")
            path.write_text(
                json.dumps({
                    "networks": [
                        {
                            "name": "mainnet",
                            "chain_id": 668,
                            "rpc_urls": ["https://user:secret@rpc.example.com"],
                            "websocket_urls": [],
                            "explorer_url": "https://scan.example.com",
                            "governance_url": "https://master.example.com",
                        },
                        {
                            "name": "other",
                            "chain_id": 668,
                            "rpc_urls": ["https://rpc-other.example.com"],
                            "websocket_urls": [],
                            "explorer_url": "https://scan-other.example.com",
                            "governance_url": "https://master-other.example.com",
                        },
                    ]
                }),
                encoding="utf-8",
            )
            with self.assertRaises(ChainHealthError):
                load_network_specs(path)


if __name__ == "__main__":
    unittest.main()
