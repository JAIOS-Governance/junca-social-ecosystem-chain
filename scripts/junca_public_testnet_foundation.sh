#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
case "$phase" in
  foundation-plan|foundation-apply) ;;
  *) echo "phase must be foundation-plan or foundation-apply" >&2; exit 2 ;;
esac

required_env=(
  AWS_ACCOUNT_ID AWS_REGION STATE_BUCKET_NAME DOMAIN_NAME ROUTE53_ZONE_ID
  NODE_AMI_ID NODE_ARTIFACT_SHA256 GENESIS_SHA256 SOURCE_COMMIT
  AVAILABILITY_ZONES_JSON
  DEPLOYMENT_ROLE_ARN
)
for name in "${required_env[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "missing required environment: $name" >&2; exit 2; }
done

[[ "$AWS_ACCOUNT_ID" == "595710543956" ]]
[[ "$AWS_REGION" == "us-east-1" ]]
[[ "$DEPLOYMENT_ROLE_ARN" == "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment" ]]
[[ "$NODE_AMI_ID" =~ ^ami-[0-9a-f]{8,17}$ ]]
[[ "$NODE_ARTIFACT_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$GENESIS_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
jq -e 'type == "array" and length == 3 and (unique | length) == 3 and all(startswith("us-east-1"))' \
  <<<"$AVAILABILITY_ZONES_JSON" >/dev/null

mkdir -p artifacts
source scripts/junca_fixed_ssm_caller.sh

wait_for_ssm_online() {
  local instance_id="$1"
  local output_path="$2"
  local attempts_path="${output_path%.json}.attempts.jsonl"
  local stderr_path="${output_path%.json}.stderr"
  local ping_status=""
  local cli_exit=0
  local attempt
  : >"$attempts_path"
  : >"$stderr_path"
  for attempt in $(seq 1 60); do
    cli_exit=0
    if ping_status="$(
      aws ssm describe-instance-information \
        --filters "Key=InstanceIds,Values=${instance_id}" \
        --query 'InstanceInformationList[0].PingStatus' \
        --output text 2>"$stderr_path"
    )"; then
      :
    else
      cli_exit=$?
      ping_status=AwsCliError
    fi
    jq -cn \
      --argjson attempt "$attempt" \
      --argjson cli_exit "$cli_exit" \
      --arg ping_status "$ping_status" \
      --rawfile stderr "$stderr_path" '{
        attempt: $attempt,
        cli_exit: $cli_exit,
        ping_status: $ping_status,
        stderr: $stderr
      }' >>"$attempts_path"
    if [[ "$cli_exit" == 0 && "$ping_status" == "Online" ]]; then
      jq -s \
        --arg instance_id "$instance_id" \
        --arg observed_status "$ping_status" '{
          schema_version: "junca-validator-ssm-online-readback/v1",
          instance_id: $instance_id,
          observed_status: $observed_status,
          attempts: .,
          accepted: true
        }' "$attempts_path" >"$output_path"
      return 0
    fi
    if [[ "$attempt" -lt 60 ]]; then
      sleep 10
    fi
  done
  jq -s \
    --arg instance_id "$instance_id" \
    --arg observed_status "$ping_status" '{
      schema_version: "junca-validator-ssm-online-readback/v1",
      instance_id: $instance_id,
      observed_status: $observed_status,
      attempts: .,
      accepted: false
    }' "$attempts_path" >"$output_path"
  return 1
}

write_post_apply_checkpoint() {
  local index="$1"
  local stage="$2"
  local status="$3"
  local instance_id="${4:-}"
  local volume_id="${5:-}"
  local stage_path="artifacts/post-apply-validator-${index}-${stage}.json"
  [[ "$index" =~ ^[0-2]$ ]]
  [[ "$stage" =~ ^[a-z0-9-]+$ ]]
  [[ "$status" =~ ^(started|succeeded|failed)$ ]]
  jq -n \
    --argjson validator_index "$index" \
    --arg validator_id "validator-0$((index + 1))" \
    --arg stage "$stage" \
    --arg status "$status" \
    --arg instance_id "$instance_id" \
    --arg volume_id "$volume_id" '{
      schema_version: "junca-validator-post-apply-checkpoint/v1",
      validator_index: $validator_index,
      validator_id: $validator_id,
      stage: $stage,
      status: $status,
      instance_id: (if $instance_id == "" then null else $instance_id end),
      volume_id: (if $volume_id == "" then null else $volume_id end),
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' >"$stage_path"
  cp "$stage_path" "artifacts/post-apply-validator-${index}-checkpoint.json"
}

verify_rollback_snapshots() {
  local validator_state_json="$1"
  local output_path="$2"
  local -a snapshot_ids
  local snapshot_ids_json
  local expected_ids
  snapshot_ids_json="$(
    jq -ce '[
      .[].rollback_snapshot_id
      | select(
        type == "string" and
        test("^snap-[0-9a-f]{8,17}$")
      )
    ]' <<<"$validator_state_json"
  )"
  test "$(jq -r 'length' <<<"$snapshot_ids_json")" = 3
  for index in 0 1 2; do
    snapshot_ids+=("$(jq -er ".[$index]" <<<"$snapshot_ids_json")")
  done
  expected_ids="$(jq -c 'sort | unique' <<<"$snapshot_ids_json")"
  test "$(jq -r 'length' <<<"$expected_ids")" = 3
  aws ec2 describe-snapshots \
    --snapshot-ids "${snapshot_ids[@]}" \
    --owner-ids "$AWS_ACCOUNT_ID" \
    --output json >"$output_path"
  jq -e \
    --arg owner_id "$AWS_ACCOUNT_ID" \
    --argjson expected_ids "$expected_ids" '
      (.Snapshots | length) == 3 and
      ([.Snapshots[].SnapshotId] | sort) == $expected_ids and
      all(
        .Snapshots[];
        .State == "completed" and
        .Encrypted == true and
        .OwnerId == $owner_id
      )
    ' "$output_path" >/dev/null
}

wait_for_ssm_command() {
  local command_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local document_name="$4"
  local document_version="$5"
  local status=""
  local error_path="${output_path%.json}-status-error.txt"
  local final_readback_succeeded=false
  for attempt in $(seq 1 90); do
    if ! status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query Status \
        --output text 2>"$error_path"
    )"; then
      if grep -Eq \
          'InvocationDoesNotExist|Throttl(ing|ed)|TooManyRequests|RequestLimitExceeded' \
          "$error_path" &&
          [[ "$attempt" != 90 ]]
      then
        sleep 2
        continue
      fi
      return 1
    fi
    case "$status" in
      Success) break ;;
      Failed|Cancelled|TimedOut|Cancelling)
        break
        ;;
    esac
    if [[ "$attempt" == 90 ]]; then
      return 1
    fi
    sleep 2
  done
  for attempt in $(seq 1 10); do
    if aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        >"$output_path" 2>"$error_path"
    then
      final_readback_succeeded=true
      break
    fi
    if ! grep -Eq \
        'InvocationDoesNotExist|Throttl(ing|ed)|TooManyRequests|RequestLimitExceeded' \
        "$error_path" ||
        [[ "$attempt" == 10 ]]
    then
      return 1
    fi
    sleep 2
  done
  if [[ "$final_readback_succeeded" != true ]]; then
    return 1
  fi
  if ! junca_fixed_ssm_validate_invocation_readback \
      "$output_path" "$instance_id" "$document_name" "$document_version" \
      "$command_id"
  then
    return 1
  fi
  rm -f "$error_path"
  return 0
}

wait_for_ssm_command_result() {
  local command_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local document_name="$4"
  local document_version="$5"
  local status=""
  local error_path="${output_path%.json}-status-error.txt"
  local final_readback_succeeded=false
  for attempt in $(seq 1 90); do
    if ! status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query Status \
        --output text 2>"$error_path"
    )"; then
      if grep -Eq \
          'InvocationDoesNotExist|Throttl(ing|ed)|TooManyRequests|RequestLimitExceeded' \
          "$error_path" &&
          [[ "$attempt" != 90 ]]
      then
        sleep 2
        continue
      fi
      return 1
    fi
    case "$status" in
      Success|Failed|Cancelled|TimedOut|Cancelling) break ;;
    esac
    if [[ "$attempt" == 90 ]]; then
      status=TimedOut
      break
    fi
    sleep 2
  done
  for attempt in $(seq 1 10); do
    if aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        >"$output_path" 2>"$error_path"
    then
      final_readback_succeeded=true
      break
    fi
    if ! grep -Eq \
        'InvocationDoesNotExist|Throttl(ing|ed)|TooManyRequests|RequestLimitExceeded' \
        "$error_path" ||
        [[ "$attempt" == 10 ]]
    then
      return 1
    fi
    sleep 2
  done
  if [[ "$final_readback_succeeded" != true ]]; then
    return 1
  fi
  if ! jq -e \
      --arg instance_id "$instance_id" \
      --arg document_name "$document_name" \
      --arg document_version "$document_version" \
      --arg command_id "$command_id" '
        .CommandId == $command_id and
        .InstanceId == $instance_id and
        .DocumentName == $document_name and
        .DocumentVersion == $document_version and
        (.Status | type) == "string" and
        (.StandardOutputContent | type) == "string" and
        (.StandardErrorContent | type) == "string"
      ' "$output_path" >/dev/null
  then
    return 1
  fi
  rm -f "$error_path"
  return 0
}

build_runtime_finality_bindings() {
  local expected_artifact_sha256="$1"
  local allow_missing_finality_keys="$2"
  local validator_ids_json="$3"
  shift 3
  local instances_json
  [[ "$expected_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  case "$allow_missing_finality_keys" in
    true|false) ;;
    *) return 2 ;;
  esac
  instances_json="$(
    printf '%s\n' "$@" | jq -Rsc 'split("\n")[:-1]'
  )"
  jq -e '
    type == "array" and length >= 1 and length <= 3 and
    (unique | length) == length and
    all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
  ' <<<"$instances_json" >/dev/null
  jq -e \
    --argjson instances "$instances_json" '
      type == "array" and
      length == ($instances | length) and
      (unique | length) == length and
      all(.[]; type == "string" and test("^validator-0[1-3]$"))
    ' <<<"$validator_ids_json" >/dev/null
  jq -cn \
    --arg expected_artifact_sha256 "$expected_artifact_sha256" \
    --argjson allow_missing_finality_keys "$allow_missing_finality_keys" \
    --argjson validator_ids "$validator_ids_json" \
    --argjson instances "$instances_json" '
      [
        range(0; ($instances | length)) as $index |
        {
          validator_id: $validator_ids[$index],
          instance_id: $instances[$index],
          expected_artifact_sha256: $expected_artifact_sha256,
          allow_missing_finality_keys: $allow_missing_finality_keys
        }
      ]
    '
}

