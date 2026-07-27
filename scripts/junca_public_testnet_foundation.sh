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

wait_for_ssm_command() {
  local command_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local status=""
  for attempt in $(seq 1 90); do
    status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query Status \
        --output text
    )"
    case "$status" in
      Success) break ;;
      Failed|Cancelled|TimedOut|Cancelling)
        break
        ;;
    esac
    test "$attempt" -lt 90
    sleep 2
  done
  aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$instance_id" >"$output_path"
  jq -e '.Status == "Success"' "$output_path" >/dev/null
}

wait_for_ssm_command_result() {
  local command_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local status=""
  for attempt in $(seq 1 90); do
    status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query Status \
        --output text
    )"
    case "$status" in
      Success|Failed|Cancelled|TimedOut|Cancelling) break ;;
    esac
    if [[ "$attempt" == 90 ]]; then
      status=TimedOut
      break
    fi
    sleep 2
  done
  aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$instance_id" >"$output_path"
}

render_runtime_finality_preflight() {
  local finality_enabled="$1"
  local block_interval="$2"
  local slot_epoch="$3"
  local expected_artifact_sha256="$4"
  local allow_missing_finality_keys="$5"
  cat <<EOF
set -euo pipefail
# BEGIN_FINALITY_REMOTE_PREFLIGHT
test -f /etc/junca/runtime.env
test ! -L /etc/junca/runtime.env
test "\$(awk '/^NODE_ARTIFACT_SHA256=/{count++} END{print count+0}' /etc/junca/runtime.env)" = 1
grep -Fxq 'NODE_ARTIFACT_SHA256=${expected_artifact_sha256}' /etc/junca/runtime.env
automatic_finality_count="\$(awk '/^AUTOMATIC_FINALITY_ENABLED=/{count++} END{print count+0}' /etc/junca/runtime.env)"
block_interval_count="\$(awk '/^TESTNET_BLOCK_INTERVAL_SECONDS=/{count++} END{print count+0}' /etc/junca/runtime.env)"
slot_epoch_count="\$(awk '/^TESTNET_SLOT_EPOCH_SECONDS=/{count++} END{print count+0}' /etc/junca/runtime.env)"
if [[ '${allow_missing_finality_keys}' == true ]]; then
  test '${finality_enabled}' = false
  test '${block_interval}' = 0
  test '${slot_epoch}' = 0
  if [[ "\$automatic_finality_count" == 0 &&
        "\$block_interval_count" == 0 &&
        "\$slot_epoch_count" == 0 ]]; then
    :
  else
    test "\$automatic_finality_count" = 1
    test "\$block_interval_count" = 1
    test "\$slot_epoch_count" = 1
  fi
else
  test "\$automatic_finality_count" = 1
  test "\$block_interval_count" = 1
  test "\$slot_epoch_count" = 1
fi
sha256sum /etc/junca/runtime.env
# END_FINALITY_REMOTE_PREFLIGHT
EOF
}

