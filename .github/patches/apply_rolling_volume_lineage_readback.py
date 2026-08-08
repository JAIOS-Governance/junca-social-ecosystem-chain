#!/usr/bin/env python3
"""Add exact retained-volume readback to rolling validator observations."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, observed {count}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_rolling_volume_lineage_readback.py FOUNDATION")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''  local -a current_instances
  local index
  terraform -chdir=infra/aws/public-testnet output -json \\
''',
        '''  local -a current_instances
  local index
  local validator_id
  local state_volume_id
  local rollback_volume_id
  local observation_path
  local enriched_observation_path
  terraform -chdir=infra/aws/public-testnet output -json \\
''',
        "rolling observation locals",
    )

    text = replace_once(
        text,
        '''  for index in 0 1 2; do
    capture_validator_observation \\
      "validator-0$((index + 1))" \\
      "${current_instances[$index]}" \\
      "artifacts/rolling-validator-$((index + 1)).json"
  done
  jq -s '.' artifacts/rolling-validator-{1,2,3}.json \\
''',
        '''  for index in 0 1 2; do
    validator_id="validator-0$((index + 1))"
    observation_path="artifacts/rolling-validator-$((index + 1)).json"
    capture_validator_observation \\
      "$validator_id" \\
      "${current_instances[$index]}" \\
      "$observation_path"
    state_volume_id="$(
      jq -er --arg validator_id "$validator_id" '
        .validator_state_volume_readback.value[]
        | select(.validator_id == $validator_id)
        | .volume_id
        | select(type == "string" and test("^vol-[0-9a-f]{8,17}$"))
      ' artifacts/rolling-foundation-outputs.json
    )"
    rollback_volume_id="$(
      jq -er --arg validator_id "$validator_id" '
        .validators[]
        | select(.validator_id == $validator_id)
        | .volume_id
        | select(type == "string" and test("^vol-[0-9a-f]{8,17}$"))
      ' artifacts/rollback-rehearsal.json
    )"
    test "$state_volume_id" = "$rollback_volume_id"
    enriched_observation_path="${observation_path%.json}.enriched.json"
    jq --arg volume_id "$state_volume_id" \\
      '. + {volume_id: $volume_id}' \\
      "$observation_path" >"$enriched_observation_path"
    mv "$enriched_observation_path" "$observation_path"
  done
  jq -s '.' artifacts/rolling-validator-{1,2,3}.json \\
''',
        "rolling retained-volume enrichment",
    )

    for required in (
        ".validator_state_volume_readback.value[]",
        "artifacts/rollback-rehearsal.json",
        'test "$state_volume_id" = "$rollback_volume_id"',
        "'. + {volume_id: $volume_id}'",
    ):
        if required not in text:
            raise SystemExit(f"missing required retained-volume contract: {required}")

    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
