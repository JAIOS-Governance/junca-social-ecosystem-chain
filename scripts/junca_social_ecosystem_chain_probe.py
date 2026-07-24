#!/usr/bin/env python3
"""Create redacted JUNCA Social Ecosystem Chain operational health evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import ChainHealthProbe, ChainHealthStatus, load_network_specs


DEFAULT_CONFIG = Path("config/junca_social_ecosystem_chain_networks.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe JUNCA Social Ecosystem Chain RPC identity, head freshness and peers."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--network",
        action="append",
        dest="networks",
        help="Network name to probe; repeat for multiple networks.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output", type=Path)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = load_network_specs(args.config)
    selected = set(args.networks or (spec.name for spec in specs))
    unknown = selected.difference(spec.name for spec in specs)
    if unknown:
        raise SystemExit(f"unknown network(s): {', '.join(sorted(unknown))}")
    probe = ChainHealthProbe(timeout_seconds=args.timeout)
    reports = [probe.probe(spec) for spec in specs if spec.name in selected]
    evidence = {
        "schema_version": "junca-chain-operations/v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall_status": max(
            (report.status for report in reports),
            key=lambda status: status.rank,
        ).value,
        "networks": [report.as_evidence() for report in reports],
    }
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        _atomic_write(args.output, rendered)
    sys.stdout.write(rendered)
    return {
        ChainHealthStatus.HEALTHY.value: 0,
        ChainHealthStatus.DEGRADED.value: 2,
        ChainHealthStatus.UNHEALTHY.value: 3,
    }[evidence["overall_status"]]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(run())