render_runtime_finality_mutation() {
  local finality_enabled="$1"
  local block_interval="$2"
  local slot_epoch="$3"
  local expected_artifact_sha256="$4"
  local allow_missing_finality_keys="$5"
  cat <<EOF
set -euo pipefail
# BEGIN_FINALITY_REMOTE_MUTATION
runtime_env=/etc/junca/runtime.env
test -f "\$runtime_env"
test ! -L "\$runtime_env"
test "\$(awk '/^NODE_ARTIFACT_SHA256=/{count++} END{print count+0}' "\$runtime_env")" = 1
grep -Fxq 'NODE_ARTIFACT_SHA256=${expected_artifact_sha256}' "\$runtime_env"
automatic_finality_count="\$(awk '/^AUTOMATIC_FINALITY_ENABLED=/{count++} END{print count+0}' "\$runtime_env")"
block_interval_count="\$(awk '/^TESTNET_BLOCK_INTERVAL_SECONDS=/{count++} END{print count+0}' "\$runtime_env")"
slot_epoch_count="\$(awk '/^TESTNET_SLOT_EPOCH_SECONDS=/{count++} END{print count+0}' "\$runtime_env")"
if [[ '${allow_missing_finality_keys}' == true ]]; then
  test '${finality_enabled}' = false
  test '${block_interval}' = 0
  test '${slot_epoch}' = 0
  if [[ "\$automatic_finality_count" == 0 &&
        "\$block_interval_count" == 0 &&
        "\$slot_epoch_count" == 0 ]]; then
    initialize_finality_keys=true
  else
    test "\$automatic_finality_count" = 1
    test "\$block_interval_count" = 1
    test "\$slot_epoch_count" = 1
    initialize_finality_keys=false
  fi
else
  test "\$automatic_finality_count" = 1
  test "\$block_interval_count" = 1
  test "\$slot_epoch_count" = 1
  initialize_finality_keys=false
fi
runtime_env_tmp="\$(mktemp /etc/junca/.runtime.env.XXXXXX)"
trap 'rm -f "\$runtime_env_tmp"' EXIT
cp -p "\$runtime_env" "\$runtime_env_tmp"
if [[ "\$initialize_finality_keys" == true ]]; then
  test "\$(tail -c 1 "\$runtime_env" | wc -l)" = 1
  printf '%s\n' \
    'AUTOMATIC_FINALITY_ENABLED=false' \
    'TESTNET_BLOCK_INTERVAL_SECONDS=0' \
    'TESTNET_SLOT_EPOCH_SECONDS=0' >> "\$runtime_env_tmp"
fi
sed -i -E 's/^AUTOMATIC_FINALITY_ENABLED=.*/AUTOMATIC_FINALITY_ENABLED=${finality_enabled}/' "\$runtime_env_tmp"
sed -i -E 's/^TESTNET_BLOCK_INTERVAL_SECONDS=.*/TESTNET_BLOCK_INTERVAL_SECONDS=${block_interval}/' "\$runtime_env_tmp"
sed -i -E 's/^TESTNET_SLOT_EPOCH_SECONDS=.*/TESTNET_SLOT_EPOCH_SECONDS=${slot_epoch}/' "\$runtime_env_tmp"
assert_runtime_finality() {
  local path="\$1"
  test "\$(awk '/^NODE_ARTIFACT_SHA256=/{count++} END{print count+0}' "\$path")" = 1
  grep -Fxq 'NODE_ARTIFACT_SHA256=${expected_artifact_sha256}' "\$path"
  test "\$(awk '/^AUTOMATIC_FINALITY_ENABLED=/{count++} END{print count+0}' "\$path")" = 1
  test "\$(awk '/^TESTNET_BLOCK_INTERVAL_SECONDS=/{count++} END{print count+0}' "\$path")" = 1
  test "\$(awk '/^TESTNET_SLOT_EPOCH_SECONDS=/{count++} END{print count+0}' "\$path")" = 1
  grep -Fxq 'AUTOMATIC_FINALITY_ENABLED=${finality_enabled}' "\$path"
  grep -Fxq 'TESTNET_BLOCK_INTERVAL_SECONDS=${block_interval}' "\$path"
  grep -Fxq 'TESTNET_SLOT_EPOCH_SECONDS=${slot_epoch}' "\$path"
}
assert_runtime_finality "\$runtime_env_tmp"
chown --reference="\$runtime_env" "\$runtime_env_tmp"
chmod --reference="\$runtime_env" "\$runtime_env_tmp"
mv -f "\$runtime_env_tmp" "\$runtime_env"
trap - EXIT
assert_runtime_finality "\$runtime_env"
systemctl restart junca-validator.service
for attempt in \$(seq 1 60); do
  systemctl is-active --quiet junca-validator.service &&
    curl -fsS http://127.0.0.1:8545/health >/dev/null &&
    assert_runtime_finality "\$runtime_env" &&
    exit 0
  sleep 2
done
systemctl status junca-validator.service --no-pager -l || true
journalctl -u junca-validator.service --no-pager -n 100 || true
exit 1
# END_FINALITY_REMOTE_MUTATION
EOF
}

