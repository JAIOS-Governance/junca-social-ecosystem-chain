"""Allowlisted read-only JSON-RPC connector for BSC and TRON testnets."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


class RpcConnectorError(ValueError):
    pass


SAFE_METHODS = frozenset(
    {
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "eth_getLogs",
        "eth_getTransactionReceipt",
    }
)

ENDPOINTS = {
    "bsc-testnet": "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
    "tron-shasta": "https://api.shasta.trongrid.io/jsonrpc",
}


@dataclass(frozen=True)
class RpcResponse:
    request_id: int
    result: Any


Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class ReadOnlyRpcConnector:
    def __init__(
        self,
        network: str,
        *,
        endpoint: str | None = None,
        timeout_seconds: float = 10,
        transport: Transport | None = None,
    ) -> None:
        if network not in ENDPOINTS:
            raise RpcConnectorError("unsupported testnet")
        self.network = network
        self.endpoint = endpoint or ENDPOINTS[network]
        self.timeout_seconds = timeout_seconds
        self.transport = transport or self._urlopen_transport
        if self.endpoint != ENDPOINTS[network] or urlparse(self.endpoint).scheme != "https":
            raise RpcConnectorError("endpoint is not allowlisted")
        if not 0 < timeout_seconds <= 30:
            raise RpcConnectorError("invalid timeout")
        self._request_id = 0

    def call(self, method: str, params: Sequence[Any]) -> RpcResponse:
        if method not in SAFE_METHODS:
            raise RpcConnectorError("RPC method is not read-only allowlisted")
        if not isinstance(params, (list, tuple)):
            raise RpcConnectorError("params must be a sequence")
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": list(params),
        }
        raw = self.transport(
            self.endpoint,
            json.dumps(payload, separators=(",", ":")).encode(),
            {"Content-Type": "application/json", "User-Agent": "JAIOS-Testnet-RPC/1"},
            self.timeout_seconds,
        )
        try:
            response = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RpcConnectorError("invalid RPC response") from exc
        if not isinstance(response, Mapping) or response.get("jsonrpc") != "2.0":
            raise RpcConnectorError("invalid RPC envelope")
        if response.get("id") != self._request_id:
            raise RpcConnectorError("RPC response id mismatch")
        if "error" in response:
            raise RpcConnectorError("RPC returned an error")
        if "result" not in response:
            raise RpcConnectorError("RPC result is missing")
        return RpcResponse(self._request_id, response["result"])

    @staticmethod
    def _urlopen_transport(
        endpoint: str, payload: bytes, headers: Mapping[str, str], timeout: float
    ) -> bytes:
        request = urllib.request.Request(endpoint, data=payload, headers=dict(headers), method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RpcConnectorError("RPC HTTP status rejected")
            return response.read(2_000_000)
