#!/usr/bin/env python3
"""Live, read-only acceptance checks for JUNCA Public Testnet endpoints.

Each atomic sample requires the health, explorer and RPC surfaces to describe the
same finalized block. The CLI performs a small, bounded series of complete
samples because independently refreshed read-only surfaces can briefly cross a
finalization boundary. A failed atomic sample is never accepted or normalized;
every failure reason and the accepted sample number are retained in the emitted
evidence.

This script never submits a transaction. The only unsafe requests are method-name
probes whose required result is rejection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HEALTH_URL = "https://health.jaios-governance.org/health"
EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json"
RPC_URL = "https://rpc.jaios-governance.org/"
SAFE_RPC_METHODS: Mapping[str, list[Any]] = {
    "eth_chainId": [],
    "eth_blockNumber": [],
    "eth_getBlockByNumber": ["latest", False],
    "net_peerCount": [],
    "web3_clientVersion": [],
}
UNSAFE_RPC_METHODS = (
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "admin_peers",
    "debug_traceBlock",
    "personal_unlockAccount",
    "miner_start",
    "junca_health",
    "junca_propose",
    "junca_submitVote",
    "junca_broadcastVote",
)
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")
HEALTH_SCHEMA = "junca-public-gateway-health/v1"
EXPLORER_SCHEMA = "junca-public-explorer/v5"
CERTIFICATE_SCHEMA = "junca-finality-certificate/v1"
CERTIFICATE_PROOF_SCHEMA = "junca-public-finality-certificate-proof/v1"
EXPECTED_VALIDATOR_IDS = (
    "validator-01",
    "validator-02",
    "validator-03",
)
HEX_DIGEST = re.compile(r"^0x[0-9a-f]{64}$")
HEX_SIGNATURE = re.compile(r"^[0-9a-f]{128}$")
CERTIFICATE_DOMAIN = b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
MAX_SAMPLE_ATTEMPTS = 10
MAX_SAMPLE_INTERVAL_SECONDS = 60.0
DEFAULT_SAMPLE_ATTEMPTS = 5
DEFAULT_SAMPLE_INTERVAL_SECONDS = 5.0
MAX_FINALIZED_HEAD_AGE_SECONDS = 120


class AcceptanceError(RuntimeError):
    """Raised when a public endpoint violates its acceptance contract."""


class BoundedAcceptanceError(AcceptanceError):
    """Raised after every bounded atomic sample has failed."""

    def __init__(self, samples: list[dict[str, Any]]) -> None:
        self.samples = samples
        final_error = samples[-1]["error"] if samples else "no samples executed"
        super().__init__(str(final_error))


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: Mapping[str, Any]


Transport = Callable[[str, str, Mapping[str, Any] | None], HttpResponse]
AtomicSample = Callable[[], Mapping[str, Any]]
Sleeper = Callable[[float], None]


def https_json_transport(
    method: str, url: str, payload: Mapping[str, Any] | None
) -> HttpResponse:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (OSError, URLError) as exc:
        raise AcceptanceError(f"{url}: endpoint unavailable") from exc
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{url}: response is not valid JSON") from exc
    if not isinstance(body, Mapping):
        raise AcceptanceError(f"{url}: response must be a JSON object")
    return HttpResponse(status, body)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _verify_boundaries(body: Mapping[str, Any], endpoint: str) -> None:
    for field in BOUNDARY_FIELDS:
        _require(body.get(field) is False, f"{endpoint}: {field} must be false")


def _rpc_payload(
    request_id: str, method: str, params: list[Any]
) -> Mapping[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def _verify_certificate_proof(
    proof: object,
    *,
    chain_id: int,
    height: int,
    block_hash: str,
    summary_certificate_hash: str,
    summary_signed_power: int,
    summary_total_power: int,
) -> Mapping[str, Any]:
    """Reconstruct one certificate without trusting the gateway summary."""

    _require(isinstance(proof, Mapping), "explorer: certificate proof is missing")
    _require(
        set(proof) == {"schema_version", "certificate", "votes"}
        and proof.get("schema_version") == CERTIFICATE_PROOF_SCHEMA,
        "explorer: certificate proof fields are invalid",
    )
    certificate = proof.get("certificate")
    certificate_fields = {
        "schema_version",
        "chain_id",
        "height",
        "round",
        "block_hash",
        "signed_power",
        "total_power",
        "validator_ids",
        "vote_hashes",
        "certificate_hash",
        "finality_status",
        *BOUNDARY_FIELDS,
    }
    _require(
        isinstance(certificate, Mapping)
        and set(certificate) == certificate_fields
        and certificate.get("schema_version") == CERTIFICATE_SCHEMA
        and certificate.get("finality_status") == "FINALIZED",
        "explorer: certificate fields are invalid",
    )
    _verify_boundaries(certificate, "explorer certificate")
    round_number = certificate.get("round")
    _require(
        certificate.get("chain_id") == chain_id
        and certificate.get("height") == height
        and certificate.get("block_hash") == block_hash
        and isinstance(round_number, int)
        and not isinstance(round_number, bool)
        and round_number >= 0,
        "explorer: certificate identity does not bind the finalized head",
    )
    _require(
        certificate.get("signed_power") == 3
        and certificate.get("total_power") == 3
        and summary_signed_power == 3
        and summary_total_power == 3,
        "explorer: exact three-of-three certificate power is required",
    )
    validator_ids = certificate.get("validator_ids")
    _require(
        validator_ids == list(EXPECTED_VALIDATOR_IDS),
        "explorer: certificate validator identities are not exact",
    )

    votes = proof.get("votes")
    _require(
        isinstance(votes, list) and len(votes) == 3,
        "explorer: certificate requires exactly three signed votes",
    )
    computed_vote_hashes: list[str] = []
    for expected_validator_id, vote in zip(EXPECTED_VALIDATOR_IDS, votes):
        _require(
            isinstance(vote, Mapping)
            and set(vote)
            == {
                "chain_id",
                "height",
                "round",
                "block_hash",
                "validator_id",
                "signature",
            },
            "explorer: certificate vote fields are invalid",
        )
        signature = vote.get("signature")
        _require(
            vote.get("chain_id") == chain_id
            and vote.get("height") == height
            and vote.get("round") == round_number
            and vote.get("block_hash") == block_hash
            and vote.get("validator_id") == expected_validator_id,
            "explorer: certificate vote does not bind the finalized head",
        )
        _require(
            isinstance(signature, str)
            and HEX_SIGNATURE.fullmatch(signature) is not None,
            "explorer: certificate vote signature is invalid",
        )
        signing_payload = json.dumps(
            {
                "block_hash": block_hash,
                "chain_id": chain_id,
                "height": height,
                "round": round_number,
                "validator_id": expected_validator_id,
                "vote_type": "PRECOMMIT",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        computed_vote_hashes.append(
            "0x"
            + hashlib.sha256(
                signing_payload + bytes.fromhex(signature)
            ).hexdigest()
        )

    supplied_vote_hashes = certificate.get("vote_hashes")
    _require(
        supplied_vote_hashes == computed_vote_hashes
        and len(set(computed_vote_hashes)) == 3
        and all(HEX_DIGEST.fullmatch(item) for item in computed_vote_hashes),
        "explorer: certificate vote hashes do not match signed votes",
    )
    certificate_body = {
        "block_hash": block_hash,
        "chain_id": chain_id,
        "height": height,
        "round": round_number,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": list(EXPECTED_VALIDATOR_IDS),
        "vote_hashes": computed_vote_hashes,
    }
    computed_certificate_hash = (
        "0x"
        + hashlib.sha256(
            CERTIFICATE_DOMAIN
            + json.dumps(
                certificate_body,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    _require(
        certificate.get("certificate_hash") == computed_certificate_hash
        and summary_certificate_hash == computed_certificate_hash,
        "explorer: certificate hash reconstruction failed",
    )
    return {
        "certificate_hash": computed_certificate_hash,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": list(EXPECTED_VALIDATOR_IDS),
        "vote_hashes": computed_vote_hashes,
        "signed_vote_count": 3,
        "recalculated": True,
    }


def run_acceptance(
    transport: Transport = https_json_transport,
    *,
    clock: Callable[[], float] = time.time,
) -> Mapping[str, Any]:
    """Run one complete, atomic endpoint-consistency sample."""

    checks: dict[str, Any] = {}

    health = transport("GET", HEALTH_URL, None)
    _require(health.status == 200, "health: expected HTTP 200")
    _require(
        health.body.get("schema_version") == HEALTH_SCHEMA,
        "health: unsupported schema_version",
    )
    _require(
        health.body.get("status") == "healthy",
        "health: status is not healthy",
    )
    _require(health.body.get("read_only") is True, "health: read_only must be true")
    _verify_boundaries(health.body, "health")
    checks["health"] = "PASS"

    explorer = transport("GET", EXPLORER_URL, None)
    _require(explorer.status == 200, "explorer: expected HTTP 200")
    _require(
        explorer.body.get("schema_version") == EXPLORER_SCHEMA,
        "explorer: v5 schema is required",
    )
    _require(
        explorer.body.get("status") == "ready",
        "explorer: status is not ready",
    )
    _require(
        explorer.body.get("finalized_only") is True,
        "explorer: finalized_only must be true",
    )
    _require(
        explorer.body.get("read_only") is True,
        "explorer: read_only must be true",
    )
    _verify_boundaries(explorer.body, "explorer")
    network = explorer.body.get("network")
    _require(isinstance(network, Mapping), "explorer: network metadata is missing")
    _require(
        isinstance(network.get("chain_id"), str)
        and isinstance(network.get("chain_id_decimal"), int)
        and not isinstance(network["chain_id_decimal"], bool)
        and network["chain_id_decimal"] > 0
        and network["chain_id"] == hex(network["chain_id_decimal"]),
        "explorer: invalid chain id",
    )
    _require(
        isinstance(network.get("client_version"), str)
        and bool(network["client_version"]),
        "explorer: invalid client version",
    )
    _require(
        isinstance(network.get("peer_count"), int)
        and not isinstance(network["peer_count"], bool)
        and network["peer_count"] == 2
        and isinstance(network.get("peer_count_hex"), str)
        and network["peer_count_hex"] == "0x2",
        "explorer: exact two-peer quorum is required",
    )
    head = explorer.body.get("head")
    _require(isinstance(head, Mapping), "explorer: finalized head is missing")
    _require(
        isinstance(head.get("height"), int)
        and not isinstance(head["height"], bool)
        and head["height"] >= 1,
        "explorer: invalid finalized height",
    )
    _require(
        isinstance(head.get("hash"), str)
        and HEX_DIGEST.fullmatch(head["hash"]) is not None,
        "explorer: invalid finalized hash",
    )
    _require(
        isinstance(head.get("certificate_hash"), str)
        and HEX_DIGEST.fullmatch(head["certificate_hash"]) is not None,
        "explorer: finalized certificate is missing",
    )
    _require(
        isinstance(head.get("signed_power"), int)
        and not isinstance(head["signed_power"], bool)
        and isinstance(head.get("total_power"), int)
        and not isinstance(head["total_power"], bool),
        "explorer: invalid finality power",
    )
    certificate_check = _verify_certificate_proof(
        head.get("certificate"),
        chain_id=network["chain_id_decimal"],
        height=head["height"],
        block_hash=head["hash"],
        summary_certificate_hash=head["certificate_hash"],
        summary_signed_power=head["signed_power"],
        summary_total_power=head["total_power"],
    )
    _require(
        isinstance(head.get("timestamp"), str)
        and head["timestamp"].startswith("0x"),
        "explorer: finalized block timestamp is missing",
    )
    try:
        finalized_timestamp = int(head["timestamp"], 16)
    except (TypeError, ValueError) as exc:
        raise AcceptanceError(
            "explorer: finalized block timestamp is invalid"
        ) from exc
    observed_epoch = int(clock())
    _require(
        0 <= observed_epoch - finalized_timestamp
        <= MAX_FINALIZED_HEAD_AGE_SECONDS,
        "explorer: finalized block is stale or future-dated",
    )
    _require(
        isinstance(head.get("state_root"), str)
        and head["state_root"].startswith("0x"),
        "explorer: finalized block state root is missing",
    )
    _require(
        isinstance(head.get("transaction_count"), int)
        and head["transaction_count"] >= 0,
        "explorer: invalid transaction count",
    )
    checks["explorer"] = {
        "result": "PASS",
        "finalized_height": head["height"],
        "finalized_hash": head["hash"],
        "signed_power": certificate_check["signed_power"],
        "total_power": certificate_check["total_power"],
        "certificate_hash": certificate_check["certificate_hash"],
        "peer_count": network["peer_count"],
    }

    safe_results: dict[str, Any] = {}
    for index, (method, params) in enumerate(SAFE_RPC_METHODS.items(), start=1):
        request_id = f"safe-{index}"
        response = transport(
            "POST", RPC_URL, _rpc_payload(request_id, method, params)
        )
        _require(response.status == 200, f"rpc {method}: expected HTTP 200")
        _require(
            response.body.get("jsonrpc") == "2.0",
            f"rpc {method}: invalid version",
        )
        _require(response.body.get("id") == request_id, f"rpc {method}: id mismatch")
        _require("result" in response.body, f"rpc {method}: result is missing")
        _require("error" not in response.body, f"rpc {method}: unexpected error")
        safe_results[method] = response.body["result"]
    _require(
        safe_results["eth_chainId"] == network["chain_id"],
        "rpc/explorer: chain id mismatch",
    )
    _require(
        safe_results["web3_clientVersion"] == network["client_version"],
        "rpc/explorer: client version mismatch",
    )
    _require(
        safe_results["net_peerCount"] == network["peer_count_hex"],
        "rpc/explorer: peer count mismatch",
    )
    _require(
        safe_results["eth_blockNumber"] == hex(head["height"]),
        "rpc/explorer: finalized height mismatch",
    )
    latest_block = safe_results["eth_getBlockByNumber"]
    _require(
        isinstance(latest_block, Mapping)
        and latest_block.get("hash") == head["hash"]
        and latest_block.get("timestamp") == head["timestamp"]
        and latest_block.get("stateRoot") == head["state_root"],
        "rpc/explorer: finalized block mismatch",
    )
    transactions = latest_block.get("transactions")
    _require(
        isinstance(transactions, list)
        and len(transactions) == head["transaction_count"],
        "rpc/explorer: transaction count mismatch",
    )
    checks["safe_rpc"] = {
        "result": "PASS",
        "methods": sorted(safe_results),
    }

    for index, method in enumerate(UNSAFE_RPC_METHODS, start=1):
        request_id = f"unsafe-{index}"
        response = transport(
            "POST", RPC_URL, _rpc_payload(request_id, method, [])
        )
        _require(response.status == 403, f"rpc {method}: expected HTTP 403")
        error = response.body.get("error")
        _require(isinstance(error, Mapping), f"rpc {method}: error is missing")
        _require(error.get("code") == -32601, f"rpc {method}: expected -32601")
        _require(response.body.get("id") == request_id, f"rpc {method}: id mismatch")
    checks["unsafe_rpc_rejection"] = {
        "result": "PASS",
        "methods": list(UNSAFE_RPC_METHODS),
    }

    return {
        "status": "PASS",
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "observed_at": datetime.fromtimestamp(
            observed_epoch,
            timezone.utc,
        ).isoformat(),
        "endpoints": {
            "health": HEALTH_URL,
            "explorer": EXPLORER_URL,
            "rpc": RPC_URL,
        },
        "finalized_head": {
            "height": head["height"],
            "hash": head["hash"],
            "timestamp": head["timestamp"],
            "state_root": head["state_root"],
            "certificate_hash": head["certificate_hash"],
        },
        "checks": checks,
    }


def run_bounded_acceptance(
    sample: AtomicSample | None = None,
    *,
    attempts: int = DEFAULT_SAMPLE_ATTEMPTS,
    interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> Mapping[str, Any]:
    """Run bounded full-consistency samples without weakening one sample."""

    if isinstance(attempts, bool) or not isinstance(attempts, int):
        raise ValueError("attempts must be an integer")
    if not 1 <= attempts <= MAX_SAMPLE_ATTEMPTS:
        raise ValueError(f"attempts must be between 1 and {MAX_SAMPLE_ATTEMPTS}")
    if isinstance(interval_seconds, bool) or not isinstance(
        interval_seconds, (int, float)
    ):
        raise ValueError("interval_seconds must be numeric")
    interval = float(interval_seconds)
    if not 0 <= interval <= MAX_SAMPLE_INTERVAL_SECONDS:
        raise ValueError(
            "interval_seconds must be between 0 and "
            f"{MAX_SAMPLE_INTERVAL_SECONDS:g}"
        )

    atomic_sample = sample or run_acceptance
    samples: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        sample_started_at = datetime.now(timezone.utc).isoformat()
        try:
            report = dict(atomic_sample())
        except AcceptanceError as exc:
            samples.append(
                {
                    "attempt": attempt,
                    "status": "FAIL",
                    "observed_at": sample_started_at,
                    "error": str(exc),
                }
            )
            if attempt < attempts:
                sleeper(interval)
            continue

        samples.append(
            {
                "attempt": attempt,
                "status": "PASS",
                "observed_at": report.get("observed_at", sample_started_at),
                "finalized_head": report.get("finalized_head"),
            }
        )
        report["sampling"] = {
            "schema_version": "junca-public-endpoint-sampling/v1",
            "strategy": "BOUNDED_FULL_CONSISTENCY_SAMPLES",
            "max_attempts": attempts,
            "interval_seconds": interval,
            "accepted_attempt": attempt,
            "sample_count": len(samples),
            "samples": samples,
        }
        return report

    raise BoundedAcceptanceError(samples)


def _failure_report(
    error: AcceptanceError,
    *,
    attempts: int,
    interval_seconds: float,
) -> Mapping[str, Any]:
    samples = error.samples if isinstance(error, BoundedAcceptanceError) else []
    return {
        "status": "FAIL",
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": {
            "health": HEALTH_URL,
            "explorer": EXPLORER_URL,
            "rpc": RPC_URL,
        },
        "error": str(error),
        "sampling": {
            "schema_version": "junca-public-endpoint-sampling/v1",
            "strategy": "BOUNDED_FULL_CONSISTENCY_SAMPLES",
            "max_attempts": attempts,
            "interval_seconds": float(interval_seconds),
            "accepted_attempt": None,
            "sample_count": len(samples),
            "samples": samples,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON instead of indented JSON",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_SAMPLE_ATTEMPTS,
        help="maximum complete endpoint-consistency samples",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
        help="delay between failed complete samples",
    )
    args = parser.parse_args()
    try:
        report = run_bounded_acceptance(
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
        )
    except (AcceptanceError, ValueError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, AcceptanceError):
            parser.error(str(exc))
        report = _failure_report(
            exc,
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
        )
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