render_runtime_finality_readback() {
  local finality_enabled="$1"
  local block_interval="$2"
  local slot_epoch="$3"
  local expected_artifact_sha256="$4"
  cat <<EOF
set -euo pipefail
systemctl is-active --quiet junca-validator.service
curl -fsS http://127.0.0.1:8545/health >/dev/null
# BEGIN_FINALITY_EXACT_READBACK
test -f /etc/junca/runtime.env
test ! -L /etc/junca/runtime.env
test "\$(awk '/^NODE_ARTIFACT_SHA256=/{count++} END{print count+0}' /etc/junca/runtime.env)" = 1
grep -Fxq 'NODE_ARTIFACT_SHA256=${expected_artifact_sha256}' /etc/junca/runtime.env
test "\$(awk '/^AUTOMATIC_FINALITY_ENABLED=/{count++} END{print count+0}' /etc/junca/runtime.env)" = 1
test "\$(awk '/^TESTNET_BLOCK_INTERVAL_SECONDS=/{count++} END{print count+0}' /etc/junca/runtime.env)" = 1
test "\$(awk '/^TESTNET_SLOT_EPOCH_SECONDS=/{count++} END{print count+0}' /etc/junca/runtime.env)" = 1
grep -Fxq 'AUTOMATIC_FINALITY_ENABLED=${finality_enabled}' /etc/junca/runtime.env
grep -Fxq 'TESTNET_BLOCK_INTERVAL_SECONDS=${block_interval}' /etc/junca/runtime.env
grep -Fxq 'TESTNET_SLOT_EPOCH_SECONDS=${slot_epoch}' /etc/junca/runtime.env
sha256sum /etc/junca/runtime.env
# END_FINALITY_EXACT_READBACK
EOF
}

build_runtime_finality_bindings() {
  local expected_artifact_sha256="$1"
  local allow_missing_finality_keys="$2"
  shift 2
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
  jq -cn \
    --arg expected_artifact_sha256 "$expected_artifact_sha256" \
    --argjson allow_missing_finality_keys "$allow_missing_finality_keys" \
    --argjson instances "$instances_json" '
      [
        $instances[] |
        {
          instance_id: .,
          expected_artifact_sha256: $expected_artifact_sha256,
          allow_missing_finality_keys: $allow_missing_finality_keys
        }
      ]
    '
}

build_pre_rollout_finality_bindings() {
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
    printf '%s\n' "$@" | jq -Rsc 'split("\n")[:-1]'
  )"
  jq -e '
    type == "array" and length == 3 and
    (unique | length) == 3 and
    all(.[]; type == "string" and test("^i-[0-9a-f]{8,17}$"))
  ' <<<"$instances_json" >/dev/null
  jq -cn \
    --argjson updated_count "$updated_count" \
    --arg target_artifact_sha256 "$target_artifact_sha256" \
    --arg previous_artifact_sha256 "$previous_artifact_sha256" \
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

