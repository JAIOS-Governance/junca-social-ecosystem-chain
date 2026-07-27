#!/usr/bin/env python3
"""Collect and aggregate a segmented, read-only 24-hour live soak.

The deterministic soak simulation remains a fast consensus regression test.
This command is the separate runtime acceptance path: it repeatedly reads the
public health, Explorer and RPC endpoints, writes one four-hour segment per
GitHub-hosted job, and fail-closes unless six segments form a continuous
candidate-bound 24-hour observation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import junca_public_testnet_runtime_acceptance_packet as packet


SCHEMA = "junca-public-testnet-live-soak/v1"
SEGMENT_SCHEMA = "junca-public-testnet-live-soak-segment/v1"
SEGMENT_COUNT = 6
SEGMENT_DURATION_SECONDS = 4 * 60 * 60
OBSERVATION_INTERVAL_SECONDS = 5 * 60
OBSERVATIONS_PER_SEGMENT = (
    SEGMENT_DURATION_SECONDS // OBSERVATION_INTERVAL_SECONDS
) + 1
MAX_OBSERVATION_GAP_SECONDS = OBSERVATION_INTERVAL_SECONDS + 120
MIN_OBSERVATION_GAP_SECONDS = OBSERVATION_INTERVAL_SECONDS - 60
MAX_SEGMENT_GAP_SECONDS = 15 * 60
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
BOUNDARY = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}


class LiveSoakError(RuntimeError):
    """Raised when live evidence is missing, discontinuous, or mismatched."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveSoakError(message)


def _parse_time(value: object) -> datetime:
    _require(isinstance(value, str), "observation timestamp is missing")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveSoakError("observation timestamp is invalid") from exc
    _require(
        observed.tzinfo is not None and observed.utcoffset() is not None,
        "observation timestamp must include a timezone",
    )
    return observed.astimezone(timezone.utc)


def _binding(
    source_commit: str,
    node_artifact_sha256: str,
    genesis_sha256: str,
    ami_id: str,
    request_sha256: str,
) -> dict[str, str]:
    _require(COMMIT.fullmatch(source_commit) is not None, "source_commit:invalid")
    _require(
        SHA256.fullmatch(node_artifact_sha256) is not None,
        "node_artifact_sha256:invalid",
    )
    _require(
        SHA256.fullmatch(genesis_sha256) is not None,
        "genesis_sha256:invalid",
    )
    _require(AMI.fullmatch(ami_id) is not None, "ami_id:invalid")
    _require(SHA256.fullmatch(request_sha256) is not None, "request_sha256:invalid")
    return {
        "source_commit": source_commit,
        "node_artifact_sha256": node_artifact_sha256,
        "genesis_sha256": genesis_sha256,
        "ami_id": ami_id,
        "request_sha256": request_sha256,
    }


def _digest_object(source: Mapping[str, Any]) -> str:
    unsigned = dict(source)
    unsigned.pop("evidence_sha256", None)
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _boundary_ok(source: Mapping[str, Any]) -> bool:
    boundary = source.get("release_boundary")
    return isinstance(boundary, Mapping) and all(
        boundary.get(field) is value for field, value in BOUNDARY.items()
    )


def _observation_times(
    observations: Sequence[Mapping[str, Any]],
) -> list[datetime]:
    return [_parse_time(item.get("observed_at")) for item in observations]


