"""Fail-closed health readback for JUNCA Social Ecosystem Chain networks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from jaios.health import DashboardStatus, HealthProbeResult


class ChainHealthError(RuntimeError):
    """Raised when chain configuration or RPC evidence is invalid."""


class ChainHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

    @property
    def rank(self) -> int:
        return {
            ChainHealthStatus.HEALTHY: 0,
            ChainHealthStatus.DEGRADED: 1,
            ChainHealthStatus.UNHEALTHY: 2,
        }[self]


@dataclass(frozen=True)
class NetworkSpec:
    name: str
    chain_id: int
    rpc_urls: tuple[str, ...]
    websocket_urls: tuple[str, ...]
    explorer_url: str
    governance_url: str
    max_block_age_seconds: int = 300


@dataclass(frozen=True)
class ChainEndpointHealth:
    endpoint: str
    status: ChainHealthStatus
    chain_id: int | None
    block_number: int | None
    block_age_seconds: int | None
    peer_count: int | None
    client_version: str
    latency_ms: int
    failure_type: str
    summary: str


@dataclass(frozen=True)
class ChainHealthReport:
    network: str
    expected_chain_id: int
    status: ChainHealthStatus
    checked_at: str
    endpoints: tuple[ChainEndpointHealth, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-chain-health/v1",
            "network": self.network,
            "expected_chain_id": self.expected_chain_id,
            "status": self.status.value,
            "checked_at": self.checked_at,
            "endpoints": [
                {
                    **asdict(endpoint),
                    "status": endpoint.status.value,
                }
                for endpoint in self.endpoints
            ],
        }


class RpcTransport(Protocol):
    def __call__(
        self,
        endpoint: str,
        method: str,
        params: list[Any],
        timeout_seconds: float,
    ) -> Any: ...


Clock = Callable[[], datetime]


def load_network_specs(path: str | Path) -> tuple[NetworkSpec, ...]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainHealthError(f"unable to load network configuration: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainHealthError("network configuration must be a JSON object")
    networks = raw.get("networks")
    if not isinstance(networks, list) or not networks:
        raise ChainHealthError("network configuration requires a non-empty networks list")
    specs = tuple(_normalize_network(item) for item in networks)
    names = [spec.name for spec in specs]
    chain_ids = [spec.chain_id for spec in specs]
    if len(names) != len(set(names)):
        raise ChainHealthError("network names must be unique")
    if len(chain_ids) != len(set(chain_ids)):
        raise ChainHealthError("chain IDs must be unique")
    return specs


class ChainHealthProbe:
    """Collect deterministic, redacted JSON-RPC health evidence."""

    def __init__(
        self,
        *,
        transport: RpcTransport | None = None,
        clock: Clock | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ChainHealthError("timeout_seconds must be between 0 and 60")
        self._transport = transport or json_rpc_request
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._timeout_seconds = float(timeout_seconds)

    def probe(self, spec: NetworkSpec) -> ChainHealthReport:
        now = _normalize_time(self._clock())
        endpoints = tuple(self._probe_endpoint(spec, endpoint, now) for endpoint in spec.rpc_urls)
        if any(item.status is ChainHealthStatus.HEALTHY for item in endpoints):
            status = ChainHealthStatus.HEALTHY
        elif any(item.status is ChainHealthStatus.DEGRADED for item in endpoints):
            status = ChainHealthStatus.DEGRADED
        else:
            status = ChainHealthStatus.UNHEALTHY
        return ChainHealthReport(
            network=spec.name,
            expected_chain_id=spec.chain_id,
            status=status,
            checked_at=now.isoformat().replace("+00:00", "Z"),
            endpoints=endpoints,
        )

    def _probe_endpoint(
        self,
        spec: NetworkSpec,
        endpoint: str,
        now: datetime,
    ) -> ChainEndpointHealth:
        started = monotonic()
        safe_endpoint = redact_endpoint(endpoint)
        try:
            chain_id = _parse_quantity(
                self._transport(endpoint, "eth_chainId", [], self._timeout_seconds),
                "eth_chainId",
            )
            if chain_id != spec.chain_id:
                return _failed_endpoint(
                    endpoint=safe_endpoint,
                    started=started,
                    failure_type="CHAIN_ID_MISMATCH",
                    summary=f"expected chain ID {spec.chain_id}, received {chain_id}",
                    chain_id=chain_id,
                )
            block_number = _parse_quantity(
                self._transport(endpoint, "eth_blockNumber", [], self._timeout_seconds),
                "eth_blockNumber",
            )
            latest_block = self._transport(
                endpoint,
                "eth_getBlockByNumber",
                ["latest", False],
                self._timeout_seconds,
            )
            if not isinstance(latest_block, Mapping):
                raise ChainHealthError("eth_getBlockByNumber returned an invalid object")
            block_timestamp = _parse_quantity(latest_block.get("timestamp"), "block timestamp")
            block_age = max(0, int(now.timestamp()) - block_timestamp)
            peer_count = _parse_quantity(
                self._transport(endpoint, "net_peerCount", [], self._timeout_seconds),
                "net_peerCount",
            )
            client_version = _clean_text(
                self._transport(endpoint, "web3_clientVersion", [], self._timeout_seconds),
                "web3_clientVersion",
                maximum=160,
            )
            if block_age > spec.max_block_age_seconds:
                status = ChainHealthStatus.UNHEALTHY
                failure_type = "STALE_HEAD"
                summary = (
                    f"latest block is {block_age}s old; limit is "
                    f"{spec.max_block_age_seconds}s"
                )
            elif peer_count == 0:
                status = ChainHealthStatus.DEGRADED
                failure_type = "NO_PEERS"
                summary = "RPC responds but reports zero connected peers"
            else:
                status = ChainHealthStatus.HEALTHY
                failure_type = ""
                summary = "chain identity, head freshness and peer connectivity passed"
            return ChainEndpointHealth(
                endpoint=safe_endpoint,
                status=status,
                chain_id=chain_id,
                block_number=block_number,
                block_age_seconds=block_age,
                peer_count=peer_count,
                client_version=client_version,
                latency_ms=_elapsed_ms(started),
                failure_type=failure_type,
                summary=summary,
            )
        except (ChainHealthError, HTTPError, URLError, TimeoutError, OSError) as exc:
            return _failed_endpoint(
                endpoint=safe_endpoint,
                started=started,
                failure_type=_failure_type(exc),
                summary=_safe_error(exc),
            )


def json_rpc_request(
    endpoint: str,
    method: str,
    params: list[Any],
    timeout_seconds: float,
) -> Any:
    _validate_endpoint(endpoint)
    if not method or not method.replace("_", "").isalnum():
        raise ChainHealthError("invalid JSON-RPC method")
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "JUNCA-Global-Chain-Ops/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise ChainHealthError(f"RPC returned HTTP {response.status}")
        payload = response.read(1_048_577)
    if len(payload) > 1_048_576:
        raise ChainHealthError("RPC response exceeded 1 MiB")
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ChainHealthError("RPC returned non-JSON content") from exc
    if not isinstance(decoded, Mapping) or decoded.get("jsonrpc") != "2.0":
        raise ChainHealthError("RPC returned an invalid JSON-RPC envelope")
    if decoded.get("error") is not None:
        error = decoded["error"]
        code = error.get("code") if isinstance(error, Mapping) else "unknown"
        raise ChainHealthError(f"RPC method failed with code {code}")
    if "result" not in decoded:
        raise ChainHealthError("RPC response omitted result")
    return decoded["result"]


def make_dashboard_probe(
    spec: NetworkSpec,
    *,
    probe: ChainHealthProbe | None = None,
) -> Callable[[str], HealthProbeResult]:
    runner = probe or ChainHealthProbe()

    def run(_tenant_id: str) -> HealthProbeResult:
        report = runner.probe(spec)
        status = {
            ChainHealthStatus.HEALTHY: DashboardStatus.HEALTHY,
            ChainHealthStatus.DEGRADED: DashboardStatus.DEGRADED,
            ChainHealthStatus.UNHEALTHY: DashboardStatus.UNHEALTHY,
        }[report.status]
        endpoint_metrics = tuple(
            {
                "endpoint": item.endpoint,
                "status": item.status.value,
                "block_number": item.block_number,
                "block_age_seconds": item.block_age_seconds,
                "peer_count": item.peer_count,
                "latency_ms": item.latency_ms,
                "failure_type": item.failure_type,
            }
            for item in report.endpoints
        )
        return HealthProbeResult(
            status=status,
            summary=f"{spec.name} is {report.status.value}",
            metrics={
                "network": spec.name,
                "expected_chain_id": spec.chain_id,
                "checked_at": report.checked_at,
                "endpoints": endpoint_metrics,
            },
        )

    return run


def redact_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path or "", "", ""))


def _normalize_network(raw: Any) -> NetworkSpec:
    if not isinstance(raw, Mapping):
        raise ChainHealthError("each network must be a JSON object")
    name = _clean_text(raw.get("name"), "network name", maximum=64).lower()
    chain_id = raw.get("chain_id")
    if not isinstance(chain_id, int) or isinstance(chain_id, bool) or chain_id <= 0:
        raise ChainHealthError(f"{name}: chain_id must be a positive integer")
    rpc_urls = _normalize_urls(raw.get("rpc_urls"), f"{name}.rpc_urls", required=True)
    websocket_urls = _normalize_urls(
        raw.get("websocket_urls"),
        f"{name}.websocket_urls",
        required=False,
        schemes={"wss"},
    )
    explorer_url = _normalize_url(raw.get("explorer_url"), f"{name}.explorer_url")
    governance_url = _normalize_url(raw.get("governance_url"), f"{name}.governance_url")
    max_age = raw.get("max_block_age_seconds", 300)
    if not isinstance(max_age, int) or isinstance(max_age, bool) or not 15 <= max_age <= 3600:
        raise ChainHealthError(
            f"{name}: max_block_age_seconds must be between 15 and 3600"
        )
    return NetworkSpec(
        name=name,
        chain_id=chain_id,
        rpc_urls=rpc_urls,
        websocket_urls=websocket_urls,
        explorer_url=explorer_url,
        governance_url=governance_url,
        max_block_age_seconds=max_age,
    )


def _normalize_urls(
    value: Any,
    field: str,
    *,
    required: bool,
    schemes: set[str] | None = None,
) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list) or (required and not value):
        raise ChainHealthError(f"{field} must be a {'non-empty ' if required else ''}list")
    urls = tuple(_normalize_url(item, field, schemes=schemes) for item in value)
    if len(urls) != len(set(urls)):
        raise ChainHealthError(f"{field} contains duplicate endpoints")
    return urls


def _normalize_url(
    value: Any,
    field: str,
    *,
    schemes: set[str] | None = None,
) -> str:
    url = _clean_text(value, field, maximum=2048)
    parsed = urlsplit(url)
    allowed = schemes or {"https"}
    if parsed.scheme not in allowed or not parsed.hostname:
        raise ChainHealthError(f"{field} must use {', '.join(sorted(allowed))}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ChainHealthError(f"{field} must not contain credentials, query or fragment")
    return url


def _validate_endpoint(endpoint: str) -> None:
    _normalize_url(endpoint, "RPC endpoint")


def _parse_quantity(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ChainHealthError(f"{field} must be a hexadecimal quantity")
    try:
        parsed = int(value, 16)
    except ValueError as exc:
        raise ChainHealthError(f"{field} is not a valid hexadecimal quantity") from exc
    if parsed < 0:
        raise ChainHealthError(f"{field} must not be negative")
    return parsed


def _clean_text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ChainHealthError(f"{field} must be text")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ChainHealthError(f"{field} must contain 1-{maximum} characters")
    return text


def _normalize_time(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ChainHealthError("clock must return datetime")
    if value.tzinfo is None:
        raise ChainHealthError("clock must return timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _failed_endpoint(
    *,
    endpoint: str,
    started: float,
    failure_type: str,
    summary: str,
    chain_id: int | None = None,
) -> ChainEndpointHealth:
    return ChainEndpointHealth(
        endpoint=endpoint,
        status=ChainHealthStatus.UNHEALTHY,
        chain_id=chain_id,
        block_number=None,
        block_age_seconds=None,
        peer_count=None,
        client_version="",
        latency_ms=_elapsed_ms(started),
        failure_type=failure_type,
        summary=summary,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _failure_type(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP_{exc.code}"
    if isinstance(exc, (TimeoutError, URLError)) and "timed out" in str(exc).lower():
        return "TIMEOUT"
    if isinstance(exc, ChainHealthError):
        return "INVALID_RPC_EVIDENCE"
    return "CONNECTION_FAILURE"


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return f"RPC endpoint returned HTTP {exc.code}"
    if isinstance(exc, (TimeoutError, URLError)) and "timed out" in str(exc).lower():
        return "RPC endpoint timed out"
    if isinstance(exc, ChainHealthError):
        return str(exc)[:240]
    return "RPC endpoint connection failed"