set_runtime_finality() {
  local block_interval="$1"
  local slot_epoch="$2"
  local bindings_json="$3"
  local finality_enabled
  local command
  local command_id
  local instance_id
  local expected_artifact_sha256
  local allow_missing_finality_keys
  local compensation_summary
  local compensation_status
  local readback_status
  local index
  local mutation_failed=false
  local -a instances=()
  local -a mutation_command_ids=()
  [[ "$block_interval" =~ ^(0|30)$ ]]
  [[ "$slot_epoch" =~ ^(0|[1-9][0-9]*)$ ]]
  jq -e '
    type == "array" and length >= 1 and length <= 3 and
    (map(.instance_id) | unique | length) == length and
    all(
      .[];
      (.instance_id | type == "string" and test("^i-[0-9a-f]{8,17}$")) and
      (.expected_artifact_sha256 |
        type == "string" and test("^[0-9a-f]{64}$")) and
      (.allow_missing_finality_keys | type == "boolean")
    )
  ' <<<"$bindings_json" >/dev/null
  mapfile -t instances < <(jq -er '.[].instance_id' <<<"$bindings_json")
  if [[ "$slot_epoch" != "0" ]]; then
    test "$slot_epoch" -gt "$(date +%s)"
    test "$((slot_epoch % 30))" -eq 0
  fi
  if [[ "$block_interval" == "30" ]]; then
    test "$slot_epoch" != "0"
    finality_enabled=true
  else
    finality_enabled=false
  fi

  # Complete every read-only preflight before any runtime.env mutation.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    expected_artifact_sha256="$(
      jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
    )"
    allow_missing_finality_keys="$(
      jq -er ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
    )"
    command="$(
      render_runtime_finality_preflight \
        "$finality_enabled" "$block_interval" "$slot_epoch" \
        "$expected_artifact_sha256" "$allow_missing_finality_keys"
    )"
    jq -n --arg command "$command" '{commands: [$command]}' \
      >"artifacts/ssm-finality-preflight-${index}.json"
    command_id="$(
      aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name AWS-RunShellScript \
        --parameters "file://artifacts/ssm-finality-preflight-${index}.json" \
        --comment "JUNCA Public Testnet finality read-only preflight" \
        --query Command.CommandId \
        --output text
    )"
    wait_for_ssm_command \
      "$command_id" "$instance_id" \
      "artifacts/finality-preflight-${block_interval}-${slot_epoch}-${instance_id}.json"
  done

  # Dispatch every mutation before collecting any result, preventing an early
  # failed invocation from hiding a partial multi-node write.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    expected_artifact_sha256="$(
      jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
    )"
    allow_missing_finality_keys="$(
      jq -er ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
    )"
    command="$(
      render_runtime_finality_mutation \
        "$finality_enabled" "$block_interval" "$slot_epoch" \
        "$expected_artifact_sha256" "$allow_missing_finality_keys"
    )"
    jq -n --arg command "$command" '{commands: [$command]}' \
      >"artifacts/ssm-set-finality-${index}.json"
    if command_id="$(
      aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name AWS-RunShellScript \
        --parameters "file://artifacts/ssm-set-finality-${index}.json" \
        --comment "JUNCA Public Testnet fail-closed finality configuration" \
        --query Command.CommandId \
        --output text
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
        "artifacts/finality-${block_interval}-${slot_epoch}-${instance_id}.json"
    then
      mutation_failed=true
      continue
    fi
    if ! jq -e '.Status == "Success"' \
      "artifacts/finality-${block_interval}-${slot_epoch}-${instance_id}.json" \
      >/dev/null; then
      mutation_failed=true
    fi
  done
  if [[ "$mutation_failed" == "true" ]]; then
    # Best-effort compensation always returns every reachable node to disabled
    # false/0/0 before the still-future canonical epoch.
    local -a compensation_command_ids=()
    for index in "${!instances[@]}"; do
      instance_id="${instances[$index]}"
      expected_artifact_sha256="$(
        jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
      )"
      allow_missing_finality_keys="$(
        jq -er ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
      )"
      command="$(
        render_runtime_finality_mutation \
          false 0 0 "$expected_artifact_sha256" \
          "$allow_missing_finality_keys"
      )"
      jq -n --arg command "$command" '{commands: [$command]}' \
        >"artifacts/ssm-finality-compensate-${index}.json"
      if command_id="$(
        aws ssm send-command \
          --instance-ids "$instance_id" \
          --document-name AWS-RunShellScript \
          --parameters "file://artifacts/ssm-finality-compensate-${index}.json" \
          --comment "JUNCA Public Testnet finality failure compensation" \
          --query Command.CommandId \
          --output text
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
          "artifacts/finality-compensation-${instance_id}.json" || true
      fi
      expected_artifact_sha256="$(
        jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
      )"
      command="$(
        render_runtime_finality_readback \
          false 0 0 "$expected_artifact_sha256"
      )"
      jq -n --arg command "$command" '{commands: [$command]}' \
        >"artifacts/ssm-finality-compensation-readback-${index}.json"
      if command_id="$(
        aws ssm send-command \
          --instance-ids "$instance_id" \
          --document-name AWS-RunShellScript \
          --parameters \
            "file://artifacts/ssm-finality-compensation-readback-${index}.json" \
          --comment "JUNCA Public Testnet finality compensation readback" \
          --query Command.CommandId \
          --output text
      )"; then
        wait_for_ssm_command_result \
          "$command_id" "$instance_id" \
          "artifacts/finality-compensation-readback-${instance_id}.json" || true
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
}

