"""Read-only live RPC acceptance harness with no transaction capability."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .rpc_connector import ReadOnlyRpcConnector


class RpcAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class RpcAcceptanceEvidence:
    network: str
    first_height: int
    second_height: int
    latest_block_hash: str
    advancing_or_stable: bool
    write_methods_exposed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def run_rpc_acceptance(connector: ReadOnlyRpcConnector) -> RpcAcceptanceEvidence:
    first = _quantity(connector.call("eth_blockNumber", []).result)
    second = _quantity(connector.call("eth_blockNumber", []).result)
    if second < first:
        raise RpcAcceptanceError("chain height regressed")
    block = connector.call("eth_getBlockByNumber", [hex(second), False]).result
    if not isinstance(block, dict):
        raise RpcAcceptanceError("latest block response is invalid")
    block_hash = str(block.get("hash", ""))
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash):
        raise RpcAcceptanceError("latest block hash is invalid")
    block_number = _quantity(block.get("number"))
    if block_number != second:
        raise RpcAcceptanceError("latest block height mismatch")
    return RpcAcceptanceEvidence(
        network=connector.network,
        first_height=first,
        second_height=second,
        latest_block_hash=block_hash.lower(),
        advancing_or_stable=True,
    )


def _quantity(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise RpcAcceptanceError("invalid RPC quantity")
    return int(value, 16)