build_pre_rollout_finality_bindings() {
  local updated_count="$1"
  local target_artifact_sha256="$2"
  local baseline_bindings_json="$3"
  shift 3
  local instances_json
  [[ "$updated_count" =~ ^[0-3]$ ]]
  [[ "$target_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  instances_json="$(
    printf '%s\n' "$@" | jq -Rsc 'split("\n")[:-1]'
  )"
  jq -e '
    type == "array" and length == 3 and
    (unique | length) == 3 and
    all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
  ' <<<"$instances_json" >/dev/null
  jq -e \
    --argjson updated_count "$updated_count" \
    --argjson instances "$instances_json" \
    --arg target_artifact_sha256 "$target_artifact_sha256" '
      . as $baseline |
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
        range(0; 3);
        . as $index |
        if $index < $updated_count then
          $baseline[$index].runtime_version == $target_artifact_sha256
        else
          true
        end
      )
    ' <<<"$baseline_bindings_json" >/dev/null
  jq -cn \
    --argjson updated_count "$updated_count" \
    --arg target_artifact_sha256 "$target_artifact_sha256" \
    --argjson baseline "$baseline_bindings_json" \
    --argjson instances "$instances_json" '
      [
        range(0; ($instances | length)) as $index |
        {
          validator_id: $baseline[$index].validator_id,
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

set_runtime_finality() {
  local block_interval="$1"
  local slot_epoch="$2"
  local bindings_json="$3"
  local finality_enabled
  local command_id
  local instance_id
  local instance_lines
  local validator_id
  local expected_artifact_sha256
  local allow_missing_finality_keys
  local finality_inspect_version
  local finality_set_version
  local compensation_summary
  local compensation_status
  local readback_status
  local index
  local mutation_failed=false
  local -a instances=()
  local -a mutation_command_ids=()
  [[ "$block_interval" =~ ^(0|30)$ ]] || return 1
  [[ "$slot_epoch" =~ ^(0|[1-9][0-9]*)$ ]] || return 1
  if ! jq -e '
    type == "array" and length >= 1 and length <= 3 and
    (map(.instance_id) | unique | length) == length and
    all(
      .[];
      (.instance_id | type == "string" and test("^i-[0-9a-f]{8,17}$")) and
      (.validator_id |
        type == "string" and test("^validator-0[1-3]$")) and
      (.expected_artifact_sha256 |
        type == "string" and test("^[0-9a-f]{64}$")) and
      (.allow_missing_finality_keys | type == "boolean")
    )
  ' <<<"$bindings_json" >/dev/null; then
    return 1
  fi
  if ! instance_lines="$(
    jq -er '.[].instance_id' <<<"$bindings_json"
  )"; then
    return 1
  fi
  mapfile -t instances <<<"$instance_lines"
  [[ "${#instances[@]}" -ge 1 && "${#instances[@]}" -le 3 ]] || return 1
  if [[ "$slot_epoch" != "0" ]]; then
    test "$slot_epoch" -gt "$(date +%s)" || return 1
    test "$((slot_epoch % 30))" -eq 0 || return 1
  fi
  if [[ "$block_interval" == "30" ]]; then
    test "$slot_epoch" != "0" || return 1
    test "$slot_epoch" -le "$(($(date +%s) + 60))" || return 1
    finality_enabled=true
  else
    test "$slot_epoch" = "0" || return 1
    finality_enabled=false
  fi
  finality_inspect_version="$(
    junca_fixed_ssm_document_version JuncaPTFinalityInspect
  )" || return
  finality_set_version="$(
    junca_fixed_ssm_document_version JuncaPTFinalitySet
  )" || return
  junca_fixed_ssm_validate_document \
    JuncaPTFinalityInspect artifacts/fixed-ssm
  junca_fixed_ssm_validate_document \
    JuncaPTFinalitySet artifacts/fixed-ssm

  # Complete every read-only preflight before any runtime.env mutation.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    if ! validator_id="$(
      jq -er ".[$index].validator_id" <<<"$bindings_json"
    )"; then
      return 1
    fi
    if ! expected_artifact_sha256="$(
      jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
    )"; then
      return 1
    fi
    if ! allow_missing_finality_keys="$(
      jq -r ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
    )"; then
      return 1
    fi
    if ! jq -n \
      --arg expected_artifact_sha256 "$expected_artifact_sha256" \
      --arg enabled "$finality_enabled" \
      --arg block_interval_seconds "$block_interval" \
      --arg slot_epoch_seconds "$slot_epoch" \
      --arg allow_missing_finality_keys "$allow_missing_finality_keys" '{
        ExpectedArtifactSha256: $expected_artifact_sha256,
        Enabled: $enabled,
        BlockIntervalSeconds: $block_interval_seconds,
        SlotEpochSeconds: $slot_epoch_seconds,
        Mode: "preflight",
        AllowMissingFinalityKeys: $allow_missing_finality_keys
      }' \
      >"artifacts/ssm-finality-preflight-${index}.json"
    then
      return 1
    fi
    if ! command_id="$(
      junca_fixed_ssm_send_command \
        JuncaPTFinalityInspect "$validator_id" "$instance_id" \
        "artifacts/ssm-finality-preflight-${index}.json" \
        "JUNCA Public Testnet fixed finality read-only preflight" \
        artifacts/fixed-ssm \
        "finality-preflight-${block_interval}-${slot_epoch}-${index}"
    )"; then
      return 1
    fi
    if ! wait_for_ssm_command \
      "$command_id" "$instance_id" \
      "artifacts/finality-preflight-${block_interval}-${slot_epoch}-${instance_id}.json" \
      JuncaPTFinalityInspect "$finality_inspect_version"
    then
      return 1
    fi
    if ! jq -er .StandardOutputContent \
        "artifacts/finality-preflight-${block_interval}-${slot_epoch}-${instance_id}.json" |
      jq -e \
        --arg validator_id "$validator_id" \
        --arg expected_artifact_sha256 "$expected_artifact_sha256" \
        --argjson enabled "$finality_enabled" \
        --argjson block_interval_seconds "$block_interval" \
        --argjson slot_epoch_seconds "$slot_epoch" '
          .schema_version == "junca-pt-finality-inspect/v1" and
          .document == "JuncaPTFinalityInspect" and
          .access_class == "read-only" and
          .mode == "preflight" and
          .validator_id == $validator_id and
          .artifact_sha256 == $expected_artifact_sha256 and
          .finality.enabled == $enabled and
          .finality.block_interval_seconds == $block_interval_seconds and
          .finality.slot_epoch_seconds == $slot_epoch_seconds and
          .mainnet_changed == false and
          .assets_moved == false and
          .bridge_activated == false
        ' >/dev/null
    then
      return 1
    fi
  done

  # Dispatch every mutation before collecting any result, preventing an early
  # failed invocation from hiding a partial multi-node write.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    validator_id="$(
      jq -er ".[$index].validator_id" <<<"$bindings_json"
    )"
    expected_artifact_sha256="$(
      jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
    )"
    jq -n \
      --arg expected_artifact_sha256 "$expected_artifact_sha256" \
      --arg enabled "$finality_enabled" \
      --arg block_interval_seconds "$block_interval" \
      --arg slot_epoch_seconds "$slot_epoch" '{
        ExpectedArtifactSha256: $expected_artifact_sha256,
        Enabled: $enabled,
        BlockIntervalSeconds: $block_interval_seconds,
        SlotEpochSeconds: $slot_epoch_seconds
      }' \
      >"artifacts/ssm-set-finality-${index}.json"
    if command_id="$(
      junca_fixed_ssm_send_command \
        JuncaPTFinalitySet "$validator_id" "$instance_id" \
        "artifacts/ssm-set-finality-${index}.json" \
        "JUNCA Public Testnet fixed fail-closed finality configuration" \
        artifacts/fixed-ssm \
        "finality-set-${block_interval}-${slot_epoch}-${index}"
    )"; then
      mutation_command_ids+=("$command_id")
    else
      mutation_command_ids+=("")
      mutation_failed=true
    fi
  done
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    if [[ -z "${mutation_command_ids[$index]}" ]] ||
      ! wait_for_ssm_command_result \
        "${mutation_command_ids[$index]}" "$instance_id" \
        "artifacts/finality-${block_interval}-${slot_epoch}-${instance_id}.json" \
        JuncaPTFinalitySet "$finality_set_version"
    then
      mutation_failed=true
      continue
    fi
    if ! jq -er .StandardOutputContent \
        "artifacts/finality-${block_interval}-${slot_epoch}-${instance_id}.json" |
      jq -e \
        --arg expected_artifact_sha256 "$(
          jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
        )" \
        --argjson enabled "$finality_enabled" \
        --argjson block_interval_seconds "$block_interval" \
        --argjson slot_epoch_seconds "$slot_epoch" '
          .schema_version == "junca-pt-finality-set/v1" and
          .document == "JuncaPTFinalitySet" and
          .access_class == "mutating" and
          .accepted == true and
          .transaction_state == "ACCEPTED" and
          .artifact_sha256 == $expected_artifact_sha256 and
          .finality.enabled == $enabled and
          .finality.block_interval_seconds == $block_interval_seconds and
          .finality.slot_epoch_seconds == $slot_epoch_seconds and
          .mainnet_changed == false and
          .assets_moved == false and
          .bridge_activated == false
        ' >/dev/null
    then
      mutation_failed=true
    fi
  done
  if [[ "$mutation_failed" == "true" ]]; then
    # Best-effort compensation always returns every reachable node to disabled
    # false/0/0 before the still-future canonical epoch.
    local -a compensation_command_ids=()
    for index in "${!instances[@]}"; do
      instance_id="${instances[$index]}"
      validator_id="$(
        jq -er ".[$index].validator_id" <<<"$bindings_json"
      )"
      expected_artifact_sha256="$(
        jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
      )"
      jq -n \
        --arg expected_artifact_sha256 "$expected_artifact_sha256" '{
          ExpectedArtifactSha256: $expected_artifact_sha256,
          Enabled: "false",
          BlockIntervalSeconds: "0",
          SlotEpochSeconds: "0"
        }' \
        >"artifacts/ssm-finality-compensate-${index}.json"
      if command_id="$(
        junca_fixed_ssm_send_command \
          JuncaPTFinalitySet "$validator_id" "$instance_id" \
          "artifacts/ssm-finality-compensate-${index}.json" \
          "JUNCA Public Testnet fixed finality failure compensation" \
          artifacts/fixed-ssm \
          "finality-compensate-${block_interval}-${slot_epoch}-${index}"
      )"; then
        compensation_command_ids+=("$command_id")
      else
        compensation_command_ids+=("")
      fi
    done
    for index in "${!instances[@]}"; do
      instance_id="${instances[$index]}"
      if [[ -n "${compensation_command_ids[$index]}" ]]; then
        wait_for_ssm_command_result \
          "${compensation_command_ids[$index]}" "$instance_id" \
          "artifacts/finality-compensation-${instance_id}.json" \
          JuncaPTFinalitySet "$finality_set_version" || true
      fi
      validator_id="$(
        jq -er ".[$index].validator_id" <<<"$bindings_json"
      )"
      expected_artifact_sha256="$(
        jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
      )"
      jq -n \
        --arg expected_artifact_sha256 "$expected_artifact_sha256" '{
          ExpectedArtifactSha256: $expected_artifact_sha256,
          Enabled: "false",
          BlockIntervalSeconds: "0",
          SlotEpochSeconds: "0",
          Mode: "exact",
          AllowMissingFinalityKeys: "false"
        }' \
        >"artifacts/ssm-finality-compensation-readback-${index}.json"
      if command_id="$(
        junca_fixed_ssm_send_command \
          JuncaPTFinalityInspect "$validator_id" "$instance_id" \
          "artifacts/ssm-finality-compensation-readback-${index}.json" \
          "JUNCA Public Testnet fixed finality compensation readback" \
          artifacts/fixed-ssm \
          "finality-compensation-readback-${index}"
      )"; then
        wait_for_ssm_command_result \
          "$command_id" "$instance_id" \
          "artifacts/finality-compensation-readback-${instance_id}.json" \
          JuncaPTFinalityInspect "$finality_inspect_version" || true
      fi
    done
    compensation_summary='[]'
    for instance_id in "${instances[@]}"; do
      compensation_status=SubmissionFailed
      readback_status=SubmissionFailed
      if [[ -f "artifacts/finality-compensation-${instance_id}.json" ]]; then
        compensation_status="$(
          jq -r '.Status // "Unknown"' \
            "artifacts/finality-compensation-${instance_id}.json"
        )"
      fi
      if [[ -f \
        "artifacts/finality-compensation-readback-${instance_id}.json" ]]; then
        readback_status="$(
          jq -r '.Status // "Unknown"' \
            "artifacts/finality-compensation-readback-${instance_id}.json"
        )"
      fi
      compensation_summary="$(
        jq -cn \
          --argjson current "$compensation_summary" \
          --arg instance_id "$instance_id" \
          --arg compensation_status "$compensation_status" \
          --arg readback_status "$readback_status" '
            $current + [{
              instance_id: $instance_id,
              compensation_status: $compensation_status,
              exact_disabled_readback_status: $readback_status
            }]
          '
      )"
    done
    jq -n \
      --argjson validators "$compensation_summary" \
      --argjson requested_block_interval "$block_interval" \
      --argjson requested_slot_epoch "$slot_epoch" '{
        schema_version: "junca-finality-compensation/v1",
        original_mutation_failed: true,
        requested_block_interval: $requested_block_interval,
        requested_slot_epoch: $requested_slot_epoch,
        compensation_target: {
          automatic_finality_enabled: false,
          block_interval_seconds: 0,
          slot_epoch_seconds: 0
        },
        validators: $validators,
        accepted: false
      }' > artifacts/finality-compensation-summary.json
    return 1
  fi
  return 0
}

verify_validator_bootstrap_readiness() {
  local validator_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local parameters_path="${output_path%.json}-parameters.json"
  local invocation_path="${output_path%.json}-invocation.json"
  local command_id
  local document_version
  [[ "$validator_id" =~ ^validator-0[1-3]$ ]] || return 1
  [[ "$instance_id" =~ ^i-[0-9a-f]{8,17}$ ]] || return 1
  document_version="$(
    junca_fixed_ssm_document_version JuncaPTBootstrapReadiness
  )" || return
  if ! jq -n \
      --arg validator_id "$validator_id" \
      --arg expected_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
      --arg expected_genesis_sha256 "$GENESIS_SHA256" '{
        ValidatorId: $validator_id,
        ExpectedArtifactSha256: $expected_artifact_sha256,
        ExpectedGenesisSha256: $expected_genesis_sha256
      }' >"$parameters_path"
  then
    return 1
  fi
  if ! command_id="$(
    junca_fixed_ssm_send_command \
      JuncaPTBootstrapReadiness "$validator_id" "$instance_id" \
      "$parameters_path" \
      "JUNCA fixed validator bootstrap readiness pre-mutation" \
      artifacts/fixed-ssm \
      "bootstrap-readiness-${validator_id}-${instance_id}"
  )"; then
    return 1
  fi
  if ! wait_for_ssm_command \
      "$command_id" "$instance_id" "$invocation_path" \
      JuncaPTBootstrapReadiness "$document_version"
  then
    return 1
  fi
  if ! jq -er .StandardOutputContent "$invocation_path" |
      jq -e \
        --arg validator_id "$validator_id" \
        --arg expected_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
        --arg expected_genesis_sha256 "$GENESIS_SHA256" '
        .schema_version == "junca-pt-bootstrap-readiness/v1" and
        .document == "JuncaPTBootstrapReadiness" and
        .access_class == "read-only" and
        .status == "READY" and
        .validator_id == $validator_id and
        .artifact_sha256 == $expected_artifact_sha256 and
        .genesis_sha256 == $expected_genesis_sha256 and
        .chain_id == 20260723 and
        (.head_height | type) == "number" and
        .head_height >= 1 and
        (.head_hash | type) == "string" and
        (.certificate_hash | type) == "string" and
        .mainnet_changed == false and
        .assets_moved == false and
        .bridge_activated == false
      ' >"$output_path"
  then
    return 1
  fi
  return 0
}

capture_validator_observation() {
  local validator_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local command_id
  local document_version
  local invocation
  local ami_id
  wait_for_ssm_online \
    "$instance_id" \
    "artifacts/ssm-online-${validator_id}-${instance_id}.json"
  ami_id="$(
    aws ec2 describe-instances \
      --instance-ids "$instance_id" \
      --query 'Reservations[0].Instances[0].ImageId' \
      --output text
  )"
  [[ "$ami_id" =~ ^ami-[0-9a-f]{8,17}$ ]]
  jq -n --arg validator_id "$validator_id" '{
    ValidatorId: $validator_id
  }' > artifacts/ssm-validator-readback.json
  document_version="$(
    junca_fixed_ssm_document_version JuncaPTRuntimeObservation
  )"
  command_id="$(
    junca_fixed_ssm_send_command \
      JuncaPTRuntimeObservation "$validator_id" "$instance_id" \
      artifacts/ssm-validator-readback.json \
      "JUNCA fixed Public Testnet rolling compatibility readback" \
      artifacts/fixed-ssm \
      "runtime-observation-${validator_id}-${instance_id}"
  )"
  invocation="artifacts/readback-${validator_id}-${instance_id}.json"
  wait_for_ssm_command \
    "$command_id" "$instance_id" "$invocation" \
    JuncaPTRuntimeObservation "$document_version"
  jq -er .StandardOutputContent "$invocation" |
    jq \
      --arg ami_id "$ami_id" \
      --arg instance_id "$instance_id" \
      '. + {ami_id: $ami_id, instance_id: $instance_id}' >"$output_path"
  jq -e \
    --arg validator_id "$validator_id" \
    --arg instance_id "$instance_id" '
      .schema_version == "junca-pt-runtime-observation/v1" and
      .document == "JuncaPTRuntimeObservation" and
      .access_class == "read-only" and
      .validator_id == $validator_id and
      .instance_id == $instance_id and
      .healthy == true and
      .ssm_online == true and
      .service_active == true and
      .durable_mount_verified == true and
      .state_store_integrity == true and
      .mainnet_changed == false and
      .assets_moved == false and
      .bridge_activated == false
    ' "$output_path" >/dev/null
}