capture_validator_observation() {
  local validator_id="$1"
  local instance_id="$2"
  local output_path="$3"
  local readback_command
  local command_id
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
  readback_command='
set -euo pipefail
systemctl is-active --quiet junca-validator.service
mountpoint -q /var/lib/junca
test -f /var/lib/junca/state.sqlite
test ! -L /var/lib/junca/state.sqlite
test "$(python3 -c '"'"'import sqlite3; connection=sqlite3.connect("file:/var/lib/junca/state.sqlite?mode=ro", uri=True); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()'"'"')" = "ok"
durable="$(python3 -c '"'"'import json,sqlite3; connection=sqlite3.connect("file:/var/lib/junca/state.sqlite?mode=ro",uri=True); connection.row_factory=sqlite3.Row; row=connection.execute("SELECT b.height,b.block_hash,b.certificate_hash,f.certificate_json FROM blocks b JOIN finality_certificates f ON f.height=b.height WHERE b.finalized=1 ORDER BY b.height DESC LIMIT 1").fetchone(); assert row is not None; certificate=json.loads(row["certificate_json"]); print(json.dumps({"head_height":row["height"],"head_hash":row["block_hash"],"certificate_hash":row["certificate_hash"],"certificate":certificate},sort_keys=True,separators=(",",":"))); connection.close()'"'"')"
test -f /etc/junca/runtime.env
test ! -L /etc/junca/runtime.env
runtime_version="$(sed -n '"'"'s/^NODE_ARTIFACT_SHA256=//p'"'"' /etc/junca/runtime.env)"
test "$(printf %s "$runtime_version" | wc -c)" = 64
# BEGIN_RUNTIME_FINALITY_READBACK
test "$(grep -c '"'"'^AUTOMATIC_FINALITY_ENABLED='"'"' /etc/junca/runtime.env)" = 1
test "$(grep -c '"'"'^TESTNET_BLOCK_INTERVAL_SECONDS='"'"' /etc/junca/runtime.env)" = 1
test "$(grep -c '"'"'^TESTNET_SLOT_EPOCH_SECONDS='"'"' /etc/junca/runtime.env)" = 1
runtime_automatic_finality_enabled="$(sed -n '"'"'s/^AUTOMATIC_FINALITY_ENABLED=//p'"'"' /etc/junca/runtime.env)"
runtime_block_interval_seconds="$(sed -n '"'"'s/^TESTNET_BLOCK_INTERVAL_SECONDS=//p'"'"' /etc/junca/runtime.env)"
runtime_slot_epoch_seconds="$(sed -n '"'"'s/^TESTNET_SLOT_EPOCH_SECONDS=//p'"'"' /etc/junca/runtime.env)"
[[ "$runtime_automatic_finality_enabled" =~ ^(true|false)$ ]]
[[ "$runtime_block_interval_seconds" =~ ^(0|30)$ ]]
[[ "$runtime_slot_epoch_seconds" =~ ^(0|[1-9][0-9]*)$ ]]
if [[ "$runtime_automatic_finality_enabled" == "true" ]]; then
  test "$runtime_block_interval_seconds" = 30
  test "$runtime_slot_epoch_seconds" -gt 0
else
  test "$runtime_block_interval_seconds" = 0
fi
# END_RUNTIME_FINALITY_READBACK
health="$(curl -fsS http://127.0.0.1:8545/health)"
jq -n \
  --arg runtime_version "$runtime_version" \
  --argjson health "$health" \
  --argjson durable "$durable" \
  --argjson runtime_automatic_finality_enabled "$runtime_automatic_finality_enabled" \
  --argjson runtime_block_interval_seconds "$runtime_block_interval_seconds" \
  --argjson runtime_slot_epoch_seconds "$runtime_slot_epoch_seconds" '"'"'
def finality_readback:
  [
    $health.automatic_finality_enabled,
    $health.block_interval_seconds,
    $health.slot_epoch_seconds
  ] as $observed
  | ($observed | map(select(. != null)) | length) as $present
  | if $present == 0 then
      {
        automatic_finality_enabled: $runtime_automatic_finality_enabled,
        block_interval_seconds: $runtime_block_interval_seconds,
        slot_epoch_seconds: $runtime_slot_epoch_seconds,
        health_supported: false
      }
    elif $present != 3 then
      error("health finality readback is partially missing")
    elif (
      ($health.automatic_finality_enabled | type) != "boolean" or
      ($health.block_interval_seconds | type) != "number" or
      ($health.slot_epoch_seconds | type) != "number" or
      $health.automatic_finality_enabled !=
        $runtime_automatic_finality_enabled or
      $health.block_interval_seconds != $runtime_block_interval_seconds or
      $health.slot_epoch_seconds != $runtime_slot_epoch_seconds
    ) then
      error("health and runtime.env finality readback differ")
    else
      {
        automatic_finality_enabled: $health.automatic_finality_enabled,
        block_interval_seconds: $health.block_interval_seconds,
        slot_epoch_seconds: $health.slot_epoch_seconds,
        health_supported: true
      }
    end;

(finality_readback) as $finality
|
{
  validator_id: $health.validator_id,
  runtime_version: $runtime_version,
  healthy: ($health.status == "healthy"),
  health_status: $health.status,
  network: $health.network,
  chain_id: $health.chain_id,
  ssm_online: true,
  service_active: true,
  durable_mount_verified: true,
  state_store_integrity: true,
  head_height: $health.head_height,
  head_hash: $health.head_hash,
  certificate_hash:
    ($health.consensus.last_certificate_hash // $durable.certificate_hash),
  durable_certificate_hash: $durable.certificate_hash,
  certificate_height:
    ($health.consensus.last_certificate.height // $durable.certificate.height),
  certificate_block_hash:
    ($health.consensus.last_certificate.block_hash //
      $durable.certificate.block_hash),
  certificate_finality_status:
    ($health.consensus.last_certificate.finality_status //
      $durable.certificate.finality_status),
  certificate_signed_power:
    ($health.consensus.last_certificate.signed_power //
      $durable.certificate.signed_power),
  certificate_total_power:
    ($health.consensus.last_certificate.total_power //
      $durable.certificate.total_power),
  certificate_validator_ids:
    ($health.consensus.last_certificate.validator_ids //
      $durable.certificate.validator_ids),
  certificate_vote_hashes:
    ($health.consensus.last_certificate.vote_hashes //
      $durable.certificate.vote_hashes),
  automatic_finality_enabled: $finality.automatic_finality_enabled,
  block_interval_seconds: $finality.block_interval_seconds,
  slot_epoch_seconds: $finality.slot_epoch_seconds,
  finality_readback: {
    runtime_env: {
      automatic_finality_enabled: $runtime_automatic_finality_enabled,
      block_interval_seconds: $runtime_block_interval_seconds,
      slot_epoch_seconds: $runtime_slot_epoch_seconds
    },
    health: {
      automatic_finality_enabled: $health.automatic_finality_enabled,
      block_interval_seconds: $health.block_interval_seconds,
      slot_epoch_seconds: $health.slot_epoch_seconds
    },
    health_supported: $finality.health_supported
  },
  mainnet_changed: $health.mainnet_changed,
  assets_moved: $health.assets_moved,
  bridge_activated: $health.bridge_activated
}
'"'"'
'
  jq -n --arg command "$readback_command" '{commands: [$command]}' \
    > artifacts/ssm-validator-readback.json
  command_id="$(
    aws ssm send-command \
      --instance-ids "$instance_id" \
      --document-name AWS-RunShellScript \
      --parameters file://artifacts/ssm-validator-readback.json \
      --comment "JUNCA Public Testnet rolling compatibility readback" \
      --query Command.CommandId \
      --output text
  )"
  invocation="artifacts/readback-${validator_id}-${instance_id}.json"
  wait_for_ssm_command "$command_id" "$instance_id" "$invocation"
  jq -er .StandardOutputContent "$invocation" |
    jq \
      --arg ami_id "$ami_id" \
      --arg instance_id "$instance_id" \
      '. + {ami_id: $ami_id, instance_id: $instance_id}' >"$output_path"
  jq -e --arg validator_id "$validator_id" \
    '.validator_id == $validator_id' "$output_path" >/dev/null
}

write_live_rollout_prefix_readback() {
  local evidence_updated_count="$1"
  local evidence_validators_path="$2"
  local previous_artifact_sha256="$3"
  local previous_ami_id="$4"
  local -a current_instances
  local index
  [[ "$evidence_updated_count" =~ ^[0-3]$ ]]
  if [[ -n "$evidence_validators_path" ]]; then
    test -f "$evidence_validators_path"
  fi
  terraform -chdir=infra/aws/public-testnet output -json \
    > artifacts/live-prefix-foundation-outputs.json
  mapfile -t current_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/live-prefix-foundation-outputs.json
  )
  test "${#current_instances[@]}" = 3
  for index in 0 1 2; do
    capture_validator_observation \
      "validator-0$((index + 1))" \
      "${current_instances[$index]}" \
      "artifacts/live-prefix-validator-$((index + 1)).json"
  done
  jq -s '.' artifacts/live-prefix-validator-{1,2,3}.json \
    > artifacts/live-prefix-validators.json
  if [[ -z "$evidence_validators_path" ]]; then
    evidence_validators_path=artifacts/live-prefix-validators.json
  fi
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
    --slurpfile evidence_validators "$evidence_validators_path" '{
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
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' > artifacts/live-prefix-readback.json
  python -m jaios.social_ecosystem_chain.rolling_compatibility \
    --mode live-prefix \
    --evidence artifacts/live-prefix-readback.json \
    --output artifacts/live-prefix-decision.json
}

