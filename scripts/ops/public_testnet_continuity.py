#!/usr/bin/env python3
"""Read-only Public Testnet continuity sampler.

The sampler compares the governed Operational API with the public Explorer JSON
across a bounded observation window. It never submits transactions, dispatches
validator commands, mutates infrastructure, or infers missing runtime values.
"""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ContinuityError(ValueError):
    """Raised when public evidence violates a continuity invariant."""


@dataclass(frozen=True)
class NormalizedSnapshot:
    source: str
    chain_id: int
    finalized_height: int
    finalized_hash: str | None
    certificate_hash: str | None
    signed_power: int
    total_power: int
    mainnet_changed: bool
    assets_moved: bool
    bridge_activated: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _first(value: Mapping[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        found = _path(value, path)
        if found is not None:
            return found
    return None


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ContinuityError(f"{label} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            result = int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError as exc:
            raise ContinuityError(f"{label} must be an integer") from exc
    else:
        raise ContinuityError(f"{label} must be an integer")
    if result < 0:
        raise ContinuityError(f"{label} must not be negative")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContinuityError(f"{label} must be a boolean")
    return value


def _hash(value: Any, label: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ContinuityError(f"{label} must be a hexadecimal string")
    normalized = value.lower()
    if len(normalized) != 66 or not normalized.startswith("0x"):
        raise ContinuityError(f"{label} must be a 32-byte hexadecimal value")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise ContinuityError(f"{label} must be a 32-byte hexadecimal value") from exc
    return normalized


def _quorum(value: Mapping[str, Any]) -> tuple[int, int]:
    signed = _first(
        value,
        (
            "signed_power",
            "finality.signed_power",
            "runtime_evidence.signed_power",
            "consensus.signed_power",
            "consensus.last_certificate.signed_power",
        ),
    )
    total = _first(
        value,
        (
            "total_power",
            "finality.total_power",
            "runtime_evidence.total_power",
            "consensus.total_power",
            "consensus.last_certificate.total_power",
        ),
    )
    if signed is not None or total is not None:
        if signed is None or total is None:
            raise ContinuityError("finality power evidence is incomplete")
        return _integer(signed, "signed_power"), _integer(total, "total_power")

    ratio = _first(value, ("quorum", "finality.quorum", "runtime_evidence.quorum"))
    if isinstance(ratio, str) and "/" in ratio:
        left, right = ratio.split("/", 1)
        return _integer(left.strip(), "signed_power"), _integer(
            right.strip(), "total_power"
        )
    raise ContinuityError("finality power evidence is required")


def normalize_snapshot(
    payload: Mapping[str, Any], *, source: str, require_safety: bool
) -> NormalizedSnapshot:
    if not isinstance(payload, Mapping):
        raise ContinuityError(f"{source} payload must be an object")

    chain_id = _integer(
        _first(
            payload,
            (
                "chain_id",
                "chainId",
                "runtime_evidence.chain_id",
                "network.chain_id",
                "status.chain_id",
            ),
        ),
        f"{source} chain_id",
    )
    height = _integer(
        _first(
            payload,
            (
                "finalized_height",
                "head_height",
                "height",
                "runtime_evidence.finalized_height",
                "consensus.head_height",
                "status.finalized_height",
                "latest.height",
            ),
        ),
        f"{source} finalized_height",
    )
    finalized_hash = _hash(
        _first(
            payload,
            (
                "finalized_hash",
                "head_hash",
                "block_hash",
                "runtime_evidence.finalized_hash",
                "consensus.head_hash",
                "latest.hash",
            ),
        ),
        f"{source} finalized_hash",
    )
    certificate_hash = _hash(
        _first(
            payload,
            (
                "certificate_hash",
                "last_certificate_hash",
                "finality.certificate_hash",
                "runtime_evidence.certificate_hash",
                "consensus.last_certificate_hash",
                "consensus.last_certificate.certificate_hash",
            ),
        ),
        f"{source} certificate_hash",
    )
    signed_power, total_power = _quorum(payload)
    if total_power <= 0 or signed_power <= (total_power * 2) // 3:
        raise ContinuityError(f"{source} finality does not exceed two-thirds")

    safety_paths = {
        "mainnet_changed": (
            "mainnet_changed",
            "runtime_evidence.mainnet_changed",
            "safety.mainnet_changed",
        ),
        "assets_moved": (
            "assets_moved",
            "runtime_evidence.assets_moved",
            "safety.assets_moved",
        ),
        "bridge_activated": (
            "bridge_activated",
            "runtime_evidence.bridge_activated",
            "safety.bridge_activated",
        ),
    }
    safety: dict[str, bool] = {}
    for label, paths in safety_paths.items():
        found = _first(payload, paths)
        if found is None:
            if require_safety:
                raise ContinuityError(f"{source} {label} evidence is required")
            safety[label] = False
        else:
            safety[label] = _boolean(found, f"{source} {label}")
        if safety[label] is not False:
            raise ContinuityError(f"{source} {label} must remain false")

    return NormalizedSnapshot(
        source=source,
        chain_id=chain_id,
        finalized_height=height,
        finalized_hash=finalized_hash,
        certificate_hash=certificate_hash,
        signed_power=signed_power,
        total_power=total_power,
        mainnet_changed=safety["mainnet_changed"],
        assets_moved=safety["assets_moved"],
        bridge_activated=safety["bridge_activated"],
    )


def compare_pair(
    operational: NormalizedSnapshot,
    explorer: NormalizedSnapshot,
    *,
    expected_chain_id: int,
) -> None:
    if operational.chain_id != expected_chain_id or explorer.chain_id != expected_chain_id:
        raise ContinuityError("public evidence chain_id does not match the approved network")
    if operational.finalized_height != explorer.finalized_height:
        raise ContinuityError("Operational API and Explorer finalized heights diverge")
    if (
        operational.finalized_hash is not None
        and explorer.finalized_hash is not None
        and operational.finalized_hash != explorer.finalized_hash
    ):
        raise ContinuityError("Operational API and Explorer finalized hashes diverge")
    if (
        operational.certificate_hash is not None
        and explorer.certificate_hash is not None
        and operational.certificate_hash != explorer.certificate_hash
    ):
        raise ContinuityError("Operational API and Explorer certificates diverge")
    if (
        operational.signed_power != explorer.signed_power
        or operational.total_power != explorer.total_power
    ):
        raise ContinuityError("Operational API and Explorer finality power diverges")


def evaluate_observations(
    observations: list[dict[str, Any]], *, require_advancement: bool
) -> str:
    if len(observations) < 2:
        raise ContinuityError("at least two observations are required")
    heights = [int(item["operational"]["finalized_height"]) for item in observations]
    if any(current < previous for previous, current in zip(heights, heights[1:])):
        raise ContinuityError("finalized height regressed during the observation window")
    advanced = heights[-1] > heights[0]
    if require_advancement and not advanced:
        raise ContinuityError("finalized height did not advance during the observation window")
    return "ACTIVE_ADVANCING" if advanced else "ACTIVE_STABLE_READ_ONLY"


def _fetch(url: str, *, timeout: int) -> Mapping[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ContinuityError("evidence URLs must use HTTPS")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "JUNCA-Public-Testnet-Continuity/1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ContinuityError("public evidence response exceeds size boundary")
        if response.status != 200:
            raise ContinuityError(f"public evidence endpoint returned {response.status}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContinuityError("public evidence endpoint did not return JSON") from exc
    if not isinstance(payload, Mapping):
        raise ContinuityError("public evidence endpoint must return a JSON object")
    return payload


def _write(path: Path, document: Mapping[str, Any]) -> None:
    body = dict(document)
    body.pop("evidence_sha256", None)
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    body["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def parser() -> ArgumentParser:
    result = ArgumentParser()
    result.add_argument(
        "--operational-url",
        default="https://chain.jaios-governance.org/api/operational",
    )
    result.add_argument(
        "--explorer-url",
        default="https://explorer.jaios-governance.org/explorer.json",
    )
    result.add_argument("--expected-chain-id", type=int, default=20260723)
    result.add_argument("--samples", type=int, default=3)
    result.add_argument("--interval-seconds", type=int, default=30)
    result.add_argument("--timeout-seconds", type=int, default=15)
    result.add_argument("--source-sha", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--require-advancement", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if not 2 <= args.samples <= 20:
        raise ContinuityError("samples must be between 2 and 20")
    if not 1 <= args.interval_seconds <= 900:
        raise ContinuityError("interval must be between 1 and 900 seconds")
    if not 1 <= args.timeout_seconds <= 60:
        raise ContinuityError("timeout must be between 1 and 60 seconds")
    if len(args.source_sha) != 40:
        raise ContinuityError("source SHA must contain 40 hexadecimal characters")
    try:
        int(args.source_sha, 16)
    except ValueError as exc:
        raise ContinuityError("source SHA must contain 40 hexadecimal characters") from exc

    target = Path(args.output)
    observations: list[dict[str, Any]] = []
    try:
        for index in range(args.samples):
            operational = normalize_snapshot(
                _fetch(args.operational_url, timeout=args.timeout_seconds),
                source="operational_api",
                require_safety=True,
            )
            explorer = normalize_snapshot(
                _fetch(args.explorer_url, timeout=args.timeout_seconds),
                source="explorer_json",
                require_safety=False,
            )
            compare_pair(
                operational,
                explorer,
                expected_chain_id=args.expected_chain_id,
            )
            observations.append(
                {
                    "sample": index + 1,
                    "observed_at": utc_now(),
                    "operational": asdict(operational),
                    "explorer": asdict(explorer),
                }
            )
            if index + 1 < args.samples:
                time.sleep(args.interval_seconds)
        state = evaluate_observations(
            observations, require_advancement=args.require_advancement
        )
        document = {
            "schema_version": "junca-public-testnet-continuity/v1",
            "state": state,
            "source_sha": args.source_sha,
            "expected_chain_id": args.expected_chain_id,
            "observation_started_at": observations[0]["observed_at"],
            "observation_completed_at": observations[-1]["observed_at"],
            "sample_count": len(observations),
            "interval_seconds": args.interval_seconds,
            "advancement_required": args.require_advancement,
            "observations": observations,
            "transaction_submission_enabled": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
        _write(target, document)
        print(target)
        print(json.dumps({"state": state, "height": observations[-1]["operational"]["finalized_height"]}, sort_keys=True))
        return 0
    except Exception as exc:
        _write(
            target,
            {
                "schema_version": "junca-public-testnet-continuity/v1",
                "state": "REJECTED",
                "source_sha": args.source_sha,
                "observed_at": utc_now(),
                "sample_count": len(observations),
                "observations": observations,
                "error": f"{type(exc).__name__}: {exc}",
                "transaction_submission_enabled": False,
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