write_live_rollout_prefix_readback() {
  local evidence_updated_count="$1"
  local evidence_validators_path="$2"
  local previous_artifact_sha256="$3"
  local previous_ami_id="$4"
  local rollback_path="$5"
  local -a current_instances
  local index
  local state_volume_id
  local validator_state_rollback
  local observation_path
  local enriched_observation_path
  [[ "$evidence_updated_count" =~ ^[0-3]$ ]]
  if [[ -n "$evidence_validators_path" ]]; then
    test -f "$evidence_validators_path"
  fi
  if [[ -n "$rollback_path" ]]; then
    test -f "$rollback_path"
  fi
  terraform -chdir=infra/aws/public-testnet output -json \
    > artifacts/live-prefix-foundation-outputs.json
  mapfile -t current_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/live-prefix-foundation-outputs.json
  )
  test "${#current_instances[@]}" = 3
  validator_state_rollback="$(
    jq -ce '
      .validator_state_volume_readback.value
      | select(
          length == 3 and
          (map(.validator_id) | sort) ==
            ["validator-01", "validator-02", "validator-03"] and
          (map(.volume_id) | unique | length) == 3 and
          (map(.rollback_snapshot_id) | unique | length) == 3
        )
    ' artifacts/live-prefix-foundation-outputs.json
  )"
  if [[ -n "$rollback_path" ]]; then
    jq -e \
      --argjson state "$validator_state_rollback" '
        [.validators[] |
          {validator_id, volume_id, rollback_snapshot_id}] ==
        [$state[] |
          {validator_id, volume_id, rollback_snapshot_id}]
      ' "$rollback_path" >/dev/null
  fi
  verify_rollback_snapshots \
    "$validator_state_rollback" \
    artifacts/live-prefix-rollback-snapshots.json
  for index in 0 1 2; do
    observation_path="artifacts/live-prefix-validator-$((index + 1)).json"
    capture_validator_observation \
      "validator-0$((index + 1))" \
      "${current_instances[$index]}" \
      "$observation_path"
    state_volume_id="$(
      jq -er \
        ".[$index].volume_id |
          select(type == \"string\" and
            test(\"^vol-[0-9a-f]{8,17}$\"))" \
        <<<"$validator_state_rollback"
    )"
    aws ec2 describe-volumes --volume-ids "$state_volume_id" \
      --output json \
      >"artifacts/live-prefix-volume-$((index + 1)).json"
    jq -e \
      --arg instance_id "${current_instances[$index]}" \
      --arg volume_id "$state_volume_id" '
        .Volumes | length == 1 and
        .[0].VolumeId == $volume_id and
        .[0].Encrypted == true and
        .[0].State == "in-use" and
        (.[0].Attachments | length) == 1 and
        .[0].Attachments[0].InstanceId == $instance_id and
        .[0].Attachments[0].State == "attached"
      ' "artifacts/live-prefix-volume-$((index + 1)).json" >/dev/null
    enriched_observation_path="${observation_path%.json}.enriched.json"
    jq --arg volume_id "$state_volume_id" \
      '. + {volume_id: $volume_id}' \
      "$observation_path" >"$enriched_observation_path"
    mv "$enriched_observation_path" "$observation_path"
  done
  jq -s '.' artifacts/live-prefix-validator-{1,2,3}.json \
    > artifacts/live-prefix-validators.json
  if [[ -z "$evidence_validators_path" ]]; then
    evidence_validators_path=artifacts/live-prefix-validators.json
  fi
  if [[ -z "$rollback_path" ]]; then
    rollback_path=artifacts/live-prefix-rollback-floor.json
    jq -n \
      --arg target_version "$previous_artifact_sha256" \
      --arg artifact_sha256 "$previous_artifact_sha256" \
      --arg ami_id "$previous_ami_id" \
      --slurpfile observed artifacts/live-prefix-validators.json \
      --argjson state "$validator_state_rollback" '{
        target_version: $target_version,
        artifact_sha256: $artifact_sha256,
        ami_id: $ami_id,
        rehearsal_passed: true,
        automatic_finality_disabled: true,
        no_state_rewind: true,
        durable_volume_reused: true,
        snapshot_restore_performed: false,
        validators: [
          range(0; 3) as $index
          | $observed[0][$index] as $health
          | $state[$index] as $volume
          | {
              validator_id: $health.validator_id,
              volume_id: $volume.volume_id,
              rollback_snapshot_id: $volume.rollback_snapshot_id,
              state_rewind_permitted: false,
              head_height: $health.head_height,
              head_hash: $health.head_hash,
              certificate_hash: $health.certificate_hash,
              certificate_height: $health.certificate_height,
              certificate_block_hash: $health.certificate_block_hash,
              certificate_finality_status:
                $health.certificate_finality_status,
              certificate_signed_power: $health.certificate_signed_power,
              certificate_total_power: $health.certificate_total_power,
              certificate_validator_ids: $health.certificate_validator_ids,
              certificate_vote_hashes: $health.certificate_vote_hashes
            }
        ],
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' >"$rollback_path"
  fi
  cp "$evidence_validators_path" \
    artifacts/evidence-bound-rollout-baseline.json
  cp "$rollback_path" artifacts/evidence-bound-rollout-rollback.json
  jq -n \
    --arg target_version "$NODE_ARTIFACT_SHA256" \
    --arg target_ami_id "$NODE_AMI_ID" \
    --arg previous_version "$previous_artifact_sha256" \
    --arg previous_ami_id "$previous_ami_id" \
    --argjson evidence_updated_count "$evidence_updated_count" \
    --argjson requested_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson observed_unix_time "$(date +%s)" \
    --slurpfile validators artifacts/live-prefix-validators.json \
    --slurpfile evidence_validators "$evidence_validators_path" \
    --slurpfile rollback "$rollback_path" '{
      target_version: $target_version,
      target_ami_id: $target_ami_id,
      previous_version: $previous_version,
      previous_ami_id: $previous_ami_id,
      update_order: ["validator-01", "validator-02", "validator-03"],
      evidence_updated_count: $evidence_updated_count,
      validators: $validators[0],
      evidence_validators: $evidence_validators[0],
      rollback: $rollback[0],
      requested_slot_epoch_seconds: $requested_slot_epoch_seconds,
      observed_unix_time: $observed_unix_time,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' > artifacts/live-prefix-readback.json
  python scripts/junca_live_rollout_prefix_gate.py \
    --evidence artifacts/live-prefix-readback.json \
    --output artifacts/live-prefix-decision.json
}

write_rolling_compatibility_evidence() {
  local expected_state="$1"
  local expected_next="${2:-}"
  local -a current_instances
  local index
  local validator_id
  local state_volume_id
  local rollback_volume_id
  local observation_path
  local enriched_observation_path
  terraform -chdir=infra/aws/public-testnet output -json \
    > artifacts/rolling-foundation-outputs.json
  mapfile -t current_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/rolling-foundation-outputs.json
  )
  test "${#current_instances[@]}" = 3
  for index in 0 1 2; do
    validator_id="validator-0$((index + 1))"
    observation_path="artifacts/rolling-validator-$((index + 1)).json"
    capture_validator_observation \
      "$validator_id" \
      "${current_instances[$index]}" \
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
    jq --arg volume_id "$state_volume_id" \
      '. + {volume_id: $volume_id}' \
      "$observation_path" >"$enriched_observation_path"
    mv "$enriched_observation_path" "$observation_path"
  done
  jq -s '.' artifacts/rolling-validator-{1,2,3}.json \
    > artifacts/rolling-validators.json
  jq -n \
    --arg target_version "$NODE_ARTIFACT_SHA256" \
    --arg target_ami_id "$NODE_AMI_ID" \
    --arg previous_version "$previous_artifact_sha256" \
    --arg previous_ami_id "$previous_ami_id" \
    --argjson evidence_updated_count \
      "$evidence_bound_baseline_updated_count" \
    --argjson requested_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson observed_unix_time "$(date +%s)" \
    --slurpfile validators artifacts/rolling-validators.json \
    --slurpfile evidence_validators \
      artifacts/evidence-bound-rollout-baseline.json \
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
  python scripts/junca_live_rollout_prefix_gate.py \
    --mode rolling \
    --evidence artifacts/rolling-compatibility-evidence.json \
    --output artifacts/rolling-compatibility-decision.json
  if [[ "$expected_state" == "AUTO" ]]; then
    jq -e '
      .mainnet_changed == false and
      .assets_moved == false and
      .bridge_activated == false
    ' artifacts/rolling-compatibility-decision.json >/dev/null
  else
    jq -e \
      --arg expected_state "$expected_state" \
      --arg expected_next "$expected_next" '
        .state == $expected_state and
        (
          if $expected_next == ""
          then .next_validator == null
          else .next_validator == $expected_next
          end
        ) and
        .mainnet_changed == false and
        .assets_moved == false and
        .bridge_activated == false
      ' artifacts/rolling-compatibility-decision.json >/dev/null
  fi
  cp \
    artifacts/rolling-compatibility-evidence.json \
    "artifacts/rolling-compatibility-${expected_state}.json"
  write_rolling_resume_evidence
}

write_rolling_resume_evidence() {
  local updated_count
  local parent_sha256=""
  updated_count="$(
    jq -er '.updated_count | select(type == "number" and . >= 0 and . <= 3)' \
      artifacts/rolling-compatibility-decision.json
  )"
  if [[ -n "${ROLLING_RESUME_EVIDENCE_PATH:-}" ]]; then
    parent_sha256="$(sha256sum "$ROLLING_RESUME_EVIDENCE_PATH" | cut -d' ' -f1)"
  fi
  jq -n \
    --arg repository "$GITHUB_REPOSITORY" \
    --arg head_sha "$GITHUB_SHA" \
    --arg candidate_provenance_head_sha "$ROLLING_CANDIDATE_HEAD_SHA" \
    --argjson producer_run_id "$GITHUB_RUN_ID" \
    --argjson ami_run_id "$AMI_RUN_ID" \
    --argjson manifest_gate_run_id "$MANIFEST_GATE_RUN_ID" \
    --argjson resume_run_id "$ROLLING_RESUME_RUN_ID" \
    --arg parent_evidence_sha256 "$parent_sha256" \
    --arg source_commit "$SOURCE_COMMIT" \
    --arg node_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
    --arg genesis_sha256 "$GENESIS_SHA256" \
    --arg ami_id "$NODE_AMI_ID" \
    --arg request_sha256 "$REQUEST_SHA256" \
    --arg manifest_decision_sha256 "$MANIFEST_DECISION_SHA256" \
    --argjson validator_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson validator_bootstrap_slot_epochs \
      "$validator_bootstrap_slot_epochs_json" \
    --argjson rolling_resume_prior_slot_epoch_seconds \
      "$rolling_resume_prior_slot_epoch_seconds" \
    --argjson rolling_epoch_renewal_performed \
      "$rolling_epoch_renewal_performed" \
    --argjson rolling_epoch_renewal_prefix_count \
      "$rolling_epoch_renewal_prefix_count" \
    --argjson updated_count "$updated_count" \
    --argjson terraform_replacement_addresses \
      "$terraform_replacement_addresses_json" \
    --slurpfile validators artifacts/rolling-validators.json \
    --slurpfile rollback artifacts/rollback-rehearsal.json \
    --slurpfile decision artifacts/rolling-compatibility-decision.json '{
      schema_version: "junca-validator-rolling-resume/v1",
      repository: $repository,
      head_sha: $head_sha,
      producer_run_id: $producer_run_id,
      ami_run_id: $ami_run_id,
      manifest_gate_run_id: $manifest_gate_run_id,
      resume_parent: (
        if $resume_run_id == 0
        then null
        else {
          run_id: $resume_run_id,
          evidence_sha256: $parent_evidence_sha256
        }
        end
      ),
      candidate: {
        provenance_head_sha: $candidate_provenance_head_sha,
        source_commit: $source_commit,
        node_artifact_sha256: $node_artifact_sha256,
        genesis_sha256: $genesis_sha256,
        ami_id: $ami_id,
        request_sha256: $request_sha256,
        manifest_decision_sha256: $manifest_decision_sha256
      },
      automatic_finality: {
        block_interval_seconds: 30,
        slot_epoch_seconds: $validator_slot_epoch_seconds,
        minimum_remaining_seconds: 900,
        maximum_remaining_seconds: 7230
      },
      terraform_bootstrap: {
        slot_epoch_seconds: $validator_bootstrap_slot_epochs
      },
      epoch_renewal: {
        performed: $rolling_epoch_renewal_performed,
        prior_slot_epoch_seconds:
          $rolling_resume_prior_slot_epoch_seconds,
        preserved_target_prefix_count:
          $rolling_epoch_renewal_prefix_count
      },
      updated_count: $updated_count,
      updated_validator_ids:
        (["validator-01", "validator-02", "validator-03"][0:$updated_count]),
      terraform_replacement_addresses: $terraform_replacement_addresses,
      validators: $validators[0],
      rollback: $rollback[0],
      compatibility_decision: $decision[0],
      automatic_finality_activation_pending:
        ($decision[0].state != "ACCEPTED"),
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' > artifacts/rolling-resume-evidence.json
  (
    cd artifacts
    sha256sum rolling-resume-evidence.json \
      > rolling-resume-evidence.json.sha256
  )
}

terraform -chdir=infra/aws/bootstrap init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/bootstrap.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="encrypt=true"
terraform -chdir=infra/aws/bootstrap output -json > artifacts/bootstrap-outputs.json

state_kms_key_arn="$(jq -er .state_kms_key_arn.value artifacts/bootstrap-outputs.json)"
lock_table="$(jq -er .lock_table.value artifacts/bootstrap-outputs.json)"
signer_arns="$(jq -ce '.validator_signer_arns.value | select(length == 3 and (unique | length) == 3)' artifacts/bootstrap-outputs.json)"
[[ "$(jq -er .aws_account_id.value artifacts/bootstrap-outputs.json)" == "$AWS_ACCOUNT_ID" ]]
[[ "$(jq -er .aws_region.value artifacts/bootstrap-outputs.json)" == "$AWS_REGION" ]]
[[ "$(jq -er .deployment_principal_arn.value artifacts/bootstrap-outputs.json)" == "$DEPLOYMENT_ROLE_ARN" ]]

terraform -chdir=infra/aws/public-testnet init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$lock_table" \
  -backend-config="encrypt=true" \
  -backend-config="kms_key_id=$state_kms_key_arn"

# Preserve an already-published public-services stage while rotating validator
# AMIs. Reverting this flag to false would plan destruction of the ALB, WAF,
# listeners, target groups and public DNS before replacement acceptance.
terraform -chdir=infra/aws/public-testnet output -json \
  > artifacts/pre-foundation-outputs.json
public_services_enabled="$(
  jq -r '
    .public_services_acceptance_readback.value.enabled
    | select(type == "boolean")
  ' \
    artifacts/pre-foundation-outputs.json
)"
case "$public_services_enabled" in
  true|false) ;;
  *) echo "public services readback must be boolean" >&2; exit 1 ;;
esac
if [[ "$public_services_enabled" == "true" ]]; then
  quorum_acceptance_sha256="$(
    jq -er '.public_services_acceptance_readback.value.quorum_evidence_sha256' \
      artifacts/pre-foundation-outputs.json
  )"
  runtime_acceptance_sha256="$(
    jq -er '.public_services_acceptance_readback.value.runtime_evidence_sha256' \
      artifacts/pre-foundation-outputs.json
  )"
  [[ "$quorum_acceptance_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$runtime_acceptance_sha256" =~ ^[0-9a-f]{64}$ ]]
else
  quorum_acceptance_sha256=""
  runtime_acceptance_sha256=""
fi

# Preserve an already-provisioned durable-state layer. Omitting these values
# after the opt-in migration would ask Terraform to remove the attachments and
# volumes on the next immutable AMI rollout.
validator_state_readback="$(
  jq -ce '.validator_state_volume_readback.value // []' \
    artifacts/pre-foundation-outputs.json
)"
validator_state_count="$(jq -r 'length' <<<"$validator_state_readback")"
case "$validator_state_count" in
  0)
    validator_state_provisioned=false
    validator_state_enabled=false
    validator_state_migration_accepted=false
    validator_state_rollback_snapshot_ids=null
    validator_state_size_gib=200
    validator_state_iops=6000
    validator_state_throughput_mibps=250
    validator_state_snapshot_ids=null
    ;;
  3)
    jq -e '
      (map(.validator_id) | sort) ==
        ["validator-01", "validator-02", "validator-03"] and
      all(.encrypted == true) and
      all(.type == "gp3") and
      all(.migration_required == false) and
      all(.migration_accepted == true) and
      all(.state_path == "/var/lib/junca") and
      (map(.volume_id) | unique | length) == 3 and
      all(.volume_id | test("^vol-[0-9a-f]{8,17}$")) and
      (map(.availability_zone) | unique | length) == 3 and
      (map(.size_gib) | unique | length) == 1 and
      (map(.iops) | unique | length) == 1 and
      (map(.throughput_mibps) | unique | length) == 1
    ' <<<"$validator_state_readback" >/dev/null
    validator_state_provisioned=true
    validator_state_enabled=true
    validator_state_migration_accepted=true
    validator_state_rollback_snapshot_ids="$(
      jq -ce '
        map(.rollback_snapshot_id)
        | select(
            length == 3 and
            (unique | length) == 3 and
            all(.[]; type == "string" and test("^snap-[0-9a-f]{8,17}$"))
          )
      ' <<<"$validator_state_readback"
    )"
    validator_state_size_gib="$(
      jq -er '.[0].size_gib' <<<"$validator_state_readback"
    )"
    validator_state_iops="$(
      jq -er '.[0].iops' <<<"$validator_state_readback"
    )"
    validator_state_throughput_mibps="$(
      jq -er '.[0].throughput_mibps' <<<"$validator_state_readback"
    )"
    validator_state_snapshot_ids="$(
      jq -c '
        map(.restored_snapshot) as $snapshots
        | if ($snapshots | length) != 3 then
            error("restored snapshots must contain exactly three values")
          elif (
            all($snapshots[]; . == null) or
            all($snapshots[]; . == "")
          ) then
            null
          elif (
            ($snapshots | unique | length) == 3 and
            all(
              $snapshots[];
              type == "string" and test("^snap-[0-9a-f]{8,17}$")
            )
          ) then
            $snapshots
          else
            error(
              "restored snapshots must be all null, all empty, or three unique snap IDs"
            )
          end
      ' <<<"$validator_state_readback"
    )"
    ;;
  *)
    echo "durable validator state must contain exactly zero or three volumes" >&2
    exit 1
    ;;
