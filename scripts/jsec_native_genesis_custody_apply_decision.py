#!/usr/bin/env python3
"""Apply a verified CEO custody decision to a non-activated JSEC plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.native_token_genesis import (
    NativeTokenGenesisError,
    apply_native_genesis_custody_decision,
    evaluate_native_token_genesis_plan,
    load_native_genesis_custody_decision,
)


DEFAULT_PLAN = Path("config/jsec_native_token_genesis_plan_v1.json")


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeTokenGenesisError("unable to load native Genesis plan") from exc


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()

    resolved = {
        "plan": args.plan.resolve(),
        "decision": args.decision.resolve(),
        "output": args.output.resolve(),
        "evidence-output": args.evidence_output.resolve(),
    }
    if len(set(resolved.values())) != len(resolved):
        print(
            "JSEC custody decision input and output paths must be distinct",
            file=sys.stderr,
        )
        return 2

    try:
        raw_plan = _load_json(args.plan)
        input_plan = evaluate_native_token_genesis_plan(raw_plan)
        decision = load_native_genesis_custody_decision(args.decision)
        updated = apply_native_genesis_custody_decision(raw_plan, decision)
        output_plan = evaluate_native_token_genesis_plan(updated)
    except NativeTokenGenesisError as exc:
        print(
            f"JSEC Genesis custody decision apply failed: {exc}",
            file=sys.stderr,
        )
        return 1

    evidence = decision.as_evidence()
    evidence.update(
        {
            "state": "APPLIED_TO_NON_ACTIVATED_GENESIS_PLAN",
            "input_plan_sha256": input_plan.specification_digest,
            "output_plan_sha256": output_plan.specification_digest,
            "remaining_blockers": list(output_plan.blockers),
        }
    )
    _write_json(args.output, updated)
    _write_json(args.evidence_output, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True) + "\n", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
