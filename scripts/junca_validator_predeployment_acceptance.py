#!/usr/bin/env python3
"""Create one fail-closed validator predeployment machine manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.predeployment_acceptance import evaluate_predeployment


def _read(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--foundation", required=True)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = evaluate_predeployment(
            _read(args.artifact), _read(args.foundation), _read(args.bootstrap)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"predeployment evidence rejected: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{result['manifest_sha256']}  {output.name}\n", encoding="utf-8"
    )
    print(json.dumps({"decision": result["decision"], "failure_count": result["failure_count"]}))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