esac
validator_state_volume_ids="$(
  jq -ce 'map(.volume_id)' <<<"$validator_state_readback"
)"

# Bind the implicit replacement root-volume key to the exact encrypted
# candidate AMI snapshot. This uses EC2 readback already required by the
# deployment role and does not assume that the Terraform-state KMS key is also
# an EBS key.
aws ec2 get-ebs-encryption-by-default \
  --region "$AWS_REGION" > artifacts/ebs-encryption-default-readback.json
jq -e '.EbsEncryptionByDefault == true' \
  artifacts/ebs-encryption-default-readback.json >/dev/null
aws ec2 describe-images \
  --region "$AWS_REGION" \
  --owners self \
  --image-ids "$NODE_AMI_ID" \
  > artifacts/candidate-root-image-readback.json
candidate_root_snapshot_id="$(
  jq -er \
    --arg account_id "$AWS_ACCOUNT_ID" \
    --arg image_id "$NODE_AMI_ID" '
      .Images
      | select(length == 1)
      | .[0]
      | select(
          .ImageId == $image_id and
          .OwnerId == $account_id and
          .State == "available" and
          .Architecture == "x86_64" and
          .RootDeviceType == "ebs" and
          (.RootDeviceName | type == "string" and length > 0)
        )
      | . as $image
      | [
          .BlockDeviceMappings[]
          | select(
              .DeviceName == $image.RootDeviceName and
              .Ebs.VolumeSize == 16 and
              (.Ebs.SnapshotId |
                type == "string" and test("^snap-[0-9a-f]{8,17}$"))
            )
          | .Ebs.SnapshotId
        ]
      | select(length == 1)
      | .[0]
    ' artifacts/candidate-root-image-readback.json
)"
aws ec2 describe-snapshots \
  --region "$AWS_REGION" \
  --owner-ids self \
  --snapshot-ids "$candidate_root_snapshot_id" \
  > artifacts/candidate-root-snapshot-readback.json
root_ebs_kms_key_arn="$(
  jq -er \
    --arg account_id "$AWS_ACCOUNT_ID" \
    --arg region "$AWS_REGION" \
    --arg snapshot_id "$candidate_root_snapshot_id" '
      .Snapshots
      | select(length == 1)
      | .[0]
      | select(
          .SnapshotId == $snapshot_id and
          .OwnerId == $account_id and
          .State == "completed" and
          .Encrypted == true and
          .VolumeSize == 16 and
          (.KmsKeyId |
            test(
              "^arn:aws:kms:" + $region + ":" + $account_id +
              ":key/[0-9A-Za-z-]{16,}$"
            ))
        )
      | .KmsKeyId
    ' artifacts/candidate-root-snapshot-readback.json
)"
[[ "$root_ebs_kms_key_arn" =~ ^arn:aws:kms:${AWS_REGION}:${AWS_ACCOUNT_ID}:key/[0-9A-Za-z-]{16,}$ ]]

if [[ "$validator_state_enabled" == "true" ]]; then
  mapfile -t validator_state_volume_id_list < <(
    jq -er '.[]' <<<"$validator_state_volume_ids"
  )
  aws ec2 describe-volumes \
    --region "$AWS_REGION" \
    --volume-ids "${validator_state_volume_id_list[@]}" \
    > artifacts/validator-state-volume-plan-readback.json
  validator_state_kms_key_arns="$(
    jq -ce \
      --arg account_id "$AWS_ACCOUNT_ID" \
      --arg region "$AWS_REGION" \
      --argjson state "$validator_state_readback" '
        .Volumes as $volumes
        | [
            $state[] as $expected
            | [
                $volumes[]
                | select(
                    .VolumeId == $expected.volume_id and
                    .AvailabilityZone == $expected.availability_zone and
                    .Encrypted == true and
                    .Size == $expected.size_gib and
                    .Iops == $expected.iops and
                    .Throughput == $expected.throughput_mibps and
                    .VolumeType == $expected.type and
                    .State == "in-use" and
                    (.KmsKeyId |
                      test(
                        "^arn:aws:kms:" + $region + ":" + $account_id +
                        ":key/[0-9A-Za-z-]{16,}$"
                      ))
                  )
                | .KmsKeyId
              ]
            | select(length == 1)
            | .[0]
          ]
        | select(length == 3)
      ' artifacts/validator-state-volume-plan-readback.json
  )"
else
  validator_state_kms_key_arns='[]'
fi

# Preserve the exact Terraform-canonical automatic finality epoch after its
# first successful apply. A later AMI rollout must not create a second slot
# schedule or silently disable the running schedule.
existing_finality="$(
  jq -ce '
    .automatic_finality_readback.value //
      {enabled: false, block_interval_seconds: 0, slot_epoch_seconds: 0}
  ' artifacts/pre-foundation-outputs.json
)"
rolling_release="${FOUNDATION_ROLLING_RELEASE:-false}"
case "$rolling_release" in
  true|false) ;;
  *)
    echo "FOUNDATION_ROLLING_RELEASE must be true or false" >&2
    exit 2
    ;;
esac
if [[ "$rolling_release" == "true" ]]; then
  for name in \
    AMI_RUN_ID MANIFEST_GATE_RUN_ID REQUEST_SHA256 \
    MANIFEST_DECISION_SHA256 GITHUB_RUN_ID GITHUB_SHA GITHUB_REPOSITORY \
    ROLLING_RESUME_RUN_ID ROLLING_CANDIDATE_HEAD_SHA
  do
    [[ -n "${!name:-}" ]] || {
      echo "missing rolling release binding: $name" >&2
      exit 2
    }
  done
  [[ "$AMI_RUN_ID" =~ ^[1-9][0-9]*$ ]]
  [[ "$MANIFEST_GATE_RUN_ID" =~ ^[1-9][0-9]*$ ]]
  [[ "$REQUEST_SHA256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$MANIFEST_DECISION_SHA256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]]
  [[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
  [[ "$ROLLING_CANDIDATE_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]
  [[ "$ROLLING_RESUME_RUN_ID" =~ ^(0|[1-9][0-9]*)$ ]]
  test "$GITHUB_REPOSITORY" = \
    "JAIOS-Governance/junca-social-ecosystem-chain"
  automatic_finality_enabled="${AUTOMATIC_FINALITY_ENABLED:-}"
  validator_block_interval_seconds="${VALIDATOR_BLOCK_INTERVAL_SECONDS:-}"
  validator_slot_epoch_seconds="${VALIDATOR_SLOT_EPOCH_SECONDS:-}"
  validator_bootstrap_slot_epochs_json="${VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"
  rolling_resume_prior_slot_epoch_seconds="${ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"
  rolling_epoch_renewal_performed="${ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"
  rolling_epoch_renewal_prefix_count="${ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"
  test "$automatic_finality_enabled" = "true"
  test "$validator_block_interval_seconds" = "30"
  [[ "$validator_slot_epoch_seconds" =~ ^[0-9]+$ ]]
  [[ "$rolling_resume_prior_slot_epoch_seconds" =~ ^[0-9]+$ ]]
  [[ "$rolling_epoch_renewal_prefix_count" =~ ^[0-3]$ ]]
  case "$rolling_epoch_renewal_performed" in
    true|false) ;;
    *) echo "ROLLING_EPOCH_RENEWAL_PERFORMED must be true or false" >&2; exit 2 ;;
  esac
  jq -e '
    type == "array" and length == 3 and
    all(.[];
      type == "number" and
      floor == . and
      . > 0 and
      . % 30 == 0
    )
  ' <<<"$validator_bootstrap_slot_epochs_json" >/dev/null
  epoch_remaining="$((validator_slot_epoch_seconds - $(date +%s)))"
  test "$epoch_remaining" -ge 900
  test "$epoch_remaining" -le 7230
  test "$((validator_slot_epoch_seconds % 30))" -eq 0
elif [[ "$(jq -r .enabled <<<"$existing_finality")" == "true" ]]; then
  automatic_finality_enabled=true
  validator_block_interval_seconds="$(
    jq -er '.block_interval_seconds | select(. == 30)' <<<"$existing_finality"
  )"
  validator_slot_epoch_seconds="$(
    jq -er '
      .slot_epoch_seconds
      | select(
          type == "number" and . > 0 and
          floor == . and . % 30 == 0
        )
    ' <<<"$existing_finality"
  )"
else
  automatic_finality_enabled="${AUTOMATIC_FINALITY_ENABLED:-false}"
  validator_block_interval_seconds="${VALIDATOR_BLOCK_INTERVAL_SECONDS:-30}"
  validator_slot_epoch_seconds="${VALIDATOR_SLOT_EPOCH_SECONDS:-0}"
  case "$automatic_finality_enabled" in
    true)
      [[ "$validator_block_interval_seconds" =~ ^[0-9]+$ ]]
      [[ "$validator_slot_epoch_seconds" =~ ^[0-9]+$ ]]
      test "$validator_block_interval_seconds" -eq 30
      test "$validator_slot_epoch_seconds" -gt "$(date +%s)"
      test "$((validator_slot_epoch_seconds % 30))" -eq 0
      ;;
    false)
      validator_block_interval_seconds=30
      validator_slot_epoch_seconds=0
      ;;
    *)
      echo "AUTOMATIC_FINALITY_ENABLED must be true or false" >&2
      exit 2
      ;;
  esac
fi

if [[ "$phase" == "foundation-apply" &&
      "$automatic_finality_enabled" != "true" ]]; then
  echo "foundation apply requires automatic finality to be enabled" >&2
  exit 2
fi

jq -n \
  --arg aws_account_id "$AWS_ACCOUNT_ID" \
  --arg aws_region "$AWS_REGION" \
  --arg domain_name "$DOMAIN_NAME" \
  --arg route53_zone_id "$ROUTE53_ZONE_ID" \
  --arg deployment_principal_arn "$DEPLOYMENT_ROLE_ARN" \
  --arg node_ami_id "$NODE_AMI_ID" \
  --arg node_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
  --arg genesis_sha256 "$GENESIS_SHA256" \
  --arg source_commit "$SOURCE_COMMIT" \
  --arg quorum_acceptance_sha256 "$quorum_acceptance_sha256" \
  --arg runtime_acceptance_sha256 "$runtime_acceptance_sha256" \
  --argjson enable_validator_state_volumes "$validator_state_enabled" \
  --argjson provision_validator_state_volumes \
    "$validator_state_provisioned" \
  --argjson validator_state_migration_accepted \
    "$validator_state_migration_accepted" \
  --argjson validator_state_rollback_snapshot_ids \
    "$validator_state_rollback_snapshot_ids" \
  --argjson validator_state_volume_size_gib "$validator_state_size_gib" \
  --argjson validator_state_volume_iops "$validator_state_iops" \
  --argjson validator_state_volume_throughput_mibps \
    "$validator_state_throughput_mibps" \
  --argjson validator_state_snapshot_ids "$validator_state_snapshot_ids" \
  --argjson automatic_finality_enabled "$automatic_finality_enabled" \
  --argjson validator_block_interval_seconds \
    "$validator_block_interval_seconds" \
  --argjson validator_slot_epoch_seconds "$validator_slot_epoch_seconds" \
  --argjson validator_bootstrap_slot_epoch_seconds \
    "$validator_bootstrap_slot_epochs_json" \
  --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
  --argjson validator_signer_arns "$signer_arns" \
  --argjson enable_public_services "$public_services_enabled" \
  '{
    aws_account_id: $aws_account_id,
    aws_region: $aws_region,
    availability_zones: $availability_zones,
    domain_name: $domain_name,
    route53_zone_id: $route53_zone_id,
    deployment_principal_arn: $deployment_principal_arn,
    validator_signer_arns: $validator_signer_arns,
    node_ami_id: $node_ami_id,
    node_artifact_sha256: $node_artifact_sha256,
    genesis_sha256: $genesis_sha256,
    source_commit: $source_commit,
    enable_validator_state_volumes: $enable_validator_state_volumes,
    provision_validator_state_volumes: $provision_validator_state_volumes,
    validator_state_migration_accepted: $validator_state_migration_accepted,
    validator_state_rollback_snapshot_ids:
      $validator_state_rollback_snapshot_ids,
    validator_state_volume_size_gib: $validator_state_volume_size_gib,
    validator_state_volume_iops: $validator_state_volume_iops,
    validator_state_volume_throughput_mibps:
      $validator_state_volume_throughput_mibps,
    validator_state_snapshot_ids: $validator_state_snapshot_ids,
    automatic_finality_enabled: $automatic_finality_enabled,
    validator_block_interval_seconds: $validator_block_interval_seconds,
    validator_slot_epoch_seconds: $validator_slot_epoch_seconds,
    validator_bootstrap_slot_epoch_seconds:
      $validator_bootstrap_slot_epoch_seconds,
    enable_public_services: $enable_public_services,
    quorum_acceptance_sha256: (
      if $enable_public_services then $quorum_acceptance_sha256 else null end
    ),
    runtime_acceptance_sha256: (
      if $enable_public_services then $runtime_acceptance_sha256 else null end
    )
  }' > artifacts/foundation.auto.tfvars.json

# Render the exact three user-data payloads from a single Terraform local used
# by aws_instance.validator. The provider stores SHA-1 in plan JSON, so these
# independently evaluated digests close the plan/apply binding without
# accepting an arbitrary 40-hex replacement value.
expected_user_data_sha1="$(
  terraform -chdir=infra/aws/public-testnet console \
    -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
    <<<'jsonencode([for value in local.validator_user_data : sha1(value)])' |
    jq -cer '
      fromjson
      | select(
          type == "array" and
          length == 3 and
          (unique | length) == 3 and
          all(.[]; type == "string" and test("^[0-9a-f]{40}$"))
        )
    '
)"
validator_user_data_template_sha256="$(
  sha256sum \
    infra/aws/public-testnet/templates/validator-user-data.sh.tftpl |
    cut -d' ' -f1
)"
[[ "$validator_user_data_template_sha256" =~ ^[0-9a-f]{64}$ ]]
jq -n \
  --arg root_ebs_kms_key_arn "$root_ebs_kms_key_arn" \
  --arg template_sha256 "$validator_user_data_template_sha256" \
  --argjson user_data_sha1 "$expected_user_data_sha1" \
  '{
    schema_version: 1,
    root_ebs_kms_key_arn: $root_ebs_kms_key_arn,
    template_sha256: $template_sha256,
    user_data_sha1: $user_data_sha1
  }' > artifacts/foundation-render-bindings.json

