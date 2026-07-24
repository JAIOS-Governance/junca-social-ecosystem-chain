"""Emit deterministic release-readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain import ChainReadinessError, load_readiness


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config/junca_social_ecosystem_chain_readiness.json"),
    )
    parser.add_argument("--output")
    parser.add_argument("--expect-state", choices=("blocked", "ready"))
    args = parser.parse_args()
    try:
        readiness = load_readiness(args.config)
        evidence = readiness.as_evidence()
    except ChainReadinessError as exc:
        evidence = {"state": "invalid", "error": str(exc)}
        if args.output:
            _write_atomic(Path(args.output), evidence)
        print(json.dumps(evidence, sort_keys=True))
        return 3
    if args.output:
        _write_atomic(Path(args.output), evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if args.expect_state and readiness.state != args.expect_state:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