write_rolling_compatibility_evidence() {
  local expected_state="$1"
  local expected_next="${2:-}"
  local -a current_instances
  local index
  terraform -chdir=infra/aws/public-testnet output -json \
    > artifacts/rolling-foundation-outputs.json
  mapfile -t current_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/rolling-foundation-outputs.json
  )
  test "${#current_instances[@]}" = 3
  for index in 0 1 2; do
    capture_validator_observation \
      "validator-0$((index + 1))" \
      "${current_instances[$index]}" \
      "artifacts/rolling-validator-$((index + 1)).json"
  done
  jq -s '.' artifacts/rolling-validator-{1,2,3}.json \
    > artifacts/rolling-validators.json
  jq -n \
    --arg target_version "$NODE_ARTIFACT_SHA256" \
    --arg target_ami_id "$NODE_AMI_ID" \
    --argjson requested_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson observed_unix_time "$(date +%s)" \
    --slurpfile validators artifacts/rolling-validators.json \
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
  python -m jaios.social_ecosystem_chain.rolling_compatibility \
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
  jq -er '.public_services_acceptance_readback.value.enabled // false' \
    artifacts/pre-foundation-outputs.json
)"
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
  test "$automatic_finality_enabled" = "true"
  test "$validator_block_interval_seconds" = "30"
  [[ "$validator_slot_epoch_seconds" =~ ^[0-9]+$ ]]
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
    enable_public_services: $enable_public_services,
    quorum_acceptance_sha256: (
      if $enable_public_services then $quorum_acceptance_sha256 else null end
    ),
    runtime_acceptance_sha256: (
      if $enable_public_services then $runtime_acceptance_sha256 else null end
    )
  }' > artifacts/foundation.auto.tfvars.json