terraform -chdir=infra/aws/public-testnet plan -input=false \
  -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
  -out="$GITHUB_WORKSPACE/artifacts/foundation.tfplan"
terraform -chdir=infra/aws/public-testnet show -json \
  "$GITHUB_WORKSPACE/artifacts/foundation.tfplan" > artifacts/foundation-plan.json
jq -e \
  --argjson expected "$expected_user_data_sha1" '
    .output_changes.validator_user_data_sha1.after == $expected and
    (
      .output_changes.validator_user_data_sha1.after_unknown // false
    ) == false
  ' artifacts/foundation-plan.json >/dev/null

# Every managed non-noop change is fail-closed. A rolling release may replace
# only the canonical validator suffix and its exact attachments; the only
# in-place updates are validator alarm InstanceId dimensions. Legacy
# non-rolling apply is retained only for an already-converged no-op state.
jq -e \
  --arg phase "$phase" \
  --arg node_ami_id "$NODE_AMI_ID" \
  --arg root_ebs_kms_key_arn "$root_ebs_kms_key_arn" \
  --argjson rolling_release "$rolling_release" \
  --argjson public_services_enabled "$public_services_enabled" \
  --argjson validator_state_enabled "$validator_state_enabled" \
  --argjson validator_state_volume_ids "$validator_state_volume_ids" \
  --argjson validator_state_kms_key_arns \
    "$validator_state_kms_key_arns" \
  --argjson validator_state_rollback_snapshot_ids \
    "$validator_state_rollback_snapshot_ids" \
  --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
  --argjson expected_user_data_sha1 "$expected_user_data_sha1" \
  --argjson current_validator_ids "$(
    jq -c '.validator_instance_ids.value' artifacts/pre-foundation-outputs.json
  )" '
  # BEGIN_ROLLING_FULL_PLAN_GATE
  def validator_index:
    .address |
      capture("^aws_instance\\.validator\\[(?<index>[0-2])\\]$").index |
      tonumber;

  def retained_state_drift(
    $volume_ids;
    $state_kms;
    $rollback_snapshot_ids;
    $zones
  ):
    validator_index as $index
    | .mode == "managed" and
      .type == "aws_instance" and
      .name == "validator" and
      .index == $index and
      .change.actions == ["update"] and
      (.change.replace_paths // []) == [] and
      .change.before.ebs_block_device == [] and
      (
        (.change.before |
          del(.ebs_block_device, .root_block_device[0].tags)) ==
        (.change.after |
          del(.ebs_block_device, .root_block_device[0].tags))
      ) and
      (
        .change.before.root_block_device[0].tags == null or
        .change.before.root_block_device[0].tags == {}
      ) and
      .change.after.root_block_device[0].tags == {} and
      ([.change.after_unknown | .. | select(. == true)] | length) == 0 and
      (.change.after.ebs_block_device | length) == 1 and
      (
        .change.after.ebs_block_device[0] as $volume
        | $volume.delete_on_termination == false and
          $volume.device_name == "/dev/sdf" and
          $volume.encrypted == true and
          $volume.iops == 6000 and
          $volume.kms_key_id == $state_kms[$index] and
          $volume.snapshot_id == "" and
          $volume.throughput == 250 and
          $volume.volume_id == $volume_ids[$index] and
          $volume.volume_size == 200 and
          $volume.volume_type == "gp3" and
          $volume.tags == $volume.tags_all and
          ($volume.tags | keys) == [
            "AssetsMoved",
            "BridgeActivated",
            "FailureDomain",
            "Governance",
            "JuncaFilesystemVerified",
            "JuncaFinalityCertificateBackfilled",
            "JuncaMigrationState",
            "JuncaRollbackSnapshotId",
            "JuncaStateStoreIntegrity",
            "MainnetChanged",
            "ManagedBy",
            "MigrationRequired",
            "MonetaryUse",
            "Name",
            "Network",
            "Project",
            "PublicTestnetOnly",
            "StatePath",
            "Validator"
          ] and
          $volume.tags.AssetsMoved == "false" and
          $volume.tags.BridgeActivated == "false" and
          $volume.tags.FailureDomain == $zones[$index] and
          $volume.tags.Governance ==
            "JAIOS Institutional Governance" and
          $volume.tags.JuncaFilesystemVerified == "true" and
          $volume.tags.JuncaFinalityCertificateBackfilled == "true" and
          $volume.tags.JuncaMigrationState == "VERIFIED_PASS" and
          $volume.tags.JuncaRollbackSnapshotId ==
            $rollback_snapshot_ids[$index] and
          $volume.tags.JuncaStateStoreIntegrity == "true" and
          $volume.tags.MainnetChanged == "false" and
          $volume.tags.ManagedBy == "Terraform" and
          $volume.tags.MigrationRequired == "false" and
          $volume.tags.MonetaryUse == "None" and
          $volume.tags.Name == (
            "junca-social-ecosystem-chain-testnet-validator-0" +
            (($index + 1) | tostring) + "-state"
          ) and
          $volume.tags.Network == "Public Testnet" and
          $volume.tags.Project == "JUNCA Social Ecosystem Chain" and
          $volume.tags.PublicTestnetOnly == "true" and
          $volume.tags.StatePath == "/var/lib/junca" and
          $volume.tags.Validator == ("0" + (($index + 1) | tostring))
      );

  def alarm_update($replacement_indices; $current_ids):
    (.address |
      capture("^aws_cloudwatch_metric_alarm\\.validator_status\\[(?<index>[0-2])\\]$").index |
      tonumber) as $index
    |
    .change.actions == ["update"] and
    (.change.replace_paths // []) == [] and
    ((.change.before | del(.dimensions)) ==
      (.change.after | del(.dimensions))) and
    (.change.before.dimensions | keys) == ["InstanceId"] and
    (.change.before.dimensions.InstanceId |
      test("^i-[0-9a-f]{8,17}$")) and
    (
      if ($replacement_indices | index($index)) != null then
        .change.after.dimensions == null and
        .change.after_unknown.dimensions == true
      else
        .change.after.dimensions ==
          {"InstanceId": $current_ids[$index]} and
        ([.change.after_unknown | .. | select(. == true)] | length) == 0
      end
    );

  . as $plan
  | [
      .resource_changes[]?
      | select(
          .mode == "managed" and
          .change.actions != ["no-op"]
        )
    ] as $changes
  | [
    $changes[]
    | select(.address | test("^aws_instance\\.validator\\[[0-2]\\]$"))
  ] as $validators
  | [
      $validators[].address
      | capture("^aws_instance\\.validator\\[(?<index>[0-2])\\]$").index
      | tonumber
    ] as $indices
  | [
      $indices[] as $index
      | "aws_lb_target_group_attachment.rpc[\($index)]",
        "aws_lb_target_group_attachment.explorer[\($index)]"
    ] as $expected_attachments
  | [
      $indices[] as $index
      | "aws_volume_attachment.validator_state[\($index)]"
    ] as $expected_state_attachments
  | [
      $changes[]
      | select(.address | test(
          "^aws_lb_target_group_attachment\\.(rpc|explorer)\\[[0-2]\\]$"
        ))
    ] as $attachments
  | [
      $changes[]
      | select(.address | test(
          "^aws_volume_attachment\\.validator_state\\[[0-2]\\]$"
        ))
    ] as $state_attachments
  | [
      $changes[]
      | select(.address | test(
          "^aws_cloudwatch_metric_alarm\\.validator_status\\[[0-2]\\]$"
        ))
    ] as $alarms
  | [($plan.resource_drift // [])[]?] as $drift
  | (
      if $validator_state_enabled then [0, 1, 2] else [] end
    ) as $expected_drift_indices
  | [
      $expected_drift_indices[] |
      "aws_instance.validator[\(.)]"
    ] as $expected_drift_addresses
  | (
      if ($indices | length) > 0 then
        [$indices[] |
          "aws_cloudwatch_metric_alarm.validator_status[\(.)]"]
      else
        [$alarms[].address]
      end
    ) as $expected_alarms
  | $plan.format_version == "1.2" and
    $plan.terraform_version == "1.9.8" and
    $plan.complete == true and
    $plan.errored == false and
    (($plan.deferred_changes // []) | length) == 0 and
    ($drift | length) <= ($expected_drift_addresses | length) and
    ([ $drift[].address ] | unique | length) == ($drift | length) and
    all(
      $drift[];
      .address as $drift_address |
      ($expected_drift_addresses | index($drift_address)) != null
    ) and
    all(
      $drift[];
      retained_state_drift(
        $validator_state_volume_ids;
        $validator_state_kms_key_arns;
        $validator_state_rollback_snapshot_ids;
        $availability_zones
      )
    ) and
    all(
      $plan.resource_changes[]?;
      if .mode == "managed" then
        true
      elif .mode == "data" then
        (.change.actions == ["read"] or .change.actions == ["no-op"])
      else
        false
      end
    ) and
    (
      if $rolling_release then
        (($changes | length) == 0 or $plan.applyable == true) and
        ($validators | length) <= 3 and
        ([ $changes[].address ] | unique | length) == ($changes | length) and
        ([ $alarms[].address ] | sort) == ($expected_alarms | sort) and
        (
          if $public_services_enabled then
            ([ $attachments[].address ] | sort) ==
              ($expected_attachments | sort)
          else
            ($attachments | length) == 0
          end
        ) and
        (
          if $validator_state_enabled then
            ([ $state_attachments[].address ] | sort) ==
              ($expected_state_attachments | sort)
          else
            ($state_attachments | length) == 0
          end
        ) and
        ($changes | length) == (
          ($validators | length) +
          ($attachments | length) +
          ($state_attachments | length) +
          ($alarms | length)
        ) and
        all(
          $validators[];
          .change.actions == ["delete", "create"] and
          .change.replace_paths == [["ami"], ["user_data"]] and
          .change.after.ami == $node_ami_id and
          .change.after.private_ip ==
            ["10.67.16.10", "10.67.32.10", "10.67.48.10"][
              (.address |
                capture("\\[(?<index>[0-2])\\]$").index |
                tonumber)
            ] and
          .change.after.associate_public_ip_address == false and
          .change.after.instance_type == "m7i.large" and
          .change.after.iam_instance_profile ==
            ("junca-social-ecosystem-chain-testnet-validator-" +
              (((.address |
                capture("\\[(?<index>[0-2])\\]$").index |
                tonumber) + 1) | tostring)) and
          .change.before.iam_instance_profile ==
            .change.after.iam_instance_profile and
          .change.before.subnet_id == .change.after.subnet_id and
          (.change.after.subnet_id | test("^subnet-[0-9a-f]{8,17}$")) and
          .change.before.vpc_security_group_ids ==
            .change.after.vpc_security_group_ids and
          (.change.after.vpc_security_group_ids | length) == 1 and
          (.change.after.vpc_security_group_ids[0] |
            test("^sg-[0-9a-f]{8,17}$")) and
          .change.before.tags_all == .change.after.tags_all and
          .change.after.tags_all.Project ==
            "JUNCA Social Ecosystem Chain" and
          .change.after.tags_all.Governance ==
            "JAIOS Institutional Governance" and
          .change.after.tags_all.Network == "Public Testnet" and
          .change.after.tags_all.MonetaryUse == "None" and
          .change.after.tags_all.ManagedBy == "Terraform" and
          .change.after.monitoring == true and
          (.change.before.user_data | test("^[0-9a-f]{40}$")) and
          .change.after.user_data ==
            $expected_user_data_sha1[
              (.address |
                capture("\\[(?<index>[0-2])\\]$").index |
                tonumber)
            ] and
          (.change.after_unknown.user_data // false) == false and
          .change.after.user_data_replace_on_change == true and
          .change.after.source_dest_check == true and
          .change.after.metadata_options[0].http_endpoint == "enabled" and
          .change.after.metadata_options[0].http_tokens == "required" and
          .change.after.root_block_device[0].encrypted == true and
          .change.after.root_block_device[0].delete_on_termination == true and
          .change.before.root_block_device[0].kms_key_id ==
            $root_ebs_kms_key_arn and
          .change.after.root_block_device[0].kms_key_id == null and
          .change.after_unknown.root_block_device[0].kms_key_id == true and
          .change.after.root_block_device[0].volume_type == "gp3" and
          .change.after.root_block_device[0].volume_size == 200 and
          .change.after.root_block_device[0].iops == 6000 and
          .change.after.root_block_device[0].throughput == 250
        ) and
        all(
          $attachments[];
          .change.actions == ["delete", "create"] and
          .change.replace_paths == [["target_id"]] and
          .change.before.target_group_arn ==
            .change.after.target_group_arn and
          .change.after_unknown.target_id == true and
          (
            if (.address | contains(".rpc[")) then
              .change.after.port == 8546
            else
              .change.after.port == 3000
            end
          )
        ) and
        all(
          $state_attachments[];
          .change.actions == ["delete", "create"] and
          .change.replace_paths == [["instance_id"]] and
          .change.after.device_name == "/dev/sdf" and
          .change.after.volume_id == .change.before.volume_id and
          .change.after.force_detach == false and
          .change.after.stop_instance_before_detaching == true and
          .change.after_unknown.instance_id == true
        ) and
        all($alarms[]; alarm_update($indices; $current_validator_ids))
      elif $phase == "foundation-plan" then
        true
      else
        ($changes | length) == 0
      end
    )
  # END_ROLLING_FULL_PLAN_GATE
' artifacts/foundation-plan.json >/dev/null

mapfile -t validator_replacements < <(
  jq -r '
    [
      .resource_changes[]?
      | select(
          (.change.actions | index("delete")) and
          (.address | test("^aws_instance\\.validator\\[[0-2]\\]$"))
        )
      | .address
    ] | sort[]
  ' artifacts/foundation-plan.json
)

terraform_replacement_addresses_json="$(
  printf '%s\n' "${validator_replacements[@]}" |
    jq -Rsc 'split("\n")[:-1]'
)"
if (( ${#validator_replacements[@]} > 0 )); then
  test "$rolling_release" = "true"
fi

if [[ "$phase" == "foundation-apply" && "$rolling_release" == "true" ]]; then
  # Resolve the complete fixed-document caller surface before the first
  # runtime or Terraform mutation. Repository-only/null live acceptance blocks
  # here; fresh live metadata can never self-authorize an unreviewed version.
  for fixed_document_name in \
    JuncaPTBootstrapReadiness \
    JuncaPTFinalityInspect \
    JuncaPTFinalitySet \
    JuncaPTRuntimeObservation
  do
    junca_fixed_ssm_validate_document \
      "$fixed_document_name" artifacts/fixed-ssm-pre-rollout
  done
  mapfile -t pre_rollout_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/pre-foundation-outputs.json
  )
  test "${#pre_rollout_instances[@]}" = 3
  resume_path="${ROLLING_RESUME_EVIDENCE_PATH:-}"
  resume_updated_count=0
  resume_evidence_validators_path=""
  live_prefix_rollback_path=""
  if [[ "$ROLLING_RESUME_RUN_ID" == "0" ]]; then
    test -z "$resume_path"
    test "${#validator_replacements[@]}" = 3
    previous_artifact_sha256="$(
      jq -er '
        .approved_node_ami_readback.value.node_sha256
        | select(type == "string" and test("^[0-9a-f]{64}$"))
      ' artifacts/pre-foundation-outputs.json
    )"
    previous_ami_id="$(
      jq -er '
        .approved_node_ami_readback.value.id
        | select(type == "string" and test("^ami-[0-9a-f]{8,17}$"))
      ' artifacts/pre-foundation-outputs.json
    )"
    test "$previous_artifact_sha256" != "$NODE_ARTIFACT_SHA256"
    test "$previous_ami_id" != "$NODE_AMI_ID"
  else
    test -f "$resume_path"
    jq -e \
      --arg repository "$GITHUB_REPOSITORY" \
      --arg candidate_head_sha "$ROLLING_CANDIDATE_HEAD_SHA" \
      --argjson producer_run_id "$ROLLING_RESUME_RUN_ID" \
      --argjson ami_run_id "$AMI_RUN_ID" \
      --argjson manifest_gate_run_id "$MANIFEST_GATE_RUN_ID" \
      --arg source_commit "$SOURCE_COMMIT" \
      --arg node_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
      --arg genesis_sha256 "$GENESIS_SHA256" \
      --arg ami_id "$NODE_AMI_ID" \
      --arg request_sha256 "$REQUEST_SHA256" \
      --arg manifest_decision_sha256 "$MANIFEST_DECISION_SHA256" \
      --argjson validator_block_interval_seconds \
        "$validator_block_interval_seconds" \
      --argjson validator_slot_epoch_seconds \
        "$validator_slot_epoch_seconds" \
      --argjson validator_bootstrap_slot_epochs \
        "$validator_bootstrap_slot_epochs_json" \
      --argjson rolling_resume_prior_slot_epoch_seconds \
        "$rolling_resume_prior_slot_epoch_seconds" \
      --argjson rolling_epoch_renewal_performed \
        "$rolling_epoch_renewal_performed" \
      --argjson rolling_epoch_renewal_prefix_count \
        "$rolling_epoch_renewal_prefix_count" '
        .schema_version == "junca-validator-rolling-resume/v1" and
        .repository == $repository and
        (.candidate.provenance_head_sha // .head_sha) ==
          $candidate_head_sha and
        .producer_run_id == $producer_run_id and
        .ami_run_id == $ami_run_id and
        .manifest_gate_run_id == $manifest_gate_run_id and
        .candidate.source_commit == $source_commit and
        .candidate.node_artifact_sha256 == $node_artifact_sha256 and
        .candidate.genesis_sha256 == $genesis_sha256 and
        .candidate.ami_id == $ami_id and
        .candidate.request_sha256 == $request_sha256 and
        .candidate.manifest_decision_sha256 ==
          $manifest_decision_sha256 and
        .automatic_finality.block_interval_seconds ==
          $validator_block_interval_seconds and
        .automatic_finality.slot_epoch_seconds ==
          $rolling_resume_prior_slot_epoch_seconds and
        .automatic_finality.minimum_remaining_seconds == 900 and
        .automatic_finality.maximum_remaining_seconds == 7230 and
        (
          (
            .terraform_bootstrap.slot_epoch_seconds //
            [
              .automatic_finality.slot_epoch_seconds,
              .automatic_finality.slot_epoch_seconds,
              .automatic_finality.slot_epoch_seconds
            ]
          ) as $prior_bootstrap
          | ($prior_bootstrap | type == "array" and length == 3) and
            (
              if $rolling_epoch_renewal_performed then
                $validator_slot_epoch_seconds >
                  $rolling_resume_prior_slot_epoch_seconds and
                $rolling_epoch_renewal_prefix_count >= .updated_count and
                $rolling_epoch_renewal_prefix_count <=
                  ([.updated_count + 1, 3] | min) and
                (
                  [
                    range(0; 3) as $index
                    | if $index < $rolling_epoch_renewal_prefix_count
                      then $validator_bootstrap_slot_epochs[$index] ==
                        $prior_bootstrap[$index]
                      else $validator_bootstrap_slot_epochs[$index] ==
                        $validator_slot_epoch_seconds
                      end
                  ] | all
                )
              else
                $validator_slot_epoch_seconds ==
                  $rolling_resume_prior_slot_epoch_seconds and
                $validator_bootstrap_slot_epochs == $prior_bootstrap and
                $rolling_epoch_renewal_prefix_count == 0
              end
            )
        ) and
        (.updated_count | type) == "number" and
        .updated_count >= 0 and .updated_count <= 3 and
        .updated_validator_ids ==
          (["validator-01","validator-02","validator-03"][0:.updated_count]) and
        .mainnet_changed == false and
        .assets_moved == false and
        .bridge_activated == false
      ' "$resume_path" >/dev/null
    previous_artifact_sha256="$(
      jq -er '.rollback.artifact_sha256' "$resume_path"
    )"
    previous_ami_id="$(jq -er '.rollback.ami_id' "$resume_path")"
    [[ "$previous_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
    [[ "$previous_ami_id" =~ ^ami-[0-9a-f]{8,17}$ ]]
    test "$previous_artifact_sha256" != "$NODE_ARTIFACT_SHA256"
    test "$previous_ami_id" != "$NODE_AMI_ID"
    jq -e \
      --arg previous_artifact_sha256 "$previous_artifact_sha256" \
      --arg previous_ami_id "$previous_ami_id" '
        .rollback.target_version == $previous_artifact_sha256 and
        .rollback.artifact_sha256 == $previous_artifact_sha256 and
        .rollback.ami_id == $previous_ami_id and
        .rollback.rehearsal_passed == true and
        .rollback.automatic_finality_disabled == true and
        .rollback.no_state_rewind == true and
        .rollback.durable_volume_reused == true and
        .rollback.snapshot_restore_performed == false and
        (.rollback.validators | length) == 3
      ' "$resume_path" >/dev/null
    jq '.rollback' "$resume_path" > artifacts/rollback-rehearsal.json
    live_prefix_rollback_path=artifacts/rollback-rehearsal.json
    jq '.validators' "$resume_path" \
      > artifacts/resume-evidence-validators.json
    resume_evidence_validators_path=artifacts/resume-evidence-validators.json
    resume_updated_count="$(jq -er '.updated_count' "$resume_path")"
  fi

  # A failed targeted apply can replace one validator before its resume
  # evidence is rewritten. Treat the evidence count as a committed lower bound
  # and recover only the one next contiguous, fully read-back target prefix.
  # This readback completes before any runtime.env mutation.
  write_live_rollout_prefix_readback \
    "$resume_updated_count" \
    "$resume_evidence_validators_path" \
    "$previous_artifact_sha256" "$previous_ami_id" \
    "$live_prefix_rollback_path"
  live_updated_count="$(
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
  if [[ "$rolling_epoch_renewal_performed" == "true" ]]; then
    test "$live_updated_count" = "$rolling_epoch_renewal_prefix_count"
  else
    test "$rolling_epoch_renewal_prefix_count" = "0"
  fi

  # Stop automatic finality before the next replacement. The observed target
  # prefix is bound strictly to the candidate artifact; only the remaining
  # legacy suffix may initialize all-absent false/0/0 keys.
  pre_rollout_finality_bindings="$(
    build_pre_rollout_finality_bindings \
      "$live_updated_count" \
      "$NODE_ARTIFACT_SHA256" "$evidence_bound_baseline_bindings" \
      "${pre_rollout_instances[@]}"
  )"
  set_runtime_finality \
    0 0 "$pre_rollout_finality_bindings"
  for index in 0 1 2; do
    capture_validator_observation \
      "validator-0$((index + 1))" \
      "${pre_rollout_instances[$index]}" \
      "artifacts/pre-rollout-validator-$((index + 1)).json"
  done

  validator_state_rollback="$(
    jq -ce '
      .validator_state_volume_readback.value
      | select(
          length == 3 and
          (map(.validator_id) | sort) ==
            ["validator-01", "validator-02", "validator-03"] and
          (map(.volume_id) | unique | length) == 3 and
          (map(.rollback_snapshot_id) | unique | length) == 3
        )
    ' artifacts/pre-foundation-outputs.json
  )"
  for index in 0 1 2; do
    state_volume_id="$(
      jq -er ".[$index].volume_id" <<<"$validator_state_rollback"
    )"
    aws ec2 describe-volumes \
      --volume-ids "$state_volume_id" \
      > "artifacts/rollback-volume-$((index + 1)).json"
    jq -e \
      --arg instance_id "${pre_rollout_instances[$index]}" '
        .Volumes | length == 1 and
        .[0].Encrypted == true and
        .[0].State == "in-use" and
        (.[0].Attachments | length) == 1 and
        .[0].Attachments[0].InstanceId == $instance_id and
        .[0].Attachments[0].State == "attached"
      ' "artifacts/rollback-volume-$((index + 1)).json" >/dev/null
  done
  mapfile -t rollback_snapshot_ids < <(
    jq -er '.[].rollback_snapshot_id' <<<"$validator_state_rollback"
  )
  aws ec2 describe-snapshots \
    --snapshot-ids "${rollback_snapshot_ids[@]}" \
    --owner-ids self \
    > artifacts/rollback-snapshot-readback.json
  jq -e \
    --argjson expected "$(
      printf '%s\n' "${rollback_snapshot_ids[@]}" |
        jq -Rsc 'split("\n")[:-1] | sort'
    )" '
      (.Snapshots | length) == 3 and
      ([.Snapshots[].SnapshotId] | sort) == $expected and
      all(.Snapshots[]; .State == "completed" and .Encrypted == true)
    ' artifacts/rollback-snapshot-readback.json >/dev/null

  if [[ "$ROLLING_RESUME_RUN_ID" == "0" ]]; then
    jq -n \
      --arg target_version "$previous_artifact_sha256" \
      --arg artifact_sha256 "$previous_artifact_sha256" \
      --arg ami_id "$previous_ami_id" \
      --slurpfile observed <(
        jq -s '.' artifacts/pre-rollout-validator-{1,2,3}.json
      ) \
      --argjson state "$validator_state_rollback" '{
        target_version: $target_version,
        artifact_sha256: $artifact_sha256,
        ami_id: $ami_id,
        rehearsal_passed: true,
        automatic_finality_disabled: true,
        no_state_rewind: true,
        durable_volume_reused: true,
        snapshot_restore_performed: false,
        validators: [
          range(0; 3) as $index
          | $observed[0][$index] as $health
          | $state[$index] as $volume
          | {
              validator_id: $health.validator_id,
              volume_id: $volume.volume_id,
              rollback_snapshot_id: $volume.rollback_snapshot_id,
              state_rewind_permitted: false,
              head_height: $health.head_height,
              head_hash: $health.head_hash,
              certificate_hash: $health.certificate_hash,
              certificate_height: $health.certificate_height,
              certificate_block_hash: $health.certificate_block_hash,
              certificate_finality_status:
                $health.certificate_finality_status,
              certificate_signed_power: $health.certificate_signed_power,
              certificate_total_power: $health.certificate_total_power,
              certificate_validator_ids: $health.certificate_validator_ids,
              certificate_vote_hashes: $health.certificate_vote_hashes
            }
        ],
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' > artifacts/rollback-rehearsal.json
  else
    jq -e \
      --argjson state "$validator_state_rollback" '
        [.rollback.validators[] |
          {validator_id, volume_id, rollback_snapshot_id}] ==
        [$state[] |
          {validator_id, volume_id, rollback_snapshot_id}]
      ' "$resume_path" >/dev/null
  fi

  write_rolling_compatibility_evidence AUTO
  live_updated_count="$(
    jq -er '.updated_count' artifacts/rolling-compatibility-decision.json
  )"
  prior_updated_count=0
  if [[ "$ROLLING_RESUME_RUN_ID" != "0" ]]; then
    prior_updated_count="$(jq -er '.updated_count' "$resume_path")"
    test "$live_updated_count" -ge "$prior_updated_count"
    test "$live_updated_count" -le "$((prior_updated_count + 1))"
    jq -e \
      --argjson prior_count "$prior_updated_count" \
      --slurpfile current artifacts/rolling-validators.json '
        .validators as $previous
        | all(
            range(0; $prior_count);
            $previous[.] as $before
            | $current[0][.] as $after
            | $before.validator_id == $after.validator_id and
              $before.instance_id == $after.instance_id and
              $before.ami_id == $after.ami_id and
              $before.runtime_version == $after.runtime_version and
              $after.head_height >= $before.head_height and
              (
                $after.head_height > $before.head_height or
                (
                  $after.head_hash == $before.head_hash and
                  $after.certificate_hash == $before.certificate_hash
                )
              )
          )
      ' "$resume_path" >/dev/null
  fi
  expected_replacements="$(
    jq -cn --argjson prefix "$live_updated_count" '
      [range($prefix; 3) | "aws_instance.validator[\(.)]"]
    '
  )"
  jq -ne \
    --argjson expected "$expected_replacements" \
    --args \
    '$ARGS.positional == $expected' \
    "${validator_replacements[@]}" >/dev/null
  if (( live_updated_count < 3 )); then
    expected_next="validator-0$((live_updated_count + 1))"
    jq -e --arg expected_next "$expected_next" '
      .state == "READY_FOR_NEXT_VALIDATOR" and
      .next_validator == $expected_next
    ' artifacts/rolling-compatibility-decision.json >/dev/null
  else
    jq -e '
      .state == "READY_FOR_SLOT_EPOCH" and .next_validator == null
    ' artifacts/rolling-compatibility-decision.json >/dev/null
  fi
fi

apply_executed=false
if [[ "$phase" == "foundation-apply" ]]; then
  if (( ${#validator_replacements[@]} > 0 )); then
    # Rotate one validator at a time. Fixed private IPs require destroy-before-
    # create; SSM Online readback prevents advancing before the replacement is
    # manageable. Other resources remain untouched during each targeted step.
    for address in "${validator_replacements[@]}"; do
      state_volume_id=""
      index="${address##*[}"
      index="${index%]}"
      target_plan="$GITHUB_WORKSPACE/artifacts/foundation-validator-${index}.tfplan"
      target_json="artifacts/foundation-validator-${index}-plan.json"
      target_args=(-target="$address")
      expected_addresses=("$address")
      if [[ "$public_services_enabled" == "true" ]]; then
        rpc_attachment="aws_lb_target_group_attachment.rpc[${index}]"
        explorer_attachment="aws_lb_target_group_attachment.explorer[${index}]"
        target_args+=(
          -target="$rpc_attachment"
          -target="$explorer_attachment"
        )
        expected_addresses+=("$rpc_attachment" "$explorer_attachment")
      fi
      if [[ "$validator_state_enabled" == "true" ]]; then
        state_attachment="aws_volume_attachment.validator_state[${index}]"
        target_args+=(-target="$state_attachment")
        expected_addresses+=("$state_attachment")
      fi
      expected_addresses_json="$(
        printf '%s\n' "${expected_addresses[@]}" | jq -Rsc 'split("\n")[:-1]'
      )"

      terraform -chdir=infra/aws/public-testnet plan -input=false \
        -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
        "${target_args[@]}" \
        -out="$target_plan"
      terraform -chdir=infra/aws/public-testnet show -json "$target_plan" \
        > "$target_json"
      jq -e \
        --slurpfile full_plan artifacts/foundation-plan.json \
        --arg address "$address" \
        --arg node_ami_id "$NODE_AMI_ID" \
        --arg root_ebs_kms_key_arn "$root_ebs_kms_key_arn" \
        --argjson expected_addresses "$expected_addresses_json" \
        --argjson validator_state_enabled "$validator_state_enabled" \
        --argjson validator_state_volume_ids "$validator_state_volume_ids" \
        --argjson validator_state_kms_key_arns \
          "$validator_state_kms_key_arns" \
        --argjson validator_state_rollback_snapshot_ids \
          "$validator_state_rollback_snapshot_ids" \
        --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
        --argjson expected_user_data_sha1 "$expected_user_data_sha1" '
        # BEGIN_ROLLING_TARGET_PLAN_GATE
        def validator_index:
          .address |
            capture("^aws_instance\\.validator\\[(?<index>[0-2])\\]$").index |
            tonumber;

        def retained_state_drift(
          $volume_ids;
          $state_kms;
          $rollback_snapshot_ids;
          $zones
        ):
          validator_index as $index
          | .mode == "managed" and
            .type == "aws_instance" and
            .name == "validator" and
            .index == $index and
            .change.actions == ["update"] and
            (.change.replace_paths // []) == [] and
            .change.before.ebs_block_device == [] and
            (
              (.change.before |
                del(.ebs_block_device, .root_block_device[0].tags)) ==
              (.change.after |
                del(.ebs_block_device, .root_block_device[0].tags))
            ) and
            (
              .change.before.root_block_device[0].tags == null or
              .change.before.root_block_device[0].tags == {}
            ) and
            .change.after.root_block_device[0].tags == {} and
            ([.change.after_unknown | .. | select(. == true)] | length) == 0 and
            (.change.after.ebs_block_device | length) == 1 and
            (
              .change.after.ebs_block_device[0] as $volume
              | $volume.delete_on_termination == false and
                $volume.device_name == "/dev/sdf" and
                $volume.encrypted == true and
                $volume.iops == 6000 and
                $volume.kms_key_id == $state_kms[$index] and
                $volume.snapshot_id == "" and
                $volume.throughput == 250 and
                $volume.volume_id == $volume_ids[$index] and
                $volume.volume_size == 200 and
                $volume.volume_type == "gp3" and
                $volume.tags == $volume.tags_all and
                ($volume.tags | keys) == [
                  "AssetsMoved",
                  "BridgeActivated",
                  "FailureDomain",
                  "Governance",
                  "JuncaFilesystemVerified",
                  "JuncaFinalityCertificateBackfilled",
                  "JuncaMigrationState",
                  "JuncaRollbackSnapshotId",
                  "JuncaStateStoreIntegrity",
                  "MainnetChanged",
                  "ManagedBy",
                  "MigrationRequired",
                  "MonetaryUse",
                  "Name",
                  "Network",
                  "Project",
                  "PublicTestnetOnly",
                  "StatePath",
                  "Validator"
                ] and
                $volume.tags.AssetsMoved == "false" and
                $volume.tags.BridgeActivated == "false" and
                $volume.tags.FailureDomain == $zones[$index] and
                $volume.tags.Governance ==
                  "JAIOS Institutional Governance" and
                $volume.tags.JuncaFilesystemVerified == "true" and
                $volume.tags.JuncaFinalityCertificateBackfilled == "true" and
                $volume.tags.JuncaMigrationState == "VERIFIED_PASS" and
                $volume.tags.JuncaRollbackSnapshotId ==
                  $rollback_snapshot_ids[$index] and
                $volume.tags.JuncaStateStoreIntegrity == "true" and
                $volume.tags.MainnetChanged == "false" and
                $volume.tags.ManagedBy == "Terraform" and
                $volume.tags.MigrationRequired == "false" and
                $volume.tags.MonetaryUse == "None" and
                $volume.tags.Name == (
                  "junca-social-ecosystem-chain-testnet-validator-0" +
                  (($index + 1) | tostring) + "-state"
                ) and
                $volume.tags.Network == "Public Testnet" and
                $volume.tags.Project == "JUNCA Social Ecosystem Chain" and
                $volume.tags.PublicTestnetOnly == "true" and
                $volume.tags.StatePath == "/var/lib/junca" and
                $volume.tags.Validator == ("0" + (($index + 1) | tostring))
            );

        . as $plan
        |
        [
          .resource_changes[]?
          | select(
              .mode == "managed" and
              .change.actions != ["no-op"]
            )
        ] as $changes
        | [($plan.resource_drift // [])[]?] as $drift
        | ($address |
            capture("\\[(?<index>[0-2])\\]$").index |
            tonumber) as $target_index
        | (
            if $validator_state_enabled then
              ["aws_instance.validator[\($target_index)]"]
            else
              []
            end
          ) as $expected_drift_addresses
        | $plan.format_version == "1.2" and
          $plan.terraform_version == "1.9.8" and
          $plan.complete == false and
          $plan.applyable == true and
          $plan.errored == false and
          (($plan.deferred_changes // []) | length) == 0 and
          ($full_plan | length) == 1 and
          $plan.variables == $full_plan[0].variables and
          $plan.configuration == $full_plan[0].configuration and
          ($drift | length) <= ($expected_drift_addresses | length) and
          ([ $drift[].address ] | unique | length) == ($drift | length) and
          all(
            $drift[];
            .address as $drift_address |
            ($expected_drift_addresses | index($drift_address)) != null
          ) and
          all(
            $drift[];
            retained_state_drift(
              $validator_state_volume_ids;
              $validator_state_kms_key_arns;
              $validator_state_rollback_snapshot_ids;
              $availability_zones
            )
          ) and
          all(
            $plan.resource_changes[]?;
            if .mode == "managed" then
              true
            elif .mode == "data" then
              (.change.actions == ["read"] or .change.actions == ["no-op"])
            else
              false
            end
          ) and
          ($changes | length) == ($expected_addresses | length) and
          ([ $changes[].address ] | sort) == ($expected_addresses | sort) and
          ([ $changes[].address ] | unique | length) == ($changes | length) and
          all(
            $changes[];
            .change.actions == ["delete", "create"] and
            (
              if .address == $address then
                .change.replace_paths == [["ami"], ["user_data"]] and
                .change.after.ami == $node_ami_id and
                .change.after.private_ip ==
                  ["10.67.16.10", "10.67.32.10", "10.67.48.10"][
                    (.address |
                      capture("\\[(?<index>[0-2])\\]$").index |
                      tonumber)
                  ] and
                .change.after.associate_public_ip_address == false and
                .change.after.instance_type == "m7i.large" and
                .change.after.iam_instance_profile ==
                  ("junca-social-ecosystem-chain-testnet-validator-" +
                    (((.address |
                      capture("\\[(?<index>[0-2])\\]$").index |
                      tonumber) + 1) | tostring)) and
                .change.before.iam_instance_profile ==
                  .change.after.iam_instance_profile and
                .change.before.subnet_id == .change.after.subnet_id and
                (.change.after.subnet_id |
                  test("^subnet-[0-9a-f]{8,17}$")) and
                .change.before.vpc_security_group_ids ==
                  .change.after.vpc_security_group_ids and
                (.change.after.vpc_security_group_ids | length) == 1 and
                (.change.after.vpc_security_group_ids[0] |
                  test("^sg-[0-9a-f]{8,17}$")) and
                .change.before.tags_all == .change.after.tags_all and
                .change.after.tags_all.Project ==
                  "JUNCA Social Ecosystem Chain" and
                .change.after.tags_all.Governance ==
                  "JAIOS Institutional Governance" and
                .change.after.tags_all.Network == "Public Testnet" and
                .change.after.tags_all.MonetaryUse == "None" and
                .change.after.tags_all.ManagedBy == "Terraform" and
                .change.after.monitoring == true and
                (.change.before.user_data |
                  test("^[0-9a-f]{40}$")) and
                .change.after.user_data ==
                  $expected_user_data_sha1[$target_index] and
                (.change.after_unknown.user_data // false) == false and
                .change.after.user_data_replace_on_change == true and
                .change.after.source_dest_check == true and
                .change.after.metadata_options[0].http_endpoint == "enabled" and
                .change.after.metadata_options[0].http_tokens == "required" and
                .change.after.root_block_device[0].encrypted == true and
                .change.after.root_block_device[0].delete_on_termination ==
                  true and
                .change.before.root_block_device[0].kms_key_id ==
                  $root_ebs_kms_key_arn and
                .change.after.root_block_device[0].kms_key_id == null and
                .change.after_unknown.root_block_device[0].kms_key_id ==
                  true and
                .change.after.root_block_device[0].volume_type == "gp3" and
                .change.after.root_block_device[0].volume_size == 200 and
                .change.after.root_block_device[0].iops == 6000 and
                .change.after.root_block_device[0].throughput == 250
              elif (.address |
                test("^aws_lb_target_group_attachment\\.rpc\\[[0-2]\\]$"))
              then
                .change.replace_paths == [["target_id"]] and
                .change.after.port == 8546 and
                .change.before.target_group_arn ==
                  .change.after.target_group_arn and
                .change.after_unknown.target_id == true
              elif (.address |
                test("^aws_lb_target_group_attachment\\.explorer\\[[0-2]\\]$"))
              then
                .change.replace_paths == [["target_id"]] and
                .change.after.port == 3000 and
                .change.before.target_group_arn ==
                  .change.after.target_group_arn and
                .change.after_unknown.target_id == true
              elif (.address |
                test("^aws_volume_attachment\\.validator_state\\[[0-2]\\]$"))
              then
                .change.replace_paths == [["instance_id"]] and
                .change.after.device_name == "/dev/sdf" and
                .change.after.volume_id == .change.before.volume_id and
                .change.after.force_detach == false and
                .change.after.stop_instance_before_detaching == true and
                .change.after_unknown.instance_id == true
              else
                false
              end
            )
          )
        # END_ROLLING_TARGET_PLAN_GATE
      ' "$target_json" >/dev/null

      # Fail before replacement when the future epoch no longer leaves a
      # bounded boot/SSM quiesce window.
      test "$((validator_slot_epoch_seconds - $(date +%s)))" -ge 900
      write_post_apply_checkpoint "$index" terraform-apply started
      if ! terraform -chdir=infra/aws/public-testnet apply \
        -input=false -auto-approve "$target_plan"
      then
        write_post_apply_checkpoint "$index" terraform-apply failed
        exit 1
      fi
      write_post_apply_checkpoint "$index" terraform-apply succeeded

      write_post_apply_checkpoint "$index" instance-output started
      if ! terraform -chdir=infra/aws/public-testnet output -json \
        validator_instance_ids \
        >"artifacts/post-apply-validator-${index}-instances.json"
      then
        write_post_apply_checkpoint "$index" instance-output failed
        exit 1
      fi
      if ! new_instance="$(
        jq -er ".[${index}] | select(test(\"^i-[0-9a-f]{8,17}$\"))" \
          "artifacts/post-apply-validator-${index}-instances.json"
      )"; then
        write_post_apply_checkpoint "$index" instance-output failed
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" instance-output succeeded "$new_instance"

      write_post_apply_checkpoint \
        "$index" root-volume started "$new_instance"
      if ! aws ec2 describe-instances \
        --region "$AWS_REGION" \
        --instance-ids "$new_instance" \
        >"artifacts/post-apply-validator-${index}-root-instance.json"
      then
        write_post_apply_checkpoint \
          "$index" root-volume failed "$new_instance"
        exit 1
      fi
      if ! readarray -t root_volume_binding < <(
        jq -er \
          --arg image_id "$NODE_AMI_ID" \
          --arg instance_id "$new_instance" \
          --argjson index "$index" '
            [
              .Reservations[].Instances[]
              | select(
                  .InstanceId == $instance_id and
                  .ImageId == $image_id and
                  .State.Name == "running" and
                  .PrivateIpAddress ==
                    ["10.67.16.10", "10.67.32.10", "10.67.48.10"][$index] and
                  (.PublicIpAddress // null) == null and
                  (.RootDeviceName | type == "string" and length > 0)
                )
            ]
            | select(length == 1)
            | .[0] as $instance
            | [
                $instance.BlockDeviceMappings[]
                | select(
                    .DeviceName == $instance.RootDeviceName and
                    .Ebs.Status == "attached" and
                    .Ebs.DeleteOnTermination == true and
                    (.Ebs.VolumeId |
                      test("^vol-[0-9a-f]{8,17}$"))
                  )
                | [$instance.RootDeviceName, .Ebs.VolumeId]
              ]
            | select(length == 1)
            | .[0][]
          ' "artifacts/post-apply-validator-${index}-root-instance.json"
      ); then
        write_post_apply_checkpoint \
          "$index" root-volume failed "$new_instance"
        exit 1
      fi
      if [[ "${#root_volume_binding[@]}" != 2 ]]; then
        write_post_apply_checkpoint \
          "$index" root-volume failed "$new_instance"
        exit 1
      fi
      candidate_root_device_name="${root_volume_binding[0]}"
      candidate_root_volume_id="${root_volume_binding[1]}"
      if ! aws ec2 describe-volumes \
        --region "$AWS_REGION" \
        --volume-ids "$candidate_root_volume_id" \
        >"artifacts/post-apply-validator-${index}-root-volume.json"
      then
        write_post_apply_checkpoint \
          "$index" root-volume failed "$new_instance"
        exit 1
      fi
      if ! jq -e \
        --arg device "$candidate_root_device_name" \
        --arg instance_id "$new_instance" \
        --arg kms_key_arn "$root_ebs_kms_key_arn" \
        --arg volume_id "$candidate_root_volume_id" '
          .Volumes
          | select(length == 1)
          | .[0]
          | .VolumeId == $volume_id and
            .Encrypted == true and
            .KmsKeyId == $kms_key_arn and
            .State == "in-use" and
            .Size == 200 and
            .VolumeType == "gp3" and
            .Iops == 6000 and
            .Throughput == 250 and
            (.Attachments | length) == 1 and
            .Attachments[0].InstanceId == $instance_id and
            .Attachments[0].Device == $device and
            .Attachments[0].State == "attached" and
            (
              .Tags | from_entries
            ).Project == "JUNCA Social Ecosystem Chain" and
            (
              .Tags | from_entries
            ).Governance == "JAIOS Institutional Governance" and
            (.Tags | from_entries).Network == "Public Testnet" and
            (.Tags | from_entries).MonetaryUse == "None" and
            (.Tags | from_entries).ManagedBy == "Terraform"
        ' "artifacts/post-apply-validator-${index}-root-volume.json" \
        >/dev/null
      then
        write_post_apply_checkpoint \
          "$index" root-volume failed "$new_instance" \
          "$candidate_root_volume_id"
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" root-volume succeeded "$new_instance" \
        "$candidate_root_volume_id"

      write_post_apply_checkpoint \
        "$index" ssm-online started "$new_instance"
      if ! wait_for_ssm_online \
        "$new_instance" \
        "artifacts/post-apply-validator-${index}-ssm-online.json"
      then
        write_post_apply_checkpoint \
          "$index" ssm-online failed "$new_instance"
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" ssm-online succeeded "$new_instance"

      if [[ "$validator_state_enabled" == "true" ]]; then
        write_post_apply_checkpoint \
          "$index" state-volume started "$new_instance"
        if ! terraform -chdir=infra/aws/public-testnet output -json \
          validator_state_volume_readback \
          >"artifacts/post-apply-validator-${index}-state-outputs.json"
        then
          write_post_apply_checkpoint \
            "$index" state-volume failed "$new_instance"
          exit 1
        fi
        if ! state_volume_id="$(
          jq -er \
            ".[${index}].volume_id |
              select(test(\"^vol-[0-9a-f]{8,17}$\"))" \
            "artifacts/post-apply-validator-${index}-state-outputs.json"
        )"; then
          write_post_apply_checkpoint \
            "$index" state-volume failed "$new_instance"
          exit 1
        fi
        if ! aws ec2 describe-volumes --volume-ids "$state_volume_id" \
          --output json \
          >"artifacts/post-apply-validator-${index}-volume.json"
        then
          write_post_apply_checkpoint \
            "$index" state-volume failed "$new_instance" "$state_volume_id"
          exit 1
        fi
        if ! jq -e --arg instance_id "$new_instance" '
            .Volumes | length == 1 and
            .[0].Encrypted == true and
            .[0].State == "in-use" and
            (.[0].Attachments | length) == 1 and
            .[0].Attachments[0].InstanceId == $instance_id and
            .[0].Attachments[0].State == "attached"
          ' "artifacts/post-apply-validator-${index}-volume.json" >/dev/null
        then
          write_post_apply_checkpoint \
            "$index" state-volume failed "$new_instance" "$state_volume_id"
          exit 1
        fi
        write_post_apply_checkpoint \
          "$index" state-volume succeeded "$new_instance" "$state_volume_id"
      fi

      write_post_apply_checkpoint \
        "$index" runtime-readiness started "$new_instance" \
        "${state_volume_id:-}"
      if ! verify_validator_bootstrap_readiness \
        "validator-0$((index + 1))" \
        "$new_instance" \
        "artifacts/post-apply-validator-${index}-runtime-readiness.json"
      then
        write_post_apply_checkpoint \
          "$index" runtime-readiness failed "$new_instance" \
          "${state_volume_id:-}"
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" runtime-readiness succeeded "$new_instance" \
        "${state_volume_id:-}"

      # A replacement boots with the Terraform-bound future epoch. Quiesce it
      # only after cloud-init, service, immutable artifacts, retained state and
      # durable finalized certificate are read back. The epoch is still in the
      # future, so no automatic-finality slot can execute during this bounded
      # transition.
      write_post_apply_checkpoint \
        "$index" finality-quiesce started "$new_instance" \
        "${state_volume_id:-}"
      if ! test "$validator_slot_epoch_seconds" -gt "$(date +%s)"; then
        write_post_apply_checkpoint \
          "$index" finality-quiesce failed "$new_instance" \
          "${state_volume_id:-}"
        exit 1
      fi
      if ! new_instance_finality_bindings="$(
        build_runtime_finality_bindings \
          "$NODE_ARTIFACT_SHA256" false \
          "[\"validator-0$((index + 1))\"]" "$new_instance"
      )"; then
        write_post_apply_checkpoint \
          "$index" finality-quiesce failed "$new_instance" \
          "${state_volume_id:-}"
        exit 1
      fi
      if ! set_runtime_finality \
        0 0 "$new_instance_finality_bindings"
      then
        write_post_apply_checkpoint \
          "$index" finality-quiesce failed "$new_instance" \
          "${state_volume_id:-}"
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" finality-quiesce succeeded "$new_instance" \
        "${state_volume_id:-}"

      if [[ "$public_services_enabled" == "true" ]]; then
        current_outputs="$(
          terraform -chdir=infra/aws/public-testnet output -json
        )"
        for target_group in \
          "$(jq -er '.public_target_group_arns.value.rpc' <<<"$current_outputs")" \
          "$(jq -er '.public_target_group_arns.value.explorer' <<<"$current_outputs")"
        do
          aws elbv2 wait target-in-service \
            --target-group-arn "$target_group" \
            --targets "Id=${new_instance}"
        done
      fi

      updated_count="$((index + 1))"
      if (( updated_count < 3 )); then
        next_validator="validator-0$((updated_count + 1))"
        write_rolling_compatibility_evidence \
          READY_FOR_NEXT_VALIDATOR "$next_validator"
      else
        write_rolling_compatibility_evidence READY_FOR_SLOT_EPOCH
      fi
    done

    # Reconcile non-destructive dependants (for example CloudWatch alarm
    # instance IDs) only after every validator replacement is SSM-managed.
    reconcile_validator_ids="$(
      terraform -chdir=infra/aws/public-testnet output -json \
        validator_instance_ids
    )"
    jq -e '
      type == "array" and length == 3 and
      (unique | length) == 3 and
      all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
    ' <<<"$reconcile_validator_ids" >/dev/null
    terraform -chdir=infra/aws/public-testnet plan -input=false \
      -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
      -out="$GITHUB_WORKSPACE/artifacts/foundation-reconcile.tfplan"
    terraform -chdir=infra/aws/public-testnet show -json \
      "$GITHUB_WORKSPACE/artifacts/foundation-reconcile.tfplan" \
      > artifacts/foundation-reconcile-plan.json
    jq -e \
      --arg root_ebs_kms_key_arn "$root_ebs_kms_key_arn" \
      --argjson validator_ids "$reconcile_validator_ids" \
      --argjson validator_state_enabled "$validator_state_enabled" \
      --argjson validator_state_volume_ids "$validator_state_volume_ids" \
      --argjson validator_state_kms_key_arns \
        "$validator_state_kms_key_arns" \
      --argjson validator_state_rollback_snapshot_ids \
        "$validator_state_rollback_snapshot_ids" \
      --argjson availability_zones "$AVAILABILITY_ZONES_JSON" '
      # BEGIN_ROLLING_RECONCILE_PLAN_GATE
      def validator_index:
        .address |
          capture("^aws_instance\\.validator\\[(?<index>[0-2])\\]$").index |
          tonumber;

      def retained_state_drift(
        $volume_ids;
        $state_kms;
        $rollback_snapshot_ids;
        $zones
      ):
        validator_index as $index
        | .mode == "managed" and
          .type == "aws_instance" and
          .name == "validator" and
          .index == $index and
          .change.actions == ["update"] and
          (.change.replace_paths // []) == [] and
          .change.before.ebs_block_device == [] and
          (
            (.change.before |
              del(.ebs_block_device, .root_block_device[0].tags)) ==
            (.change.after |
              del(.ebs_block_device, .root_block_device[0].tags))
          ) and
          (
            .change.before.root_block_device[0].tags == null or
            .change.before.root_block_device[0].tags == {}
          ) and
          .change.after.root_block_device[0].tags == {} and
          ([.change.after_unknown | .. | select(. == true)] | length) == 0 and
          (.change.after.ebs_block_device | length) == 1 and
          (
            .change.after.ebs_block_device[0] as $volume
            | $volume.delete_on_termination == false and
              $volume.device_name == "/dev/sdf" and
              $volume.encrypted == true and
              $volume.iops == 6000 and
              $volume.kms_key_id == $state_kms[$index] and
              $volume.snapshot_id == "" and
              $volume.throughput == 250 and
              $volume.volume_id == $volume_ids[$index] and
              $volume.volume_size == 200 and
              $volume.volume_type == "gp3" and
              $volume.tags == $volume.tags_all and
              ($volume.tags | keys) == [
                "AssetsMoved",
                "BridgeActivated",
                "FailureDomain",
                "Governance",
                "JuncaFilesystemVerified",
                "JuncaFinalityCertificateBackfilled",
                "JuncaMigrationState",
                "JuncaRollbackSnapshotId",
                "JuncaStateStoreIntegrity",
                "MainnetChanged",
                "ManagedBy",
                "MigrationRequired",
                "MonetaryUse",
                "Name",
                "Network",
                "Project",
                "PublicTestnetOnly",
                "StatePath",
                "Validator"
              ] and
              $volume.tags.AssetsMoved == "false" and
              $volume.tags.BridgeActivated == "false" and
              $volume.tags.FailureDomain == $zones[$index] and
              $volume.tags.Governance ==
                "JAIOS Institutional Governance" and
              $volume.tags.JuncaFilesystemVerified == "true" and
              $volume.tags.JuncaFinalityCertificateBackfilled == "true" and
              $volume.tags.JuncaMigrationState == "VERIFIED_PASS" and
              $volume.tags.JuncaRollbackSnapshotId ==
                $rollback_snapshot_ids[$index] and
              $volume.tags.JuncaStateStoreIntegrity == "true" and
              $volume.tags.MainnetChanged == "false" and
              $volume.tags.ManagedBy == "Terraform" and
              $volume.tags.MigrationRequired == "false" and
              $volume.tags.MonetaryUse == "None" and
              $volume.tags.Name == (
                "junca-social-ecosystem-chain-testnet-validator-0" +
                (($index + 1) | tostring) + "-state"
              ) and
              $volume.tags.Network == "Public Testnet" and
              $volume.tags.Project == "JUNCA Social Ecosystem Chain" and
              $volume.tags.PublicTestnetOnly == "true" and
              $volume.tags.StatePath == "/var/lib/junca" and
              $volume.tags.Validator == ("0" + (($index + 1) | tostring))
          );

      . as $plan
      | [
          .resource_changes[]?
          | select(
              .mode == "managed" and
              .change.actions != ["no-op"]
            )
        ] as $changes
      | [($plan.resource_drift // [])[]?] as $drift
      | (
          if $validator_state_enabled then [0, 1, 2] else [] end
        ) as $expected_drift_indices
      | [
          $expected_drift_indices[] |
          "aws_instance.validator[\(.)]"
        ] as $expected_drift_addresses
      | $plan.format_version == "1.2" and
        $plan.terraform_version == "1.9.8" and
        $plan.complete == true and
        $plan.errored == false and
        (($plan.deferred_changes // []) | length) == 0 and
        (($changes | length) == 0 or $plan.applyable == true) and
        ($drift | length) <= ($expected_drift_addresses | length) and
        ([ $drift[].address ] | unique | length) == ($drift | length) and
        all(
          $drift[];
          .address as $drift_address |
          ($expected_drift_addresses | index($drift_address)) != null
        ) and
        all(
          $drift[];
          retained_state_drift(
            $validator_state_volume_ids;
            $validator_state_kms_key_arns;
            $validator_state_rollback_snapshot_ids;
            $availability_zones
          )
        ) and
        ([ $changes[].address ] | unique | length) == ($changes | length) and
        all(
          $plan.resource_changes[]?;
          if .mode == "managed" then
            true
          elif .mode == "data" then
            (.change.actions == ["read"] or .change.actions == ["no-op"])
          else
            false
          end
        ) and
        all(
          $changes[];
          (.address |
            capture("^aws_cloudwatch_metric_alarm\\.validator_status\\[(?<index>[0-2])\\]$").index |
            tonumber) as $index
          |
          .change.actions == ["update"] and
          (.change.replace_paths // []) == [] and
          ((.change.before | del(.dimensions)) ==
            (.change.after | del(.dimensions))) and
          (.change.after.dimensions ==
            {"InstanceId": $validator_ids[$index]}) and
          ([.change.after_unknown | .. | select(. == true)] | length) == 0
        )
      # END_ROLLING_RECONCILE_PLAN_GATE
    ' \
      artifacts/foundation-reconcile-plan.json >/dev/null
    terraform -chdir=infra/aws/public-testnet apply -input=false -auto-approve \
      "$GITHUB_WORKSPACE/artifacts/foundation-reconcile.tfplan"
  else
    terraform -chdir=infra/aws/public-testnet apply -input=false -auto-approve \
      "$GITHUB_WORKSPACE/artifacts/foundation.tfplan"
  fi

  if [[ "$rolling_release" == "true" ]]; then
    # Activation is a separate phase after every validator has the exact target
    # runtime, SSM/service health, durable mount, SQLite integrity and matching
    # finalized head/certificate. This also completes an evidence-bound resume
    # whose strict live prefix was already 3/3 when the rerun began.
    mapfile -t activated_instances < <(
      terraform -chdir=infra/aws/public-testnet output -json \
        validator_instance_ids |
        jq -er '.[]'
    )
    test "${#activated_instances[@]}" = 3
    activated_finality_bindings="$(
      build_runtime_finality_bindings \
        "$NODE_ARTIFACT_SHA256" false \
        '["validator-01","validator-02","validator-03"]' \
        "${activated_instances[@]}"
    )"
    write_rolling_compatibility_evidence READY_FOR_FINALITY_ENABLE
    activation_dispatch_epoch="$((validator_slot_epoch_seconds - 60))"
    activation_now="$(date +%s)"
    if (( activation_dispatch_epoch > activation_now )); then
      sleep "$((activation_dispatch_epoch - activation_now))"
    fi
    activation_remaining="$((validator_slot_epoch_seconds - $(date +%s)))"
    test "$activation_remaining" -gt 0
    test "$activation_remaining" -le 60
    set_runtime_finality \
      30 "$validator_slot_epoch_seconds" "$activated_finality_bindings"
    write_rolling_compatibility_evidence ACCEPTED
  fi

  apply_executed=true
  terraform -chdir=infra/aws/public-testnet output -json > artifacts/foundation-outputs.json
  jq -e --argjson public_services_enabled "$public_services_enabled" '
    (.validator_instance_ids.value | length) == 3 and
    .deployment_stage.value == (
      if $public_services_enabled then "public-services" else "validators-only" end
    ) and
    (
      if $public_services_enabled then
        .public_rpc_url.value == "https://rpc.jaios-governance.org" and
        .explorer_url.value == "https://explorer.jaios-governance.org" and
        .health_url.value == "https://health.jaios-governance.org"
      else
        .public_rpc_url.value == null and
        .explorer_url.value == null and
        .health_url.value == null
      end
    ) and
    .runtime_boundary.value.governance == "JAIOS Institutional Governance" and
    .runtime_boundary.value.mainnet_changed == false and
    .runtime_boundary.value.assets_moved == false and
    .runtime_boundary.value.bridge_activated == false and
    .automatic_finality_readback.value.enabled == true and
    .automatic_finality_readback.value.block_interval_seconds == 30 and
    (.automatic_finality_readback.value.slot_epoch_seconds | type) == "number" and
    .automatic_finality_readback.value.slot_epoch_seconds > 0 and
    .automatic_finality_readback.value.slot_epoch_seconds % 30 == 0
  ' artifacts/foundation-outputs.json >/dev/null
fi

jq -n \
  --arg phase "$phase" \
  --arg account_id "$AWS_ACCOUNT_ID" \
  --arg region "$AWS_REGION" \
  --arg role_arn "$DEPLOYMENT_ROLE_ARN" \
  --arg source_commit "$SOURCE_COMMIT" \
  --arg node_ami_id "$NODE_AMI_ID" \
  --argjson apply_executed "$apply_executed" \
  --argjson public_services_enabled "$public_services_enabled" \
  '{
    schema_version: "1.0",
    chain_name: "JUNCA Social Ecosystem Chain",
    governance: "JAIOS Institutional Governance",
    notice: "Public Testnet / No Monetary Value",
    phase: $phase,
    account_id: $account_id,
    region: $region,
    deployment_role_arn: $role_arn,
    source_commit: $source_commit,
    node_ami_id: $node_ami_id,
    deployment_stage: (
      if $public_services_enabled then "public-services" else "validators-only" end
    ),
    apply_executed: $apply_executed,
    quorum_verified: false,
    public_services_enabled: $public_services_enabled,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false
  }' > artifacts/foundation-execution-evidence.json