def build_segment(
    acceptance_packet: Mapping[str, Any],
    *,
    segment_index: int,
    source_commit: str,
    node_artifact_sha256: str,
    genesis_sha256: str,
    ami_id: str,
    request_sha256: str,
    duration_seconds: int = SEGMENT_DURATION_SECONDS,
    interval_seconds: int = OBSERVATION_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Bind one live endpoint packet to an immutable runtime segment."""

    candidate = _binding(
        source_commit,
        node_artifact_sha256,
        genesis_sha256,
        ami_id,
        request_sha256,
    )
    failures: list[str] = []
    if not 1 <= segment_index <= SEGMENT_COUNT:
        failures.append("segment_index:out_of_range")
    if duration_seconds != SEGMENT_DURATION_SECONDS:
        failures.append("duration_seconds:not_four_hours")
    if interval_seconds != OBSERVATION_INTERVAL_SECONDS:
        failures.append("interval_seconds:not_five_minutes")
    if (
        acceptance_packet.get("schema_version")
        != "junca-public-testnet-live-acceptance-packet/v1"
    ):
        failures.append("packet.schema_version:mismatch")
    if acceptance_packet.get("status") != "PASS":
        failures.append("packet.status:not_pass")
    if not _boundary_ok(acceptance_packet):
        failures.append("packet.release_boundary:not_false")

    raw_observations = acceptance_packet.get("observations")
    observations = (
        raw_observations
        if isinstance(raw_observations, list)
        and all(isinstance(item, Mapping) for item in raw_observations)
        else []
    )
    expected_count = duration_seconds // interval_seconds + 1
    if len(observations) != expected_count:
        failures.append("observations:count_mismatch")

    times: list[datetime] = []
    try:
        times = _observation_times(observations)
    except LiveSoakError:
        failures.append("observations:timestamp_invalid")
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(times, times[1:])
    ]
    if gaps and any(
        gap < MIN_OBSERVATION_GAP_SECONDS
        or gap > MAX_OBSERVATION_GAP_SECONDS
        for gap in gaps
    ):
        failures.append("observations:gap_out_of_bounds")
    observed_duration = (
        (times[-1] - times[0]).total_seconds() if len(times) >= 2 else 0
    )
    if observed_duration < duration_seconds:
        failures.append("observations:duration_too_short")

    result: dict[str, Any] = {
        "schema_version": SEGMENT_SCHEMA,
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "status": "PASS" if not failures else "FAIL",
        "failures": sorted(set(failures)),
        "segment_index": segment_index,
        "segment_count": SEGMENT_COUNT,
        "candidate_binding": candidate,
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "observation_count": len(observations),
        "observed_from": (
            times[0].isoformat().replace("+00:00", "Z") if times else None
        ),
        "observed_to": (
            times[-1].isoformat().replace("+00:00", "Z") if times else None
        ),
        "max_observation_gap_seconds": max(gaps) if gaps else None,
        "acceptance_packet": dict(acceptance_packet),
        "release_boundary": dict(BOUNDARY),
    }
    result["evidence_sha256"] = _digest_object(result)
    return result


def aggregate_segments(
    segments: Sequence[Mapping[str, Any]],
    *,
    source_commit: str,
    node_artifact_sha256: str,
    genesis_sha256: str,
    ami_id: str,
    request_sha256: str,
    foundation_run_id: str = "1",
    public_release_run_id: str = "1",
    final_runtime_readback_sha256: str = "0" * 64,
) -> dict[str, Any]:
    """Fail-close unless six candidate-identical segments cover 24 hours."""

    candidate = _binding(
        source_commit,
        node_artifact_sha256,
        genesis_sha256,
        ami_id,
        request_sha256,
    )
    _require(foundation_run_id.isdigit(), "foundation_run_id:invalid")
    _require(public_release_run_id.isdigit(), "public_release_run_id:invalid")
    _require(
        SHA256.fullmatch(final_runtime_readback_sha256) is not None,
        "final_runtime_readback_sha256:invalid",
    )
    failures: list[str] = []
    ordered = sorted(segments, key=lambda item: item.get("segment_index", -1))
    if len(ordered) != SEGMENT_COUNT:
        failures.append("segments:not_exact_six")
    if [item.get("segment_index") for item in ordered] != list(
        range(1, SEGMENT_COUNT + 1)
    ):
        failures.append("segments:index_sequence_mismatch")

    all_observations: list[Mapping[str, Any]] = []
    for segment in ordered:
        if segment.get("schema_version") != SEGMENT_SCHEMA:
            failures.append("segment.schema_version:mismatch")
        if segment.get("status") != "PASS":
            failures.append("segment.status:not_pass")
        if segment.get("candidate_binding") != candidate:
            failures.append("segment.candidate_binding:mismatch")
        if not _boundary_ok(segment):
            failures.append("segment.release_boundary:not_false")
        if segment.get("evidence_sha256") != _digest_object(segment):
            failures.append("segment.evidence_sha256:mismatch")
        acceptance_packet = segment.get("acceptance_packet")
        observations = (
            acceptance_packet.get("observations")
            if isinstance(acceptance_packet, Mapping)
            else None
        )
        if not isinstance(observations, list) or not all(
            isinstance(item, Mapping) for item in observations
        ):
            failures.append("segment.observations:missing")
        else:
            all_observations.extend(observations)

    segment_times: list[tuple[datetime, datetime]] = []
    try:
        segment_times = [
            (_parse_time(item.get("observed_from")), _parse_time(item.get("observed_to")))
            for item in ordered
        ]
    except LiveSoakError:
        failures.append("segments:timestamp_invalid")
    segment_gaps = [
        (right[0] - left[1]).total_seconds()
        for left, right in zip(segment_times, segment_times[1:])
    ]
    if segment_gaps and any(
        gap < 0 or gap > MAX_SEGMENT_GAP_SECONDS for gap in segment_gaps
    ):
        failures.append("segments:continuity_gap")

    observed_duration = (
        (segment_times[-1][1] - segment_times[0][0]).total_seconds()
        if len(segment_times) == SEGMENT_COUNT
        else 0
    )
    if observed_duration < 24 * 60 * 60:
        failures.append("soak:duration_too_short")

    normalized = [
        item.get("normalized")
        for item in all_observations
        if isinstance(item.get("normalized"), Mapping)
    ]
    heights = [item.get("height") for item in normalized]
    timestamps = [item.get("timestamp_decimal") for item in normalized]
    if len(normalized) != len(all_observations):
        failures.append("observations:normalized_missing")
    if not all(
        isinstance(left, int)
        and isinstance(right, int)
        and right > left
        for left, right in zip(heights, heights[1:])
    ):
        failures.append("observations:finalized_head_not_advancing")
    if not all(
        isinstance(left, int)
        and isinstance(right, int)
        and right > left
        for left, right in zip(timestamps, timestamps[1:])
    ):
        failures.append("observations:block_timestamp_not_advancing")
    if any(
        item.get("signed_power") != 3
        or item.get("total_power") != 3
        or not isinstance(item.get("peer_count"), int)
        or item.get("peer_count") < 2
        for item in normalized
    ):
        failures.append("observations:quorum_or_peer_count_invalid")

    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "status": "PASS" if not failures else "FAIL",
        "accepted": not failures,
        "failures": sorted(set(failures)),
        "candidate_binding": candidate,
        "provenance": {
            "foundation_run_id": foundation_run_id,
            "public_release_run_id": public_release_run_id,
            "final_runtime_readback_sha256": final_runtime_readback_sha256,
        },
        "segments_expected": SEGMENT_COUNT,
        "segments_completed": len(ordered),
        "segment_duration_seconds": SEGMENT_DURATION_SECONDS,
        "observation_interval_seconds": OBSERVATION_INTERVAL_SECONDS,
        "observation_count": len(all_observations),
        "observed_from": (
            segment_times[0][0].isoformat().replace("+00:00", "Z")
            if segment_times
            else None
        ),
        "observed_to": (
            segment_times[-1][1].isoformat().replace("+00:00", "Z")
            if segment_times
            else None
        ),
        "duration_seconds": observed_duration,
        "max_segment_gap_seconds": max(segment_gaps) if segment_gaps else 0,
        "continuous_observation": not any(
            failure.startswith("segments:") for failure in failures
        ),
        "head_advanced": not any(
            failure.startswith("observations:finalized_head")
            or failure.startswith("observations:block_timestamp")
            for failure in failures
        ),
        "segment_evidence_sha256": [
            item.get("evidence_sha256") for item in ordered
        ],
        "release_boundary": dict(BOUNDARY),
    }
    result["evidence_sha256"] = _digest_object(result)
    return result


def _write(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveSoakError(f"unable to read evidence: {path}") from exc
    _require(isinstance(value, dict), f"evidence must be an object: {path}")
    return value


def _collect_segment(args: argparse.Namespace) -> int:
    count = SEGMENT_DURATION_SECONDS // OBSERVATION_INTERVAL_SECONDS + 1
    observations: list[dict[str, Any]] = []
    collection_error: str | None = None
    for index in range(1, count + 1):
        try:
            observations.append(packet.collect_observation(index))
        except packet.AcceptanceError as exc:
            collection_error = str(exc)
            break
        if index < count:
            time.sleep(OBSERVATION_INTERVAL_SECONDS)
    if collection_error is None:
        acceptance_packet = packet.build_packet(
            observations, OBSERVATION_INTERVAL_SECONDS
        )
    else:
        acceptance_packet = {
            "schema_version": "junca-public-testnet-live-acceptance-packet/v1",
            "scope": "Public Testnet Runtime Acceptance / Read-only",
            "status": "FAIL",
            "failures": ["observation:endpoint_unavailable"],
            "collection_error": collection_error,
            "observations": observations,
            "release_boundary": dict(BOUNDARY),
        }
    segment = build_segment(
        acceptance_packet,
        segment_index=args.segment_index,
        source_commit=args.source_commit,
        node_artifact_sha256=args.node_artifact_sha256,
        genesis_sha256=args.genesis_sha256,
        ami_id=args.ami_id,
        request_sha256=args.request_sha256,
    )
    _write(args.output, segment)
    print(json.dumps({"status": segment["status"], "output": args.output}))
    return 0 if segment["status"] == "PASS" else 1


def _aggregate(args: argparse.Namespace) -> int:
    paths = sorted(Path(args.segments_dir).glob("segment-*.json"))
    result = aggregate_segments(
        [_read(path) for path in paths],
        source_commit=args.source_commit,
        node_artifact_sha256=args.node_artifact_sha256,
        genesis_sha256=args.genesis_sha256,
        ami_id=args.ami_id,
        request_sha256=args.request_sha256,
        foundation_run_id=args.foundation_run_id,
        public_release_run_id=args.public_release_run_id,
        final_runtime_readback_sha256=args.final_runtime_readback_sha256,
    )
    _write(args.output, result)
    print(json.dumps({"status": result["status"], "output": args.output}))
    return 0 if result["status"] == "PASS" else 1


def _binding_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--node-artifact-sha256", required=True)
    parser.add_argument("--genesis-sha256", required=True)
    parser.add_argument("--ami-id", required=True)
    parser.add_argument("--request-sha256", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect-segment")
    collect.add_argument("--segment-index", type=int, required=True)
    collect.add_argument("--output", required=True)
    _binding_arguments(collect)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--segments-dir", required=True)
    aggregate.add_argument("--output", required=True)
    aggregate.add_argument("--foundation-run-id", required=True)
    aggregate.add_argument("--public-release-run-id", required=True)
    aggregate.add_argument("--final-runtime-readback-sha256", required=True)
    _binding_arguments(aggregate)
    args = parser.parse_args()
    if args.command == "collect-segment":
        return _collect_segment(args)
    return _aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
