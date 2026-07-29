#!/usr/bin/env python3
"""Apply exact Foundation shell changes for evidence-bound rolling lifecycle."""

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
        raise SystemExit("usage: apply_evidence_bound_rolling_lifecycle.py PATH")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''build_pre_rollout_finality_bindings() {
  local updated_count="$1"
  local target_artifact_sha256="$2"
  local previous_artifact_sha256="$3"
  shift 3
  local instances_json
  [[ "$updated_count" =~ ^[0-3]$ ]]
  [[ "$target_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$previous_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  test "$target_artifact_sha256" != "$previous_artifact_sha256"
  instances_json="$(
    printf '%s\\n' "$@" | jq -Rsc 'split("\\n")[:-1]'
  )"
  jq -e '
    type == "array" and length == 3 and
    (unique | length) == 3 and
    all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
  ' <<<"$instances_json" >/dev/null
  jq -cn \\
    --argjson updated_count "$updated_count" \\
    --arg target_artifact_sha256 "$target_artifact_sha256" \\
    --arg previous_artifact_sha256 "$previous_artifact_sha256" \\
    --argjson instances "$instances_json" '
      [
        range(0; ($instances | length)) as $index |
        {
          instance_id: $instances[$index],
          expected_artifact_sha256:
            (if $index < $updated_count then
               $target_artifact_sha256
             else
               $previous_artifact_sha256
             end),
          allow_missing_finality_keys: ($index >= $updated_count)
        }
      ]
    '
}
''',
        '''build_pre_rollout_finality_bindings() {
  local updated_count="$1"
  local target_artifact_sha256="$2"
  local baseline_bindings_json="$3"
  shift 3
  local instances_json
  [[ "$updated_count" =~ ^[0-3]$ ]]
  [[ "$target_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  instances_json="$(
    printf '%s\\n' "$@" | jq -Rsc 'split("\\n")[:-1]'
  )"
  jq -e '
    type == "array" and length == 3 and
    (unique | length) == 3 and
    all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
  ' <<<"$instances_json" >/dev/null
  jq -e \\
    --argjson instances "$instances_json" \\
    --arg target_artifact_sha256 "$target_artifact_sha256" '
      type == "array" and length == 3 and
      [.[].validator_id] ==
        ["validator-01", "validator-02", "validator-03"] and
      [.[].instance_id] == $instances and
      all(
        .[];
        (.runtime_version | type == "string" and
          test("^[0-9a-f]{64}$")) and
        (.ami_id | type == "string" and
          test("^ami-[0-9a-f]{8,17}$")) and
        (.target_runtime | type == "boolean")
      ) and
      all(
        range(0; 3) as $index;
        if $index < $updated_count then
          .[$index].runtime_version == $target_artifact_sha256
        else
          true
        end
      )
    ' <<<"$baseline_bindings_json" >/dev/null
  jq -cn \\
    --argjson updated_count "$updated_count" \\
    --arg target_artifact_sha256 "$target_artifact_sha256" \\
    --argjson baseline "$baseline_bindings_json" \\
    --argjson instances "$instances_json" '
      [
        range(0; ($instances | length)) as $index |
        {
          instance_id: $instances[$index],
          expected_artifact_sha256:
            (if $index < $updated_count then
               $target_artifact_sha256
             else
               $baseline[$index].runtime_version
             end),
          allow_missing_finality_keys: ($index >= $updated_count)
        }
      ]
    '
}
''',
        "pre-rollout finality binding function",
    )

    text = replace_once(
        text,
        '''  fi
  jq -n \\
    --arg target_version "$NODE_ARTIFACT_SHA256" \\
''',
        '''  fi
  cp "$evidence_validators_path" \\
    artifacts/evidence-bound-rollout-baseline.json
  cp "$rollback_path" artifacts/evidence-bound-rollout-rollback.json
  jq -n \\
    --arg target_version "$NODE_ARTIFACT_SHA256" \\
''',
        "rollout baseline preservation",
    )

    text = replace_once(
        text,
        '''  jq -n \\
    --arg target_version "$NODE_ARTIFACT_SHA256" \\
    --arg target_ami_id "$NODE_AMI_ID" \\
    --argjson requested_slot_epoch_seconds \\
      "$validator_slot_epoch_seconds" \\
    --argjson observed_unix_time "$(date +%s)" \\
    --slurpfile validators artifacts/rolling-validators.json \\
    --slurpfile rollback artifacts/rollback-rehearsal.json '{
      target_version: $target_version,
      target_ami_id: $target_ami_id,
      update_order: ["validator-01", "validator-02", "validator-03"],
      validators: $validators[0],
      requested_slot_epoch_seconds: $requested_slot_epoch_seconds,
      observed_unix_time: $observed_unix_time,
      fallback_active: false,
      rollback: $rollback[0],
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' > artifacts/rolling-compatibility-evidence.json
  python -m jaios.social_ecosystem_chain.rolling_compatibility \\
    --evidence artifacts/rolling-compatibility-evidence.json \\
    --output artifacts/rolling-compatibility-decision.json
''',
        '''  jq -n \\
    --arg target_version "$NODE_ARTIFACT_SHA256" \\
    --arg target_ami_id "$NODE_AMI_ID" \\
    --arg previous_version "$previous_artifact_sha256" \\
    --arg previous_ami_id "$previous_ami_id" \\
    --argjson evidence_updated_count \\
      "$evidence_bound_baseline_updated_count" \\
    --argjson requested_slot_epoch_seconds \\
      "$validator_slot_epoch_seconds" \\
    --argjson observed_unix_time "$(date +%s)" \\
    --slurpfile validators artifacts/rolling-validators.json \\
    --slurpfile evidence_validators \\
      artifacts/evidence-bound-rollout-baseline.json \\
    --slurpfile rollback artifacts/rollback-rehearsal.json '{
      target_version: $target_version,
      target_ami_id: $target_ami_id,
      previous_version: $previous_version,
      previous_ami_id: $previous_ami_id,
      update_order: ["validator-01", "validator-02", "validator-03"],
      evidence_updated_count: $evidence_updated_count,
      validators: $validators[0],
      evidence_validators: $evidence_validators[0],
      requested_slot_epoch_seconds: $requested_slot_epoch_seconds,
      observed_unix_time: $observed_unix_time,
      fallback_active: false,
      rollback: $rollback[0],
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' > artifacts/rolling-compatibility-evidence.json
  python scripts/junca_live_rollout_prefix_gate.py \\
    --mode rolling \\
    --evidence artifacts/rolling-compatibility-evidence.json \\
    --output artifacts/rolling-compatibility-decision.json
''',
        "rolling compatibility invocation",
    )

    text = replace_once(
        text,
        '''  live_updated_count="$(
    jq -er '.live_updated_count' artifacts/live-prefix-decision.json
  )"

  # Stop automatic finality before the next replacement. The observed target
''',
        '''  live_updated_count="$(
    jq -er '.live_updated_count' artifacts/live-prefix-decision.json
  )"
  evidence_bound_baseline_updated_count="$(
    jq -er '.evidence_updated_count' artifacts/live-prefix-decision.json
  )"
  evidence_bound_baseline_bindings="$(
    jq -ce '
      .baseline_bindings
      | select(
          length == 3 and
          [.[].validator_id] ==
            ["validator-01", "validator-02", "validator-03"] and
          all(.[]; .runtime_version | test("^[0-9a-f]{64}$")) and
          all(.[]; .instance_id | test("^i-[0-9a-f]{8,17}$"))
        )
    ' artifacts/live-prefix-decision.json
  )"

  # Stop automatic finality before the next replacement. The observed target
''',
        "initial decision binding",
    )

    text = replace_once(
        text,
        '''    build_pre_rollout_finality_bindings \\
      "$live_updated_count" \\
      "$NODE_ARTIFACT_SHA256" "$previous_artifact_sha256" \\
      "${pre_rollout_instances[@]}"
''',
        '''    build_pre_rollout_finality_bindings \\
      "$live_updated_count" \\
      "$NODE_ARTIFACT_SHA256" "$evidence_bound_baseline_bindings" \\
      "${pre_rollout_instances[@]}"
''',
        "pre-rollout finality binding call",
    )

    required = (
        "artifacts/evidence-bound-rollout-baseline.json",
        '"$evidence_bound_baseline_bindings"',
        "--mode rolling",
        ".baseline_bindings",
    )
    for value in required:
        if value not in text:
            raise SystemExit(f"missing required patched value: {value}")
    if text.count("python -m jaios.social_ecosystem_chain.rolling_compatibility") != 0:
        raise SystemExit("legacy single-previous rolling gate remains in Foundation")
    if text.count("python scripts/junca_live_rollout_prefix_gate.py") != 2:
        raise SystemExit("evidence-bound gate must be invoked exactly twice")

    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