terraform -chdir=infra/aws/public-testnet plan -input=false \
  -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
  -out="$GITHUB_WORKSPACE/artifacts/foundation.tfplan"
terraform -chdir=infra/aws/public-testnet show -json \
  "$GITHUB_WORKSPACE/artifacts/foundation.tfplan" > artifacts/foundation-plan.json

# Destructive changes remain fail-closed. The only permitted delete action is
# an AMI-driven replacement of one or more of the three canonical validators.
jq -e \
  --argjson public_services_enabled "$public_services_enabled" \
  --argjson validator_state_enabled "$validator_state_enabled" '
  [
    .resource_changes[]?
    | select(.change.actions | index("delete"))
    | {
        address,
        actions: .change.actions,
        replace_paths: (.change.replace_paths // [])
      }
  ] as $deletions
  | ($deletions | length) == 0 or
    (
      [
        $deletions[]
        | select(.address | test("^aws_instance\\.validator\\[[0-2]\\]$"))
      ] as $validators
      | [
          $validators[].address
          | capture("^aws_instance\\.validator\\[(?<index>[0-2])\\]$").index
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
          $deletions[]
          | select(.address | test(
              "^aws_lb_target_group_attachment\\.(rpc|explorer)\\[[0-2]\\]$"
          ))
        ] as $attachments
      | [
          $deletions[]
          | select(.address | test(
              "^aws_volume_attachment\\.validator_state\\[[0-2]\\]$"
            ))
        ] as $state_attachments
      | ($validators | length) >= 1 and
        ($validators | length) <= 3 and
        ([ $deletions[].address ] | unique | length) == ($deletions | length) and
        (
          if $public_services_enabled then
            ([ $attachments[].address ] | sort) == ($expected_attachments | sort)
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
        ($deletions | length) == (
          ($validators | length) +
          ($attachments | length) +
          ($state_attachments | length)
        ) and
        all(
          $deletions[];
          (.actions | index("create")) != null and
          (.actions | index("delete")) != null and
          (
            (
              (.address | test("^aws_instance\\.validator\\[[0-2]\\]$")) and
              (.replace_paths | any(.[]; . == ["ami"]))
            ) or
            (
              (.address | test(
                "^aws_lb_target_group_attachment\\.(rpc|explorer)\\[[0-2]\\]$"
              )) and
              (.replace_paths | any(.[]; . == ["target_id"]))
            ) or
            (
              (.address | test(
                "^aws_volume_attachment\\.validator_state\\[[0-2]\\]$"
              )) and
              (.replace_paths | any(.[]; . == ["instance_id"]))
            )
          )
        )
    )
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
  mapfile -t pre_rollout_instances < <(
    jq -er '.validator_instance_ids.value[]' \
      artifacts/pre-foundation-outputs.json
  )
  test "${#pre_rollout_instances[@]}" = 3
  resume_path="${ROLLING_RESUME_EVIDENCE_PATH:-}"
  resume_updated_count=0
  resume_evidence_validators_path=""
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
        "$validator_slot_epoch_seconds" '
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
        .automatic_finality == {
          block_interval_seconds: $validator_block_interval_seconds,
          slot_epoch_seconds: $validator_slot_epoch_seconds,
          minimum_remaining_seconds: 900,
          maximum_remaining_seconds: 7230
        } and
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
    "$previous_artifact_sha256" "$previous_ami_id"
  live_updated_count="$(
    jq -er '.live_updated_count' artifacts/live-prefix-decision.json
  )"

  # Stop automatic finality before the next replacement. The observed target
  # prefix is bound strictly to the candidate artifact; only the remaining
  # legacy suffix may initialize all-absent false/0/0 keys.
  pre_rollout_finality_bindings="$(
    build_pre_rollout_finality_bindings \
      "$live_updated_count" \
      "$NODE_ARTIFACT_SHA256" "$previous_artifact_sha256" \
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
        --arg address "$address" \
        --argjson expected_addresses "$expected_addresses_json" '
        [
          .resource_changes[]?
          | select(.change.actions | index("delete"))
          | {
              address,
              actions: .change.actions,
            replace_paths: (.change.replace_paths // [])
          }
        ] as $deletions
        | ($deletions | length) == ($expected_addresses | length) and
          ([ $deletions[].address ] | sort) == ($expected_addresses | sort) and
          all(
            $deletions[];
            (.actions | index("create")) != null and
            (.actions | index("delete")) != null and
            (
              (
                .address == $address and
                (.replace_paths | any(.[]; . == ["ami"]))
              ) or
              (
                .address != $address and
                (
                  (.replace_paths | any(.[]; . == ["target_id"])) or
                  (.replace_paths | any(.[]; . == ["instance_id"]))
                )
              )
            )
          )
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

      # A replacement boots with the Terraform-bound future epoch. Quiesce it
      # immediately after SSM and retained-volume readback; the epoch is still
      # in the future, so no automatic-finality slot can execute during this
      # bounded transition.
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
          "$NODE_ARTIFACT_SHA256" false "$new_instance"
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
    terraform -chdir=infra/aws/public-testnet plan -input=false \
      -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
      -out="$GITHUB_WORKSPACE/artifacts/foundation-reconcile.tfplan"
    terraform -chdir=infra/aws/public-testnet show -json \
      "$GITHUB_WORKSPACE/artifacts/foundation-reconcile.tfplan" \
      > artifacts/foundation-reconcile-plan.json
    jq -e '[.resource_changes[]?.change.actions | select(index("delete"))] | length == 0' \
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
        "$NODE_ARTIFACT_SHA256" false "${activated_instances[@]}"
    )"
    test "$((validator_slot_epoch_seconds - $(date +%s)))" -ge 900
    set_runtime_finality \
      0 "$validator_slot_epoch_seconds" "$activated_finality_bindings"
    write_rolling_compatibility_evidence READY_FOR_FINALITY_ENABLE
    test "$((validator_slot_epoch_seconds - $(date +%s)))" -ge 900
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
