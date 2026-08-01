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

read_required_json_boolean() {
  local path_json="$1"
  local source_path="$2"
  jq -r \
    --argjson path "$path_json" '
      getpath($path)
      | if type == "boolean" then
          tostring
        else
          error("required JSON boolean is missing or invalid")
        end
    ' "$source_path"
}

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
  local expected_ids
  local snapshot_lines
  snapshot_lines="$(
    jq -er '
      .[].rollback_snapshot_id
      | select(
          type == "string" and
          test("^snap-[0-9a-f]{8,17}$")
        )
    ' <<<"$validator_state_json"
  )"
  mapfile -t snapshot_ids <<<"$snapshot_lines"
  test "${#snapshot_ids[@]}" = 3
  expected_ids="$(
    printf '%s\n' "${snapshot_ids[@]}" |
      jq -Rsc 'split("\n")[:-1] | sort | unique'
  )"
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

ensure_public_gateways_available() {
  local instance_id="$1"
  local command_path="$2"
  local result_path="$3"
  local command_id=""

  jq -n '{
    commands: [
      "set -euo pipefail",
      "systemctl is-active --quiet junca-validator.service",
      "curl -fsS http://127.0.0.1:8545/health >/tmp/junca-validator-health.json",
      "systemctl daemon-reload",
      "systemctl enable junca-public-rpc.service junca-public-explorer.service",
      "systemctl restart junca-public-rpc.service junca-public-explorer.service",
      "for attempt in $(seq 1 60); do if curl -fsS http://127.0.0.1:8546/health >/tmp/junca-public-rpc-health.json && curl -fsS http://127.0.0.1:3000/health >/tmp/junca-public-explorer-health.json; then break; fi; test \"$attempt\" -lt 60; sleep 2; done",
      "systemctl is-active --quiet junca-public-rpc.service junca-public-explorer.service",
      "jq -e \".status == \\\"healthy\\\" and .read_only == true\" /tmp/junca-public-rpc-health.json >/dev/null",
      "jq -e \".status == \\\"healthy\\\" and .read_only == true\" /tmp/junca-public-explorer-health.json >/dev/null",
      "echo \"{\\\"schema_version\\\":\\\"junca-public-gateway-local-readback/v1\\\",\\\"accepted\\\":true,\\\"mainnet_changed\\\":false,\\\"assets_moved\\\":false,\\\"bridge_activated\\\":false}\""
    ]
  }' >"$command_path"
  command_id="$(
    aws ssm send-command \
      --instance-ids "$instance_id" \
      --document-name AWS-RunShellScript \
      --parameters "file://$command_path" \
      --comment "JUNCA Public Testnet local gateway readiness" \
      --query Command.CommandId \
      --output text
  )"
  wait_for_ssm_command_result "$command_id" "$instance_id" "$result_path"
  jq -e '
    .Status == "Success" and
    (.ResponseCode // -1) == 0 and
    (.StandardOutputContent | contains(
      "junca-public-gateway-local-readback/v1"
    )) and
    (.StandardOutputContent | contains("\"accepted\":true"))
  ' "$result_path" >/dev/null
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

write_finality_local_gate() {
  local output_path="$1"
  local block_interval="$2"
  local slot_epoch="$3"
  local bindings_json="$4"
  local stage="$5"
  local accepted="$6"
  local reason="${7:-}"
  jq -n \
    --arg stage "$stage" \
    --arg reason "$reason" \
    --argjson accepted "$accepted" \
    --argjson block_interval "$block_interval" \
    --argjson slot_epoch "$slot_epoch" \
    --argjson bindings "$bindings_json" '{
      schema_version: "junca-finality-local-gate/v1",
      stage: $stage,
      requested: {
        block_interval_seconds: $block_interval,
        slot_epoch_seconds: $slot_epoch
      },
      bindings: $bindings,
      accepted: $accepted,
      reason: (if $reason == "" then null else $reason end),
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' >"$output_path"
}

write_pre_rollout_quiesce_reuse_decision() {
  local validators_path="$1"
  local updated_count="$2"
  local target_artifact_sha256="$3"
  local output_path="$4"
  [[ "$updated_count" =~ ^[0-3]$ ]]
  [[ "$target_artifact_sha256" =~ ^[0-9a-f]{64}$ ]]
  test -f "$validators_path"
  if ! jq -e \
    --argjson updated_count "$updated_count" \
    --arg target_artifact_sha256 "$target_artifact_sha256" '
      . as $validators |
      type == "array" and length == 3 and
      [.[].validator_id] ==
        ["validator-01", "validator-02", "validator-03"] and
      all(
        .[];
        .healthy == true and
        .service_active == true and
        .ssm_online == true and
        .automatic_finality_enabled == false and
        .block_interval_seconds == 0 and
        .slot_epoch_seconds == 0 and
        .finality_readback.health_supported == true and
        .finality_readback.runtime_env.automatic_finality_enabled == false and
        .finality_readback.runtime_env.block_interval_seconds == 0 and
        .finality_readback.runtime_env.slot_epoch_seconds == 0 and
        .finality_readback.health.automatic_finality_enabled == false and
        .finality_readback.health.block_interval_seconds == 0 and
        .finality_readback.health.slot_epoch_seconds == 0 and
        .mainnet_changed == false and
        .assets_moved == false and
        .bridge_activated == false
      ) and
      all(
        range(0; $updated_count);
        . as $index |
        $validators[$index].runtime_version == $target_artifact_sha256
      )
    ' "$validators_path" >/dev/null
  then
    return 1
  fi
  jq -n \
    --argjson updated_count "$updated_count" '{
      schema_version: "junca-pre-rollout-finality-quiesce/v1",
      state: "EXACT_QUIESCED_READBACK_REUSED",
      updated_count: $updated_count,
      mutation_performed: false,
      automatic_finality_enabled: false,
      block_interval_seconds: 0,
      slot_epoch_seconds: 0,
      accepted: true,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' >"$output_path"
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
  local instance_lines
  local local_gate_path
  local index
  local mutation_failed=false
  local -a instances=()
  local -a mutation_command_ids=()
  local_gate_path="artifacts/finality-local-gate-${block_interval}-${slot_epoch}.json"
  if ! [[ "$block_interval" =~ ^(0|30)$ ]] ||
    ! [[ "$slot_epoch" =~ ^(0|[1-9][0-9]*)$ ]] ||
    ! jq -e '
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
  then
    write_finality_local_gate \
      "$local_gate_path" "$block_interval" "$slot_epoch" \
      "$bindings_json" INPUT_REJECTED false \
      "invalid finality request or runtime bindings"
    return 1
  fi
  if ! instance_lines="$(
    jq -er '.[].instance_id' <<<"$bindings_json"
  )"; then
    write_finality_local_gate \
      "$local_gate_path" "$block_interval" "$slot_epoch" \
      "$bindings_json" INSTANCE_BINDINGS_REJECTED false \
      "unable to read the ordered instance bindings"
    return 1
  fi
  mapfile -t instances <<<"$instance_lines"
  if [[ "${#instances[@]}" -lt 1 || "${#instances[@]}" -gt 3 ]]; then
    write_finality_local_gate \
      "$local_gate_path" "$block_interval" "$slot_epoch" \
      "$bindings_json" INSTANCE_BINDINGS_REJECTED false \
      "ordered instance binding count is outside one through three"
    return 1
  fi
  if [[ "$slot_epoch" != "0" ]]; then
    if ! test "$slot_epoch" -gt "$(date +%s)" ||
      ! test "$((slot_epoch % 30))" -eq 0
    then
      write_finality_local_gate \
        "$local_gate_path" "$block_interval" "$slot_epoch" \
        "$bindings_json" SLOT_EPOCH_REJECTED false \
        "slot epoch is not a future 30-second boundary"
      return 1
    fi
  fi
  if [[ "$block_interval" == "30" ]]; then
    if [[ "$slot_epoch" == "0" ]]; then
      write_finality_local_gate \
        "$local_gate_path" "$block_interval" "$slot_epoch" \
        "$bindings_json" SLOT_EPOCH_REJECTED false \
        "enabled finality requires a non-zero future slot epoch"
      return 1
    fi
    finality_enabled=true
  else
    finality_enabled=false
  fi

  # Render and retain every read-only command before the first SSM request.
  # This makes a local binding/render failure distinguishable from a remote
  # validator preflight failure without weakening the fail-closed boundary.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
    if ! expected_artifact_sha256="$(
      jq -er ".[$index].expected_artifact_sha256" <<<"$bindings_json"
    )" || ! allow_missing_finality_keys="$(
      # A valid false boolean makes jq --exit-status return 1. The complete
      # bindings object was schema-checked above, so read this value without
      # treating false as a failed lookup.
      jq -r ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
    )"; then
      write_finality_local_gate \
        "$local_gate_path" "$block_interval" "$slot_epoch" \
        "$bindings_json" COMMAND_BINDING_REJECTED false \
        "unable to read a finality command binding at index ${index}"
      return 1
    fi
    if ! command="$(
      render_runtime_finality_preflight \
        "$finality_enabled" "$block_interval" "$slot_epoch" \
        "$expected_artifact_sha256" "$allow_missing_finality_keys"
    )" || ! jq -n --arg command "$command" '{commands: [$command]}' \
      >"artifacts/ssm-finality-preflight-${index}.json"
    then
      write_finality_local_gate \
        "$local_gate_path" "$block_interval" "$slot_epoch" \
        "$bindings_json" COMMAND_RENDER_REJECTED false \
        "unable to render a finality preflight at index ${index}"
      return 1
    fi
  done
  write_finality_local_gate \
    "$local_gate_path" "$block_interval" "$slot_epoch" \
    "$bindings_json" READ_ONLY_PREFLIGHT_RENDERED true

  # Complete every read-only preflight before any runtime.env mutation.
  for index in "${!instances[@]}"; do
    instance_id="${instances[$index]}"
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
      jq -r ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
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
        jq -r ".[$index].allow_missing_finality_keys" <<<"$bindings_json"
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

read_instance_ami_binding() {
  local instance_id="$1"
  local output_path="$2"
  local instance_readback_path="${output_path%.json}.instance.json"
  local image_readback_path="${output_path%.json}.image.json"
  local ami_id
  local runtime_version
  local source_commit
  [[ "$instance_id" =~ ^i-[0-9a-f]{8,17}$ ]]
  aws ec2 describe-instances \
    --region "$AWS_REGION" \
    --instance-ids "$instance_id" \
    --output json >"$instance_readback_path"
  jq -e \
    --arg account_id "$AWS_ACCOUNT_ID" \
    --arg region "$AWS_REGION" \
    --arg instance_id "$instance_id" '
      .Reservations as $reservations
      | $reservations[0].Instances[0] as $instance
      | ($reservations | length) == 1 and
        $reservations[0].OwnerId == $account_id and
        ($reservations[0].Instances | length) == 1 and
        $instance.InstanceId == $instance_id and
        $instance.State.Name == "running" and
        ($instance.ImageId | type) == "string" and
        ($instance.ImageId | test("^ami-[0-9a-f]{8,17}$")) and
        ($instance.Placement.AvailabilityZone | type) == "string" and
        ($instance.Placement.AvailabilityZone | startswith($region))
    ' "$instance_readback_path" >/dev/null
  ami_id="$(
    jq -er '.Reservations[0].Instances[0].ImageId' \
      "$instance_readback_path"
  )"
  aws ec2 describe-images \
    --region "$AWS_REGION" \
    --image-ids "$ami_id" \
    --owners self \
    --output json >"$image_readback_path"
  jq -e \
    --arg account_id "$AWS_ACCOUNT_ID" \
    --arg ami_id "$ami_id" \
    --arg genesis_sha256 "$GENESIS_SHA256" '
      .Images as $images
      | $images[0] as $image
      | ([$image.Tags[]? |
          select(.Key == "NodeArtifactSHA256") | .Value]) as $node
      | ([$image.Tags[]? |
          select(.Key == "GenesisSHA256") | .Value]) as $genesis
      | ([$image.Tags[]? |
          select(.Key == "SourceCommit") | .Value]) as $source
      | ([$image.Tags[]? |
          select(.Key == "Network") | .Value]) as $network
      | ([$image.Tags[]? |
          select(.Key == "Governance") | .Value]) as $governance
      | ($images | length) == 1 and
        $image.ImageId == $ami_id and
        $image.OwnerId == $account_id and
        $image.State == "available" and
        $image.ImageType == "machine" and
        $image.Architecture == "x86_64" and
        $image.VirtualizationType == "hvm" and
        $image.RootDeviceType == "ebs" and
        $image.Public == false and
        ($node | length) == 1 and
        ($node[0] | type) == "string" and
        ($node[0] | test("^[0-9a-f]{64}$")) and
        ($genesis | length) == 1 and
        $genesis[0] == $genesis_sha256 and
        ($source | length) == 1 and
        ($source[0] | type) == "string" and
        ($source[0] | test("^[0-9a-f]{40}$")) and
        ($network | length) == 1 and
        $network[0] == "Public Testnet" and
        ($governance | length) == 1 and
        $governance[0] == "JAIOS Institutional Governance"
    ' "$image_readback_path" >/dev/null
  runtime_version="$(
    jq -er '
      [ .Images[0].Tags[]? |
        select(.Key == "NodeArtifactSHA256") | .Value ]
      | select(length == 1) | .[0]
    ' "$image_readback_path"
  )"
  source_commit="$(
    jq -er '
      [ .Images[0].Tags[]? |
        select(.Key == "SourceCommit") | .Value ]
      | select(length == 1) | .[0]
    ' "$image_readback_path"
  )"
  jq -n \
    --arg account_id "$AWS_ACCOUNT_ID" \
    --arg region "$AWS_REGION" \
    --arg instance_id "$instance_id" \
    --arg ami_id "$ami_id" \
    --arg runtime_version "$runtime_version" \
    --arg source_commit "$source_commit" \
    --arg genesis_sha256 "$GENESIS_SHA256" \
    --slurpfile instance "$instance_readback_path" \
    --slurpfile image "$image_readback_path" '{
      schema_version: "junca-validator-instance-ami-binding/v1",
      account_id: $account_id,
      region: $region,
      instance_id: $instance_id,
      instance_state: $instance[0].Reservations[0].Instances[0].State.Name,
      availability_zone:
        $instance[0].Reservations[0].Instances[0].Placement.AvailabilityZone,
      ami_id: $ami_id,
      ami_owner_id: $image[0].Images[0].OwnerId,
      ami_state: $image[0].Images[0].State,
      runtime_version: $runtime_version,
      source_commit: $source_commit,
      genesis_sha256: $genesis_sha256,
      network: "Public Testnet",
      governance: "JAIOS Institutional Governance",
      accepted: true,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false,
      mainnet_activation_authorized: false
    }' >"$output_path"
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

render_canonical_validator_runtime_env() {
  local validator_id="$1"
  local runtime_version="$2"
  local genesis_sha256="$3"
  local signer_arn="$4"
  local signer_bindings="$5"
  local peer_endpoints="$6"
  local automatic_finality_enabled="$7"
  local block_interval_seconds="$8"
  local slot_epoch_seconds="$9"
  local binding_01
  local binding_02
  local binding_03
  local binding_extra
  local selected_binding
  [[ "$validator_id" =~ ^validator-0[1-3]$ ]]
  [[ "$runtime_version" =~ ^[0-9a-f]{64}$ ]]
  [[ "$genesis_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$signer_arn" =~ ^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$ ]]
  IFS=, read -r binding_01 binding_02 binding_03 binding_extra \
    <<<"$signer_bindings"
  [[ -z "$binding_extra" ]]
  [[ "$binding_01" =~ ^validator-01=arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$ ]]
  [[ "$binding_02" =~ ^validator-02=arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$ ]]
  [[ "$binding_03" =~ ^validator-03=arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$ ]]
  case "$validator_id" in
    validator-01) selected_binding="${binding_01#*=}" ;;
    validator-02) selected_binding="${binding_02#*=}" ;;
    validator-03) selected_binding="${binding_03#*=}" ;;
  esac
  test "$selected_binding" = "$signer_arn"
  test "$peer_endpoints" = \
    "validator-01=10.67.16.10:30303,validator-02=10.67.32.10:30303,validator-03=10.67.48.10:30303"
  case "$automatic_finality_enabled" in
    true)
      test "$block_interval_seconds" = 30
      [[ "$slot_epoch_seconds" =~ ^[1-9][0-9]*$ ]]
      test "$((slot_epoch_seconds % 30))" = 0
      ;;
    false)
      test "$block_interval_seconds" = 0
      test "$slot_epoch_seconds" = 0
      ;;
    *) return 2 ;;
  esac
  cat <<EOF
CHAIN_NAME=JUNCA Social Ecosystem Chain
GOVERNANCE=JAIOS Institutional Governance
NETWORK_NOTICE=Public Testnet / No Monetary Value
VALIDATOR_ID=${validator_id}
CHAIN_ID=20260723
GENESIS_SHA256=${genesis_sha256}
NODE_ARTIFACT_SHA256=${runtime_version}
SIGNER_RESOURCE_ARN=${signer_arn}
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1
PUBLIC_RPC=false
P2P_PORT=30303
# Comma-separated exact-three contracts:
# validator-01=arn:aws:kms:...,... and validator-01=10.x.x.x:30303,...
VALIDATOR_SIGNER_BINDINGS=${signer_bindings}
VALIDATOR_PEER_ENDPOINTS=${peer_endpoints}
AUTOMATIC_FINALITY_ENABLED=${automatic_finality_enabled}
TESTNET_BLOCK_INTERVAL_SECONDS=${block_interval_seconds}
TESTNET_SLOT_EPOCH_SECONDS=${slot_epoch_seconds}
BRIDGE_ACTIVATED=false
EOF
}

validate_validator_service_recovery_evidence() {
  local evidence_path="$1"
  local validator_id="$2"
  local instance_id="$3"
  local expected_ami_id="$4"
  local expected_runtime_version="$5"
  local expected_runtime_env_sha256="$6"
  local expected_state_volume_id="$7"
  local expected_genesis_sha256="$8"
  local expected_source_commit="$9"
  shift 9
  local expected_recovery_request_sha256="$1"
  local expected_recovery_command_id="$2"
  local expected_recovery_run_id="$3"
  local expected_recovery_run_attempt="$4"
  local expected_release_request_sha256="$5"
  local expected_manifest_decision_sha256="$6"
  local expected_candidate_head_sha="$7"
  local expected_allow_runtime_env_repair="$8"
  [[ "$expected_genesis_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$expected_source_commit" =~ ^[0-9a-f]{40}$ ]]
  [[ "$expected_recovery_request_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$expected_recovery_command_id" =~ \
    ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
  [[ "$expected_recovery_run_id" =~ ^[1-9][0-9]*$ ]]
  [[ "$expected_recovery_run_attempt" =~ ^[1-9][0-9]*$ ]]
  [[ "$expected_release_request_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$expected_manifest_decision_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$expected_candidate_head_sha" =~ ^[0-9a-f]{40}$ ]]
  case "$expected_allow_runtime_env_repair" in
    true|false) ;;
    *) return 2 ;;
  esac
  jq -e \
    --arg validator_id "$validator_id" \
    --arg instance_id "$instance_id" \
    --arg expected_ami_id "$expected_ami_id" \
    --arg expected_runtime_version "$expected_runtime_version" \
    --arg expected_runtime_env_sha256 "$expected_runtime_env_sha256" \
    --arg expected_state_volume_id "$expected_state_volume_id" \
    --arg expected_genesis_sha256 "$expected_genesis_sha256" \
    --arg expected_source_commit "$expected_source_commit" \
    --arg expected_recovery_request_sha256 \
      "$expected_recovery_request_sha256" \
    --arg expected_recovery_command_id "$expected_recovery_command_id" \
    --argjson expected_recovery_run_id "$expected_recovery_run_id" \
    --argjson expected_recovery_run_attempt \
      "$expected_recovery_run_attempt" \
    --arg expected_release_request_sha256 \
      "$expected_release_request_sha256" \
    --arg expected_manifest_decision_sha256 \
      "$expected_manifest_decision_sha256" \
    --arg expected_candidate_head_sha "$expected_candidate_head_sha" \
    --argjson expected_allow_runtime_env_repair \
      "$expected_allow_runtime_env_repair" '
      .schema_version == "junca-validator-service-recovery/v8" and
      .validator_id == $validator_id and
      .instance_id == $instance_id and
      .ami_id == $expected_ami_id and
      .genesis_sha256 == $expected_genesis_sha256 and
      .source_commit == $expected_source_commit and
      .recovery_request_sha256 == $expected_recovery_request_sha256 and
      .recovery_command_id == $expected_recovery_command_id and
      .recovery_dispatch_sequence == 1 and
      .recovery_run_id == $expected_recovery_run_id and
      .recovery_run_attempt == $expected_recovery_run_attempt and
      .release_request_sha256 == $expected_release_request_sha256 and
      .manifest_decision_sha256 == $expected_manifest_decision_sha256 and
      .candidate_head_sha == $expected_candidate_head_sha and
      .allow_runtime_env_repair == $expected_allow_runtime_env_repair and
      (.before_status | type) == "string" and
      (.pre_repair_health_status | type) == "string" and
      (.pre_repair_validator_id | type) == "string" and
      (.controlled_active_repair | type) == "boolean" and
      (.controlled_stop_attempted | type) == "boolean" and
      (.controlled_stop_exit | type) == "number" and
      (.controlled_stop_verified | type) == "boolean" and
      (.restart_attempted | type) == "boolean" and
      .restart_exit == 0 and
      (
        if .controlled_active_repair then
          .before_status == "active" and
          .pre_repair_health_status == "healthy" and
          .pre_repair_validator_id == $validator_id and
          .controlled_stop_attempted == true and
          .controlled_stop_exit == 0 and
          .controlled_stop_verified == true and
          .restart_attempted == true
        elif .before_status == "active" then
          .pre_repair_health_status == "healthy" and
          .pre_repair_validator_id == $validator_id and
          .controlled_stop_attempted == false and
          .controlled_stop_exit == 0 and
          .controlled_stop_verified == false and
          .restart_attempted == false
        else
          .pre_repair_health_status == "" and
          .pre_repair_validator_id == "" and
          .controlled_active_repair == false and
          .controlled_stop_attempted == false and
          .controlled_stop_exit == 0 and
          .controlled_stop_verified == false and
          .restart_attempted == true
        end
      ) and
      .durable_mount_verified == true and
      .durable_mount_volume_id == $expected_state_volume_id and
      (.durable_mount_device |
        test("^/dev/nvme[0-9]+n[0-9]+$")) and
      .durable_mount_source == .durable_mount_device and
      (.durable_mount_filesystem == "ext4" or
        .durable_mount_filesystem == "xfs") and
      .durable_mount_persistence_verified == true and
      (.durable_mount_repair_attempted | type) == "boolean" and
      (.durable_mount_repaired | type) == "boolean" and
      (.durable_mount_repair_exit | type) == "number" and
      .durable_mount_repair_exit == 0 and
      (
        if .durable_mount_repaired then
          .before_status != "active" and
          .durable_mount_repair_attempted == true
        else
          .durable_mount_repair_attempted == false
        end
      ) and
      .state_store_integrity == true and
      .state_path_access_verified == true and
      (.state_path_access_repair_attempted | type) == "boolean" and
      (.state_path_access_repaired | type) == "boolean" and
      (
        if .state_path_access_repaired then
          .state_path_access_repair_attempted == true and
          (.before_status != "active" or
            .controlled_active_repair == true)
        else
          .state_path_access_repair_attempted == false
        end
      ) and
      .state_directory_owner == "junca:junca" and
      (.state_directory_mode == "700" or
        .state_directory_mode == "710" or
        .state_directory_mode == "750" or
        .state_directory_mode == "755") and
      .state_file_owner == "junca:junca" and
      (.state_file_mode == "600" or
        .state_file_mode == "640" or
        .state_file_mode == "644") and
      (
        if .state_path_access_repaired then
          .state_directory_mode == "750" and
          .state_file_mode == "600"
        else
          true
        end
      ) and
      .state_file_link_count == 1 and
      (.state_auxiliary_file_count | type) == "number" and
      .state_auxiliary_file_count >= 0 and
      .state_auxiliary_file_count <= 5 and
      .binary_artifact_verified == true and
      .genesis_verified == true and
      .system_identity_verified == true and
      (.system_identity_repair_attempted | type) == "boolean" and
      (.system_identity_repaired | type) == "boolean" and
      .system_identity_uid == 992 and
      .system_identity_gid == 992 and
      (
        if .system_identity_repaired then
          .system_identity_repair_attempted == true and
          .runtime_config_repaired == true
        else
          true
        end
      ) and
      .runtime_config_access_verified == true and
      (.runtime_config_repair_attempted | type) == "boolean" and
      (.runtime_config_repaired | type) == "boolean" and
      (
        if .runtime_config_repaired then
          (.before_status != "active" or
            .controlled_active_repair == true) and
          .runtime_config_repair_attempted == true
        else
          .runtime_config_repair_attempted == false
        end
      ) and
      .runtime_directory_owner == "root:junca" and
      .runtime_directory_mode == "750" and
      .genesis_owner == "root:junca" and
      .genesis_mode == "640" and
      .genesis_link_count == 1 and
      .validator_config_owner == "root:junca" and
      .validator_config_mode == "640" and
      .validator_config_link_count == 1 and
      (.validator_config_preexisting | type) == "boolean" and
      (.validator_config_pre_identity | type) == "string" and
      (.validator_config_pre_sha256 | type) == "string" and
      (.validator_config_pre_size | type) == "number" and
      (.validator_config_identity |
        test("^[0-9]+:[0-9]+$")) and
      (.validator_config_sha256 |
        test("^[0-9a-f]{64}$")) and
      (.validator_config_size | type) == "number" and
      .validator_config_size >= 0 and
      (
        if .validator_config_preexisting then
          (.validator_config_pre_identity |
            test("^[0-9]+:[0-9]+$")) and
          (.validator_config_pre_sha256 |
            test("^[0-9a-f]{64}$")) and
          .validator_config_pre_size >= 0 and
          .validator_config_identity == .validator_config_pre_identity and
          .validator_config_sha256 == .validator_config_pre_sha256 and
          .validator_config_size == .validator_config_pre_size
        else
          .validator_config_pre_identity == "" and
          .validator_config_pre_sha256 == "" and
          .validator_config_pre_size == 0 and
          .validator_config_size == 0
        end
      ) and
      .runtime_directory_verified == true and
      .runtime_env_verified == true and
      .runtime_version == $expected_runtime_version and
      (.runtime_env_repair_attempted | type) == "boolean" and
      (.runtime_env_created | type) == "boolean" and
      (.runtime_env_created_identity | type) == "string" and
      (.runtime_env_admission_identity | type) == "string" and
      .runtime_env_owner == "root:junca" and
      .runtime_env_mode == "640" and
      .runtime_env_link_count == 1 and
      .runtime_env_schema_verified == true and
      .runtime_env_required_assignment_count == 18 and
      (.runtime_env_repaired | type) == "boolean" and
      (.runtime_env_persistence_verified | type) == "boolean" and
      .runtime_env_post_restart_verified == true and
      .repair_rollback_attempted == false and
      .repair_rollback_succeeded == false and
      .repair_rollback_persistence_verified == false and
      .containment_restart_attempted == false and
      .containment_restart_exit == 0 and
      .containment_health_status == "" and
      .containment_recovered == false and
      .service_stop_exit == 0 and
      (
        if .runtime_env_repaired then
          .runtime_env_repair_attempted == true and
          .runtime_env_created == true and
          (.runtime_env_created_identity | test("^[0-9]+:[0-9]+$")) and
          .runtime_env_admission_identity ==
            .runtime_env_created_identity and
          .runtime_env_persistence_verified == true and
          .runtime_env_source == "canonical" and
          .runtime_env_sha256 == $expected_runtime_env_sha256
        else
          .runtime_env_repair_attempted == false and
          .runtime_env_created == false and
          .runtime_env_created_identity == "" and
          (.runtime_env_admission_identity |
            test("^[0-9]+:[0-9]+$")) and
          .runtime_env_persistence_verified == false and
          .runtime_env_source == "existing" and
          (.runtime_env_sha256 | test("^[0-9a-f]{64}$"))
        end
      ) and
      .after_status == "active" and
      .health_status == "healthy" and
      .health_validator_id == $validator_id and
      (.attempts | type) == "number" and
      .attempts >= 1 and
      .attempts <= 60 and
      .accepted == true and
      .mainnet_changed == false and
      .assets_moved == false and
      .bridge_activated == false and
      .mainnet_activation_authorized == false
    ' "$evidence_path" >/dev/null
}

ensure_validator_service_available() {
  local validator_id="$1"
  local instance_id="$2"
  local expected_ami_id="$3"
  local expected_runtime_version="$4"
  local genesis_sha256="$5"
  local signer_arn="$6"
  local signer_bindings="$7"
  local peer_endpoints="$8"
  local automatic_finality_enabled="$9"
  shift 9
  local block_interval_seconds="$1"
  local slot_epoch_seconds="$2"
  local expected_state_volume_id="$3"
  local allow_runtime_env_repair="$4"
  local output_path="$5"
  local recovery_command
  local canonical_runtime_b64
  local canonical_runtime_env_sha256
  local recovery_request_sha256
  local command_id
  local invocation
  local ami_id
  [[ "$expected_ami_id" =~ ^ami-[0-9a-f]{8,17}$ ]]
  [[ "$expected_runtime_version" =~ ^[0-9a-f]{64}$ ]]
  [[ "$genesis_sha256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$expected_state_volume_id" =~ ^vol-[0-9a-f]{8,17}$ ]]
  case "$allow_runtime_env_repair" in
    true|false) ;;
    *) return 2 ;;
  esac
  [[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]]
  [[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]
  [[ "$REQUEST_SHA256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$MANIFEST_DECISION_SHA256" =~ ^[0-9a-f]{64}$ ]]
  [[ "$ROLLING_CANDIDATE_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]
  canonical_runtime_b64="$(
    render_canonical_validator_runtime_env \
      "$validator_id" "$expected_runtime_version" "$genesis_sha256" \
      "$signer_arn" "$signer_bindings" "$peer_endpoints" \
      "$automatic_finality_enabled" "$block_interval_seconds" \
      "$slot_epoch_seconds" |
      base64 -w0
  )"
  canonical_runtime_env_sha256="$(
    render_canonical_validator_runtime_env \
      "$validator_id" "$expected_runtime_version" "$genesis_sha256" \
      "$signer_arn" "$signer_bindings" "$peer_endpoints" \
      "$automatic_finality_enabled" "$block_interval_seconds" \
      "$slot_epoch_seconds" |
      sha256sum |
      awk '{print $1}'
  )"
  recovery_request_sha256="$(
    jq -cnS \
      --arg validator_id "$validator_id" \
      --arg instance_id "$instance_id" \
      --arg ami_id "$expected_ami_id" \
      --arg runtime_sha256 "$expected_runtime_version" \
      --arg runtime_env_sha256 "$canonical_runtime_env_sha256" \
      --arg genesis_sha256 "$genesis_sha256" \
      --arg state_volume_id "$expected_state_volume_id" \
      --arg source_commit "$SOURCE_COMMIT" \
      --argjson recovery_run_id "$GITHUB_RUN_ID" \
      --argjson recovery_run_attempt "$GITHUB_RUN_ATTEMPT" \
      --arg release_request_sha256 "$REQUEST_SHA256" \
      --arg manifest_decision_sha256 "$MANIFEST_DECISION_SHA256" \
      --arg candidate_head_sha "$ROLLING_CANDIDATE_HEAD_SHA" \
      --argjson allow_runtime_env_repair "$allow_runtime_env_repair" '{
        schema_version: "junca-validator-service-recovery-request/v2",
        validator_id: $validator_id,
        instance_id: $instance_id,
        ami_id: $ami_id,
        runtime_sha256: $runtime_sha256,
        runtime_env_sha256: $runtime_env_sha256,
        genesis_sha256: $genesis_sha256,
        state_volume_id: $state_volume_id,
        source_commit: $source_commit,
        recovery_run_id: $recovery_run_id,
        recovery_run_attempt: $recovery_run_attempt,
        release_request_sha256: $release_request_sha256,
        manifest_decision_sha256: $manifest_decision_sha256,
        candidate_head_sha: $candidate_head_sha,
        allow_runtime_env_repair: $allow_runtime_env_repair,
        recovery_dispatch_sequence: 1
      }' |
      sha256sum |
      awk '{print $1}'
  )"
  wait_for_ssm_online \
    "$instance_id" \
    "artifacts/ssm-online-service-recovery-${validator_id}-${instance_id}.json"
  ami_id="$(
    aws ec2 describe-instances \
      --instance-ids "$instance_id" \
      --query 'Reservations[0].Instances[0].ImageId' \
      --output text
  )"
  test "$ami_id" = "$expected_ami_id"
  recovery_command="$(
    printf 'expected_runtime_version=%q\n' "$expected_runtime_version"
    printf 'expected_genesis_sha256=%q\n' "$genesis_sha256"
    printf 'expected_validator_id=%q\n' "$validator_id"
    printf 'expected_signer_arn=%q\n' "$signer_arn"
    printf 'expected_signer_bindings=%q\n' "$signer_bindings"
    printf 'expected_peer_endpoints=%q\n' "$peer_endpoints"
    printf 'expected_automatic_finality_enabled=%q\n' \
      "$automatic_finality_enabled"
    printf 'expected_block_interval_seconds=%q\n' "$block_interval_seconds"
    printf 'expected_slot_epoch_seconds=%q\n' "$slot_epoch_seconds"
    printf 'expected_state_volume_id=%q\n' "$expected_state_volume_id"
    printf 'expected_genesis_sha256=%q\n' "$genesis_sha256"
    printf 'expected_source_commit=%q\n' "$SOURCE_COMMIT"
    printf 'expected_recovery_request_sha256=%q\n' \
      "$recovery_request_sha256"
    printf 'recovery_dispatch_sequence=%q\n' 1
    printf 'recovery_run_id=%q\n' "$GITHUB_RUN_ID"
    printf 'recovery_run_attempt=%q\n' "$GITHUB_RUN_ATTEMPT"
    printf 'release_request_sha256=%q\n' "$REQUEST_SHA256"
    printf 'manifest_decision_sha256=%q\n' "$MANIFEST_DECISION_SHA256"
    printf 'candidate_head_sha=%q\n' "$ROLLING_CANDIDATE_HEAD_SHA"
    printf 'allow_runtime_env_repair=%q\n' "$allow_runtime_env_repair"
    printf 'canonical_runtime_b64=%q\n' "$canonical_runtime_b64"
    printf 'canonical_runtime_env_sha256=%q\n' \
      "$canonical_runtime_env_sha256"
    cat <<'EOF'
set -u -o pipefail
before_status="$(systemctl is-active junca-validator.service 2>/dev/null || true)"
pre_repair_health_status=""
pre_repair_validator_id=""
controlled_active_repair=false
controlled_stop_attempted=false
controlled_stop_exit=0
controlled_stop_verified=false
repair_status_admitted=false
restart_attempted=false
durable_mount_verified=false
durable_mount_volume_id="$expected_state_volume_id"
durable_mount_device=""
durable_mount_source=""
durable_mount_filesystem=""
durable_mount_persistence_verified=false
durable_mount_repair_attempted=false
durable_mount_repaired=false
durable_mount_repair_exit=0
durable_mount_repair_stage=not_attempted
unmounted_state_target_entries=
scan_rollbacks_quarantined=false
scan_rollbacks_quarantine_path=
scan_rollbacks_manifest_sha256=
state_store_integrity=false
state_path_access_verified=false
state_path_access_repair_attempted=false
state_path_access_repaired=false
state_directory_owner=""
state_directory_mode=""
state_file_owner=""
state_file_mode=""
state_file_link_count=0
state_auxiliary_file_count=0
binary_artifact_verified=false
genesis_verified=false
system_identity_verified=false
system_identity_repair_attempted=false
system_identity_repaired=false
system_identity_uid=0
system_identity_gid=0
runtime_config_access_verified=false
runtime_config_repair_attempted=false
runtime_config_repaired=false
runtime_directory_owner=""
runtime_directory_mode=""
genesis_owner=""
genesis_mode=""
genesis_link_count=0
validator_config_owner=""
validator_config_mode=""
validator_config_link_count=0
validator_config_admissible=false
validator_config_preexisting=false
validator_config_pre_identity=""
validator_config_pre_sha256=""
validator_config_pre_size=0
validator_config_identity=""
validator_config_sha256=""
validator_config_size=0
runtime_directory_verified=false
runtime_env_verified=false
runtime_version=""
runtime_env_repair_attempted=false
runtime_env_created=false
runtime_env_created_identity=""
runtime_env_admission_identity=""
runtime_env_owner=""
runtime_env_mode=""
runtime_env_link_count=0
runtime_env_schema_verified=false
runtime_env_required_assignment_count=0
runtime_env_repaired=false
runtime_env_persistence_verified=false
runtime_env_post_restart_verified=false
runtime_env_repair_admissible=false
runtime_env_target_admitted=false
runtime_env_preexisting=false
runtime_env_pre_identity=""
runtime_env_pre_sha256=""
runtime_env_pre_size=0
runtime_env_pre_owner=""
runtime_env_pre_mode=""
runtime_env_backup_created=false
runtime_env_backup_path=""
runtime_env_replaced=false
repair_rollback_attempted=false
repair_rollback_succeeded=false
repair_rollback_persistence_verified=false
containment_restart_attempted=false
containment_restart_exit=0
containment_health_status=""
containment_recovered=false
runtime_env_source=""
runtime_env_sha256=""
service_stop_exit=0
restart_exit=0
after_status="$before_status"
health_status=""
health_validator_id=""
attempts=1
accepted=false
if [[ "$before_status" != "active" ]]; then
  repair_status_admitted=true
fi

runtime_env_has_exact_assignment() {
  local path="$1"
  local key="$2"
  local expected="$3"
  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]]
  [[ "$(
    awk -v key="$key" '
      $0 ~ "^[[:space:]]*" key "[[:space:]]*=" { count++ }
      END { print count + 0 }
    ' "$path"
  )" == 1 ]] &&
    grep -Fxq "${key}=${expected}" "$path"
}

runtime_env_has_only_canonical_assignments() {
  local path="$1"
  awk '
    BEGIN {
      split("CHAIN_NAME GOVERNANCE NETWORK_NOTICE VALIDATOR_ID CHAIN_ID GENESIS_SHA256 NODE_ARTIFACT_SHA256 SIGNER_RESOURCE_ARN AWS_REGION AWS_DEFAULT_REGION PUBLIC_RPC P2P_PORT VALIDATOR_SIGNER_BINDINGS VALIDATOR_PEER_ENDPOINTS AUTOMATIC_FINALITY_ENABLED TESTNET_BLOCK_INTERVAL_SECONDS TESTNET_SLOT_EPOCH_SECONDS BRIDGE_ACTIVATED", names, " ")
      for (item_index in names) {
        canonical[names[item_index]] = 1
      }
    }
    /^[[:space:]]*($|#)/ { next }
    {
      line = $0
      sub(/^[[:space:]]*/, "", line)
      if (line !~ /^[A-Z][A-Z0-9_]*=/) {
        exit 1
      }
      key = line
      sub(/=.*/, "", key)
      if (!(key in canonical)) {
        exit 1
      }
      count++
    }
    END {
      if (count != 18) {
        exit 1
      }
    }
  ' "$path"
}

verify_runtime_env_schema() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] &&
    runtime_env_has_only_canonical_assignments "$path" &&
    runtime_env_has_exact_assignment \
      "$path" CHAIN_NAME "JUNCA Social Ecosystem Chain" &&
    runtime_env_has_exact_assignment \
      "$path" GOVERNANCE "JAIOS Institutional Governance" &&
    runtime_env_has_exact_assignment \
      "$path" NETWORK_NOTICE "Public Testnet / No Monetary Value" &&
    runtime_env_has_exact_assignment \
      "$path" VALIDATOR_ID "$expected_validator_id" &&
    runtime_env_has_exact_assignment "$path" CHAIN_ID 20260723 &&
    runtime_env_has_exact_assignment \
      "$path" GENESIS_SHA256 "$expected_genesis_sha256" &&
    runtime_env_has_exact_assignment \
      "$path" NODE_ARTIFACT_SHA256 "$expected_runtime_version" &&
    runtime_env_has_exact_assignment \
      "$path" SIGNER_RESOURCE_ARN "$expected_signer_arn" &&
    runtime_env_has_exact_assignment "$path" AWS_REGION us-east-1 &&
    runtime_env_has_exact_assignment "$path" AWS_DEFAULT_REGION us-east-1 &&
    runtime_env_has_exact_assignment "$path" PUBLIC_RPC false &&
    runtime_env_has_exact_assignment "$path" P2P_PORT 30303 &&
    runtime_env_has_exact_assignment \
      "$path" VALIDATOR_SIGNER_BINDINGS "$expected_signer_bindings" &&
    runtime_env_has_exact_assignment \
      "$path" VALIDATOR_PEER_ENDPOINTS "$expected_peer_endpoints" &&
    runtime_env_has_exact_assignment \
      "$path" AUTOMATIC_FINALITY_ENABLED \
      "$expected_automatic_finality_enabled" &&
    runtime_env_has_exact_assignment \
      "$path" TESTNET_BLOCK_INTERVAL_SECONDS \
      "$expected_block_interval_seconds" &&
    runtime_env_has_exact_assignment \
      "$path" TESTNET_SLOT_EPOCH_SECONDS "$expected_slot_epoch_seconds" &&
    runtime_env_has_exact_assignment "$path" BRIDGE_ACTIVATED false
}

pin_repairable_runtime_env() {
  local path="$1"
  local identity=""
  local digest=""
  local size=""
  local owner=""
  local mode=""
  [[ -f "$path" && ! -L "$path" ]] || return 1
  [[ "$(stat -c '%U' "$path")" == root ]] || return 1
  [[ "$(stat -c '%G' "$path")" =~ ^(root|junca)$ ]] || return 1
  [[ "$(stat -c '%a' "$path")" =~ ^(600|640|644)$ ]] || return 1
  [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
  runtime_env_has_only_canonical_assignments "$path" || return 1
  identity="$(stat -Lc '%d:%i' "$path")" || return 1
  digest="$(sha256sum "$path" | awk '{print $1}')" || return 1
  size="$(stat -c '%s' "$path")" || return 1
  owner="$(stat -c '%U:%G' "$path")" || return 1
  mode="$(stat -c '%a' "$path")" || return 1
  [[ "$identity" =~ ^[0-9]+:[0-9]+$ ]] || return 1
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || return 1
  [[ "$size" =~ ^[0-9]+$ && "$size" -le 8192 ]] || return 1
  runtime_env_repair_admissible=true
  runtime_env_preexisting=true
  runtime_env_pre_identity="$identity"
  runtime_env_pre_sha256="$digest"
  runtime_env_pre_size="$size"
  runtime_env_pre_owner="$owner"
  runtime_env_pre_mode="$mode"
}

pin_existing_validator_config() {
  local path="$1"
  local identity=""
  local digest=""
  local size=""
  [[ -f "$path" && ! -L "$path" ]] || return 1
  [[ "$(stat -c '%U' "$path")" == "root" ]] || return 1
  [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
  identity="$(stat -Lc '%d:%i' "$path")" || return 1
  digest="$(sha256sum "$path" | awk '{print $1}')" || return 1
  size="$(stat -c '%s' "$path")" || return 1
  [[ "$identity" =~ ^[0-9]+:[0-9]+$ ]] || return 1
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || return 1
  [[ "$size" =~ ^[0-9]+$ ]] || return 1
  validator_config_preexisting=true
  validator_config_pre_identity="$identity"
  validator_config_pre_sha256="$digest"
  validator_config_pre_size="$size"
}

validator_config_matches_admission() {
  local path="$1"
  if [[ "$validator_config_preexisting" == true ]]; then
    [[ -f "$path" && ! -L "$path" ]] || return 1
    [[ "$(stat -c '%U' "$path")" == "root" ]] || return 1
    [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
    [[ "$(stat -Lc '%d:%i' "$path")" == \
      "$validator_config_pre_identity" ]] || return 1
    [[ "$(sha256sum "$path" | awk '{print $1}')" == \
      "$validator_config_pre_sha256" ]] || return 1
    [[ "$(stat -c '%s' "$path")" == "$validator_config_pre_size" ]] ||
      return 1
    return 0
  else
    [[ ! -e "$path" && ! -L "$path" ]] || return 1
  fi
}

admit_controlled_active_repair() {
  if [[ "$repair_status_admitted" == true ]]; then
    return 0
  fi
  [[ "$before_status" == "active" ]] || return 1
  [[ "$pre_repair_health_status" == "healthy" ]] || return 1
  [[ "$pre_repair_validator_id" == "$expected_validator_id" ]] || return 1
  [[ "$durable_mount_verified" == true ]] || return 1
  [[ "$state_store_integrity" == true ]] || return 1
  [[ "$binary_artifact_verified" == true ]] || return 1
  [[ "$genesis_verified" == true ]] || return 1
  controlled_active_repair=true
  controlled_stop_attempted=true
  systemctl stop junca-validator.service || controlled_stop_exit=$?
  if [[ "$controlled_stop_exit" == 0 ]] &&
      ! systemctl is-active --quiet junca-validator.service; then
    controlled_stop_verified=true
    repair_status_admitted=true
    return 0
  fi
  return 1
}

verify_junca_system_identity() {
  local passwd_entry=""
  local group_entry=""
  local passwd_name=""
  local passwd_uid=""
  local passwd_gid=""
  local passwd_home=""
  local passwd_shell=""
  local group_name=""
  local group_gid=""
  passwd_entry="$(getent passwd junca 2>/dev/null || true)"
  group_entry="$(getent group junca 2>/dev/null || true)"
  [[ -n "$passwd_entry" && -n "$group_entry" ]] || return 1
  IFS=: read -r passwd_name _ passwd_uid passwd_gid _ passwd_home \
    passwd_shell <<<"$passwd_entry"
  IFS=: read -r group_name _ group_gid _ <<<"$group_entry"
  [[ "$passwd_name" == junca ]] || return 1
  [[ "$passwd_uid" == 992 ]] || return 1
  [[ "$passwd_gid" == 992 ]] || return 1
  [[ "$passwd_home" == /var/lib/junca ]] || return 1
  [[ "$passwd_shell" == /sbin/nologin ]] || return 1
  [[ "$group_name" == junca ]] || return 1
  [[ "$group_gid" == 992 ]] || return 1
  [[ "$(getent passwd 992 2>/dev/null || true)" == "$passwd_entry" ]] ||
    return 1
  [[ "$(getent group 992 2>/dev/null || true)" == "$group_entry" ]] ||
    return 1
  system_identity_uid=992
  system_identity_gid=992
  system_identity_verified=true
}

ensure_junca_system_identity() {
  local passwd_entry=""
  local group_entry=""
  local group_name=""
  local group_gid=""
  if verify_junca_system_identity; then
    return 0
  fi
  system_identity_repair_attempted=true
  passwd_entry="$(getent passwd junca 2>/dev/null || true)"
  group_entry="$(getent group junca 2>/dev/null || true)"
  [[ -z "$passwd_entry" ]] || return 1
  if [[ -n "$group_entry" ]]; then
    IFS=: read -r group_name _ group_gid _ <<<"$group_entry"
    [[ "$group_name" == junca && "$group_gid" == 992 ]] || return 1
  else
    [[ -z "$(getent group 992 2>/dev/null || true)" ]] || return 1
    groupadd --system --gid 992 junca || return 1
  fi
  [[ -z "$(getent passwd 992 2>/dev/null || true)" ]] || return 1
  useradd --system --uid 992 --gid 992 --home-dir /var/lib/junca \
    --shell /sbin/nologin --no-create-home junca || return 1
  verify_junca_system_identity || return 1
  system_identity_repaired=true
}

admit_state_path_access_repair() {
  local state_root="$1"
  local service_uid="$2"
  local service_gid="$3"
  local root_device=""
  local path=""
  local path_uid=""
  local path_gid=""
  local path_mode=""
  [[ "$service_uid" =~ ^[0-9]+$ && "$service_gid" =~ ^[0-9]+$ ]] ||
    return 1
  [[ -d "$state_root" && ! -L "$state_root" ]] || return 1
  [[ -f "$state_root/state.sqlite" &&
    ! -L "$state_root/state.sqlite" ]] || return 1
  root_device="$(stat -c '%d' "$state_root")" || return 1
  [[ "$root_device" =~ ^[0-9]+$ ]] || return 1
  path_uid="$(stat -c '%u' "$state_root")" || return 1
  path_gid="$(stat -c '%g' "$state_root")" || return 1
  path_mode="$(stat -c '%a' "$state_root")" || return 1
  [[ "$path_uid" == 0 || "$path_uid" == "$service_uid" ]] || return 1
  [[ "$path_gid" == 0 || "$path_gid" == "$service_gid" ]] || return 1
  [[ "$path_mode" =~ ^(700|710|750|755)$ ]] || return 1
  for path in \
    "$state_root/state.sqlite" \
    "$state_root/state.sqlite-wal" \
    "$state_root/state.sqlite-shm" \
    "$state_root/consensus-signing.sqlite" \
    "$state_root/consensus-signing.sqlite-wal" \
    "$state_root/consensus-signing.sqlite-shm"; do
    if [[ ! -e "$path" && ! -L "$path" ]]; then
      [[ "$path" != "$state_root/state.sqlite" ]] || return 1
      continue
    fi
    [[ -f "$path" && ! -L "$path" ]] || return 1
    [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
    [[ "$(stat -c '%d' "$path")" == "$root_device" ]] || return 1
    path_uid="$(stat -c '%u' "$path")" || return 1
    path_gid="$(stat -c '%g' "$path")" || return 1
    path_mode="$(stat -c '%a' "$path")" || return 1
    [[ "$path_uid" == 0 || "$path_uid" == "$service_uid" ]] || return 1
    [[ "$path_gid" == 0 || "$path_gid" == "$service_gid" ]] || return 1
    [[ "$path_mode" =~ ^(600|640|644)$ ]] || return 1
  done
}

verify_state_path_access() {
  local path=""
  local auxiliary_count=0
  local quick_check=""
  local signing_journal_quick_check=""
  [[ "$system_identity_verified" == true ]] || return 1
  [[ "$durable_mount_verified" == true ]] || return 1
  [[ -d /var/lib/junca && ! -L /var/lib/junca ]] || return 1
  [[ "$(stat -c '%U:%G' /var/lib/junca)" == junca:junca ]] || return 1
  [[ "$(stat -c '%a' /var/lib/junca)" =~ ^(700|710|750|755)$ ]] ||
    return 1
  for path in \
    /var/lib/junca/state.sqlite \
    /var/lib/junca/state.sqlite-wal \
    /var/lib/junca/state.sqlite-shm \
    /var/lib/junca/consensus-signing.sqlite \
    /var/lib/junca/consensus-signing.sqlite-wal \
    /var/lib/junca/consensus-signing.sqlite-shm; do
    if [[ ! -e "$path" && ! -L "$path" ]]; then
      [[ "$path" != /var/lib/junca/state.sqlite ]] || return 1
      continue
    fi
    [[ -f "$path" && ! -L "$path" ]] || return 1
    [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
    [[ "$(stat -c '%d' "$path")" == \
      "$(stat -c '%d' /var/lib/junca)" ]] || return 1
    [[ "$(stat -c '%U:%G' "$path")" == junca:junca ]] || return 1
    [[ "$(stat -c '%a' "$path")" =~ ^(600|640|644)$ ]] || return 1
    runuser -u junca -- test -r "$path" || return 1
    runuser -u junca -- test -w "$path" || return 1
    if [[ "$path" != /var/lib/junca/state.sqlite ]]; then
      auxiliary_count=$((auxiliary_count + 1))
    fi
  done
  runuser -u junca -- test -x /var/lib/junca || return 1
  runuser -u junca -- test -w /var/lib/junca || return 1
  runuser -u junca -- test -r /var/lib/junca/state.sqlite || return 1
  runuser -u junca -- test -w /var/lib/junca/state.sqlite || return 1
  quick_check="$(
    runuser -u junca -- python3 -c \
      'import sqlite3; connection=sqlite3.connect("file:/var/lib/junca/state.sqlite?mode=rw", uri=True); connection.execute("PRAGMA query_only=ON"); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()' \
      2>/dev/null || true
  )"
  [[ "$quick_check" == ok ]] || return 1
  if [[ -f /var/lib/junca/consensus-signing.sqlite &&
        ! -L /var/lib/junca/consensus-signing.sqlite ]]; then
    signing_journal_quick_check="$(
      runuser -u junca -- python3 -c \
        'import sqlite3; connection=sqlite3.connect("file:/var/lib/junca/consensus-signing.sqlite?mode=rw", uri=True); connection.execute("PRAGMA query_only=ON"); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()' \
        2>/dev/null || true
    )"
    [[ "$signing_journal_quick_check" == ok ]] || return 1
  fi
  state_directory_owner="$(stat -c '%U:%G' /var/lib/junca)"
  state_directory_mode="$(stat -c '%a' /var/lib/junca)"
  state_file_owner="$(stat -c '%U:%G' /var/lib/junca/state.sqlite)"
  state_file_mode="$(stat -c '%a' /var/lib/junca/state.sqlite)"
  state_file_link_count="$(stat -c '%h' /var/lib/junca/state.sqlite)"
  state_auxiliary_file_count="$auxiliary_count"
  state_path_access_verified=true
}

repair_state_path_access() {
  local path=""
  local -a paths=(/var/lib/junca/state.sqlite)
  local -a identities=()
  local index=0
  [[ "$repair_status_admitted" == true ]] || return 1
  [[ "$durable_mount_verified" == true ]] || return 1
  [[ "$state_store_integrity" == true ]] || return 1
  [[ "$system_identity_verified" == true ]] || return 1
  state_path_access_repair_attempted=true
  systemctl stop junca-validator.service || service_stop_exit=$?
  [[ "$service_stop_exit" == 0 ]] || return 1
  ! systemctl is-active --quiet junca-validator.service || return 1
  admit_state_path_access_repair /var/lib/junca \
    "$system_identity_uid" "$system_identity_gid" || return 1
  for path in \
    /var/lib/junca/state.sqlite-wal \
    /var/lib/junca/state.sqlite-shm \
    /var/lib/junca/consensus-signing.sqlite \
    /var/lib/junca/consensus-signing.sqlite-wal \
    /var/lib/junca/consensus-signing.sqlite-shm; do
    if [[ -e "$path" || -L "$path" ]]; then
      paths+=("$path")
    fi
  done
  identities+=("$(stat -Lc '%d:%i:%s' /var/lib/junca)")
  for path in "${paths[@]}"; do
    identities+=("$(stat -Lc '%d:%i:%s' "$path")")
  done
  chown junca:junca /var/lib/junca "${paths[@]}"
  chmod 0750 /var/lib/junca
  chmod 0600 "${paths[@]}"
  for path in "${paths[@]}"; do
    sync -f "$path"
  done
  sync -f /var/lib/junca
  [[ "$(stat -Lc '%d:%i:%s' /var/lib/junca)" == "${identities[0]}" ]] ||
    return 1
  for index in "${!paths[@]}"; do
    [[ "$(stat -Lc '%d:%i:%s' "${paths[$index]}")" == \
      "${identities[$((index + 1))]}" ]] || return 1
  done
  verify_state_path_access || return 1
  state_path_access_repaired=true
}

verify_durable_mount_persistence_contract() (
  set -euo pipefail
  local helper_path=/usr/local/sbin/junca-mount-validator-state
  local override_dir=/etc/systemd/system/junca-validator.service.d
  local override_path="$override_dir/validator-state.conf"
  local unit_path=/etc/systemd/system/junca-validator-state.service
  local expected_helper
  local expected_override
  local expected_unit
  local expected_state_serial="${expected_state_volume_id//-/}"
  expected_helper="$(mktemp /tmp/junca-mount-validator-state.XXXXXX)"
  expected_override="$(mktemp /tmp/junca-validator-state-override.XXXXXX)"
  expected_unit="$(mktemp /tmp/junca-validator-state.service.XXXXXX)"
  trap 'rm -f "$expected_helper" "$expected_override" "$expected_unit"' EXIT
  cat >"$expected_helper" <<STATE_HELPER_EOF
#!/usr/bin/env bash
set -euo pipefail
volume_id='${expected_state_volume_id}'
expected_serial='${expected_state_serial}'
device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_\${expected_serial}"
for attempt in \$(seq 1 120); do
  if [[ -b "\$device" ]]; then
    break
  fi
  mapfile -t candidates < <(
    lsblk -dnpo NAME,SERIAL,TYPE |
      awk -v expected="\$expected_serial" \
        '{ serial=\$2; gsub(/-/, "", serial); if (\$3 == "disk" && serial == expected) print \$1 }'
  )
  if [[ "\${#candidates[@]}" == 1 && -b "\${candidates[0]}" ]]; then
    device="\${candidates[0]}"
    break
  fi
  test "\$attempt" -lt 120
  sleep 5
done
[[ -b "\$device" ]]
resolved_device="\$(readlink -f "\$device")"
[[ -b "\$resolved_device" ]]
actual_serial="\$(lsblk -ndo SERIAL "\$device" | tr -d '-')"
test "\$actual_serial" = "\$expected_serial"
filesystem="\$(blkid -o value -s TYPE "\$device")"
case "\$filesystem" in
  ext4|xfs) ;;
  *) echo "validator state filesystem is absent or unapproved" >&2; exit 1 ;;
esac
if ! mountpoint -q /var/lib/junca; then
  mount -o noatime,nosuid,nodev "\$device" /var/lib/junca
fi
test "\$(findmnt -n -o SOURCE --target /var/lib/junca)" = "\$resolved_device"
test -f /var/lib/junca/state.sqlite
test ! -L /var/lib/junca/state.sqlite
STATE_HELPER_EOF
  cat >"$expected_unit" <<'STATE_UNIT_EOF'
[Unit]
Description=JUNCA Validator Durable State Mount
Before=junca-validator.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/junca-mount-validator-state
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
STATE_UNIT_EOF
  cat >"$expected_override" <<'STATE_OVERRIDE_EOF'
[Unit]
Requires=junca-validator-state.service
After=junca-validator-state.service
RequiresMountsFor=/var/lib/junca
ConditionPathIsMountPoint=/var/lib/junca
ConditionPathExists=/var/lib/junca/state.sqlite
STATE_OVERRIDE_EOF
  [[ -f "$helper_path" && ! -L "$helper_path" ]] &&
    [[ "$(stat -c '%U:%G' "$helper_path")" == "root:root" ]] &&
    [[ "$(stat -c '%a' "$helper_path")" == "750" ]] &&
    [[ "$(stat -c '%h' "$helper_path")" == 1 ]] &&
    cmp -s "$expected_helper" "$helper_path"
  [[ -f "$unit_path" && ! -L "$unit_path" ]] &&
    [[ "$(stat -c '%U:%G' "$unit_path")" == "root:root" ]] &&
    [[ "$(stat -c '%a' "$unit_path")" == "640" ]] &&
    [[ "$(stat -c '%h' "$unit_path")" == 1 ]] &&
    cmp -s "$expected_unit" "$unit_path"
  [[ -d "$override_dir" && ! -L "$override_dir" ]] &&
    [[ "$(stat -c '%U:%G' "$override_dir")" == "root:root" ]] &&
    [[ "$(stat -c '%a' "$override_dir")" == "755" ]]
  [[ -f "$override_path" && ! -L "$override_path" ]] &&
    [[ "$(stat -c '%U:%G' "$override_path")" == "root:root" ]] &&
    [[ "$(stat -c '%a' "$override_path")" == "640" ]] &&
    [[ "$(stat -c '%h' "$override_path")" == 1 ]] &&
    cmp -s "$expected_override" "$override_path"
  systemctl is-enabled --quiet junca-validator-state.service
)

repair_durable_mount_persistence_contract() (
  set -euo pipefail
  local helper_path=/usr/local/sbin/junca-mount-validator-state
  local override_dir=/etc/systemd/system/junca-validator.service.d
  local override_path="$override_dir/validator-state.conf"
  local unit_path=/etc/systemd/system/junca-validator-state.service
  local helper_tmp
  local override_tmp
  local unit_tmp
  local expected_state_serial="${expected_state_volume_id//-/}"
  for path in "$helper_path" "$unit_path" "$override_path"; do
    if [[ -e "$path" || -L "$path" ]]; then
      [[ -f "$path" && ! -L "$path" ]] || return 1
      [[ "$(stat -c '%U:%G' "$path")" == root:root ]] || return 1
      [[ "$(stat -c '%h' "$path")" == 1 ]] || return 1
    fi
  done
  if [[ -e "$override_dir" || -L "$override_dir" ]]; then
    [[ -d "$override_dir" && ! -L "$override_dir" ]] || return 1
    [[ "$(stat -c '%U:%G' "$override_dir")" == root:root ]] || return 1
  else
    install -d -m 0755 -o root -g root "$override_dir"
  fi
  chmod 0755 "$override_dir"
  helper_tmp="$(mktemp /usr/local/sbin/.junca-mount-validator-state.XXXXXX)"
  override_tmp="$(mktemp "$override_dir/.validator-state.conf.XXXXXX")"
  unit_tmp="$(mktemp /etc/systemd/system/.junca-validator-state.service.XXXXXX)"
  trap 'rm -f "$helper_tmp" "$override_tmp" "$unit_tmp"' EXIT
  cat >"$helper_tmp" <<STATE_HELPER_EOF
#!/usr/bin/env bash
set -euo pipefail
volume_id='${expected_state_volume_id}'
expected_serial='${expected_state_serial}'
device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_\${expected_serial}"
for attempt in \$(seq 1 120); do
  if [[ -b "\$device" ]]; then
    break
  fi
  mapfile -t candidates < <(
    lsblk -dnpo NAME,SERIAL,TYPE |
      awk -v expected="\$expected_serial" \
        '{ serial=\$2; gsub(/-/, "", serial); if (\$3 == "disk" && serial == expected) print \$1 }'
  )
  if [[ "\${#candidates[@]}" == 1 && -b "\${candidates[0]}" ]]; then
    device="\${candidates[0]}"
    break
  fi
  test "\$attempt" -lt 120
  sleep 5
done
[[ -b "\$device" ]]
resolved_device="\$(readlink -f "\$device")"
[[ -b "\$resolved_device" ]]
actual_serial="\$(lsblk -ndo SERIAL "\$device" | tr -d '-')"
test "\$actual_serial" = "\$expected_serial"
filesystem="\$(blkid -o value -s TYPE "\$device")"
case "\$filesystem" in
  ext4|xfs) ;;
  *) echo "validator state filesystem is absent or unapproved" >&2; exit 1 ;;
esac
if ! mountpoint -q /var/lib/junca; then
  mount -o noatime,nosuid,nodev "\$device" /var/lib/junca
fi
test "\$(findmnt -n -o SOURCE --target /var/lib/junca)" = "\$resolved_device"
test -f /var/lib/junca/state.sqlite
test ! -L /var/lib/junca/state.sqlite
STATE_HELPER_EOF
  cat >"$unit_tmp" <<'STATE_UNIT_EOF'
[Unit]
Description=JUNCA Validator Durable State Mount
Before=junca-validator.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/junca-mount-validator-state
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
STATE_UNIT_EOF
  cat >"$override_tmp" <<'STATE_OVERRIDE_EOF'
[Unit]
Requires=junca-validator-state.service
After=junca-validator-state.service
RequiresMountsFor=/var/lib/junca
ConditionPathIsMountPoint=/var/lib/junca
ConditionPathExists=/var/lib/junca/state.sqlite
STATE_OVERRIDE_EOF
  chown root:root "$helper_tmp" "$override_tmp" "$unit_tmp"
  chmod 0750 "$helper_tmp"
  chmod 0640 "$override_tmp"
  chmod 0640 "$unit_tmp"
  sync -f "$helper_tmp"
  sync -f "$override_tmp"
  sync -f "$unit_tmp"
  mv -fT "$helper_tmp" "$helper_path"
  mv -fT "$override_tmp" "$override_path"
  mv -fT "$unit_tmp" "$unit_path"
  trap - EXIT
  sync -f /usr/local/sbin
  sync -f "$override_dir"
  sync -f /etc/systemd/system
  systemctl daemon-reload
  systemctl enable junca-validator-state.service
)

verify_durable_state_mount() {
  local actual_serial
  local expected_device
  local expected_serial
  local filesystem
  local mount_options
  local resolved_device
  local source
  local source_device
  expected_serial="${expected_state_volume_id//-/}"
  expected_device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${expected_serial}"
  if [[ ! -b "$expected_device" ]]; then
    mapfile -t state_device_candidates < <(
      lsblk -dnpo NAME,SERIAL,TYPE |
        awk -v expected="$expected_serial" \
          '{ serial=$2; gsub(/-/, "", serial); if ($3 == "disk" && serial == expected) print $1 }'
    )
    [[ "${#state_device_candidates[@]}" == 1 ]] || return 1
    expected_device="${state_device_candidates[0]}"
  fi
  [[ -b "$expected_device" ]] || return 1
  resolved_device="$(readlink -f "$expected_device")"
  [[ -b "$resolved_device" ]] || return 1
  [[ "$(lsblk -nrpo NAME "$resolved_device" | wc -l)" == 1 ]] || return 1
  actual_serial="$(lsblk -ndo SERIAL "$expected_device" | tr -d '-')"
  [[ "$actual_serial" == "$expected_serial" ]] || return 1
  mountpoint -q /var/lib/junca || return 1
  source="$(findmnt -n -o SOURCE --target /var/lib/junca)"
  source_device="$(readlink -f "$source")"
  [[ "$source_device" == "$resolved_device" ]] || return 1
  filesystem="$(blkid -c /dev/null -o value -s TYPE "$resolved_device")"
  case "$filesystem" in
    ext4|xfs) ;;
    *) return 1 ;;
  esac
  mount_options="$(findmnt -n -o OPTIONS --target /var/lib/junca)"
  grep -Eq '(^|,)noatime(,|$)' <<<"$mount_options" || return 1
  grep -Eq '(^|,)nosuid(,|$)' <<<"$mount_options" || return 1
  grep -Eq '(^|,)nodev(,|$)' <<<"$mount_options" || return 1
  verify_durable_mount_persistence_contract || return 1
  systemctl is-active --quiet junca-validator-state.service || return 1
  durable_mount_device="$resolved_device"
  durable_mount_source="$source_device"
  durable_mount_filesystem="$filesystem"
  durable_mount_persistence_verified=true
  durable_mount_verified=true
}

verify_unmounted_state_target_admission() {
  local entry
  local entry_name
  local entry_count=0
  local sqlite_entry_count=0
  local sqlite_quick_check
  [[ -d /var/lib/junca && ! -L /var/lib/junca ]] || return 1
  ! mountpoint -q /var/lib/junca || return 1
  unmounted_state_target_entries="$(
    find /var/lib/junca -mindepth 1 -maxdepth 1 -printf '%f\n' |
      LC_ALL=C sort |
      paste -sd, -
  )"
  while IFS= read -r -d '' entry; do
    entry_name="${entry##*/}"
    case "$entry_name" in
      state.sqlite|state.sqlite-shm|state.sqlite-wal)
        [[ -f "$entry" && ! -L "$entry" ]] || return 1
        [[ "$(stat -c '%h' "$entry")" == 1 ]] || return 1
        sqlite_entry_count=$((sqlite_entry_count + 1))
        ;;
      scan-rollbacks)
        [[ -d "$entry" && ! -L "$entry" ]] || return 1
        ;;
      *) return 1 ;;
    esac
    entry_count=$((entry_count + 1))
  done < <(
    find /var/lib/junca -mindepth 1 -maxdepth 1 -print0
  )
  if [[ -d /var/lib/junca/scan-rollbacks ]]; then
    quarantine_scan_rollbacks_for_mount \
      /var/lib/junca/scan-rollbacks \
      /var/lib/junca-unmounted-recovery || return 1
  fi
  if [[ "$sqlite_entry_count" -gt 0 ]]; then
    [[ -f /var/lib/junca/state.sqlite &&
      ! -L /var/lib/junca/state.sqlite ]] || return 1
    sqlite_quick_check="$(
      python3 -c \
        'import sqlite3; connection=sqlite3.connect("file:/var/lib/junca/state.sqlite?mode=ro", uri=True); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()' \
        2>/dev/null || true
    )"
    [[ "$sqlite_quick_check" == "ok" ]] || return 1
  fi
}

quarantine_scan_rollbacks_for_mount() {
  local source_path="$1"
  local quarantine_root="$2"
  local destination_path
  local manifest_readback
  local manifest_sha256
  local owner
  [[ "${source_path##*/}" == scan-rollbacks ]] || return 1
  [[ -d "$source_path" && ! -L "$source_path" ]] || return 1
  ! mountpoint -q "$source_path" || return 1
  owner="$(stat -c '%U:%G' "$source_path")"
  [[ "$owner" == root:root || "$owner" == junca:junca ]] || return 1
  manifest_readback="$(
    python3 - "$source_path" <<'PY'
import hashlib
import os
import pwd
import stat
import sys

root = os.path.abspath(sys.argv[1])
root_stat = os.lstat(root)
allowed_uids = {0}
allowed_gids = {0}
try:
    account = pwd.getpwnam("junca")
except KeyError:
    pass
else:
    allowed_uids.add(account.pw_uid)
    allowed_gids.add(account.pw_gid)
records = []
entry_count = 0
total_bytes = 0
for current, directories, files in os.walk(root, topdown=True, followlinks=False):
    for name in sorted(directories + files):
        path = os.path.join(current, name)
        metadata = os.lstat(path)
        if metadata.st_dev != root_stat.st_dev:
            raise SystemExit("cross-device scan-rollbacks entry")
        if stat.S_ISLNK(metadata.st_mode):
            raise SystemExit("scan-rollbacks symlink rejected")
        if metadata.st_uid not in allowed_uids or metadata.st_gid not in allowed_gids:
            raise SystemExit("scan-rollbacks owner rejected")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise SystemExit("scan-rollbacks hard link rejected")
            kind = "f"
            total_bytes += metadata.st_size
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "d"
        else:
            raise SystemExit("scan-rollbacks special entry rejected")
        entry_count += 1
        if entry_count > 1000 or total_bytes > 1073741824:
            raise SystemExit("scan-rollbacks bound exceeded")
        relative = os.path.relpath(path, root)
        records.append(
            "\0".join(
                (
                    relative,
                    kind,
                    str(metadata.st_size),
                    str(metadata.st_uid),
                    str(metadata.st_gid),
                    oct(stat.S_IMODE(metadata.st_mode)),
                )
            ).encode("utf-8", "surrogateescape")
        )
digest = hashlib.sha256(b"\0".join(sorted(records))).hexdigest()
print(f"{entry_count}\t{total_bytes}\t{digest}")
PY
  )" || return 1
  [[ "$manifest_readback" =~ ^[0-9]+$'\t'[0-9]+$'\t'[0-9a-f]{64}$ ]] ||
    return 1
  manifest_sha256="${manifest_readback##*$'\t'}"
  [[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]] || return 1
  if [[ ! -e "$quarantine_root" && ! -L "$quarantine_root" ]]; then
    install -d -m 0700 -o root -g root "$quarantine_root"
  fi
  [[ -d "$quarantine_root" && ! -L "$quarantine_root" ]] || return 1
  [[ "$(stat -c '%U:%G' "$quarantine_root")" == root:root ]] || return 1
  [[ "$(stat -c '%a' "$quarantine_root")" == 700 ]] || return 1
  [[ "$(stat -c '%d' "$source_path")" == \
    "$(stat -c '%d' "$quarantine_root")" ]] || return 1
  destination_path="$quarantine_root/scan-rollbacks-$manifest_sha256"
  [[ ! -e "$destination_path" && ! -L "$destination_path" ]] || return 1
  mv -T "$source_path" "$destination_path"
  sync -f "${source_path%/*}"
  sync -f "$quarantine_root"
  [[ -d "$destination_path" && ! -L "$destination_path" ]] || return 1
  scan_rollbacks_quarantined=true
  scan_rollbacks_quarantine_path="$destination_path"
  scan_rollbacks_manifest_sha256="$manifest_sha256"
}

if ! verify_durable_state_mount &&
    [[ "$allow_runtime_env_repair" == true &&
      "$before_status" != "active" &&
      -d /var/lib/junca &&
      ! -L /var/lib/junca ]] &&
    ! mountpoint -q /var/lib/junca; then
  durable_mount_repair_attempted=true
  durable_mount_repair_stage=service_stop
  systemctl stop junca-validator.service || service_stop_exit=$?
  expected_state_serial="${expected_state_volume_id//-/}"
  expected_state_device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${expected_state_serial}"
  if [[ "$service_stop_exit" == 0 ]] &&
      ! systemctl is-active --quiet junca-validator.service; then
    durable_mount_repair_stage=target_admission
  fi
  if [[ "$durable_mount_repair_stage" == target_admission ]] &&
      verify_unmounted_state_target_admission; then
    durable_mount_repair_stage=device_identity
  fi
  if [[ "$durable_mount_repair_stage" == device_identity &&
        ! -b "$expected_state_device" ]]; then
    mapfile -t state_device_candidates < <(
      lsblk -dnpo NAME,SERIAL,TYPE |
        awk -v expected="$expected_state_serial" \
          '{ serial=$2; gsub(/-/, "", serial); if ($3 == "disk" && serial == expected) print $1 }'
    )
    if [[ "${#state_device_candidates[@]}" == 1 ]]; then
      expected_state_device="${state_device_candidates[0]}"
    fi
  fi
  if [[ "$durable_mount_repair_stage" == device_identity &&
        -b "$expected_state_device" ]]; then
    resolved_state_device="$(readlink -f "$expected_state_device")"
    actual_state_serial="$(
      lsblk -ndo SERIAL "$expected_state_device" |
        tr -d '-'
    )"
    state_filesystem="$(
      blkid -c /dev/null -o value -s TYPE "$resolved_state_device" \
        2>/dev/null || true
    )"
    durable_mount_repair_stage=device_contract
    if [[ -b "$resolved_state_device" &&
          "$(lsblk -nrpo NAME "$resolved_state_device" | wc -l)" == 1 &&
          "$actual_state_serial" == "$expected_state_serial" &&
          -z "$(findmnt -rn -S "$resolved_state_device" -o TARGET)" ]] &&
        [[ "$state_filesystem" == ext4 ||
          "$state_filesystem" == xfs ]]; then
      durable_mount_repair_stage=persistence_contract
    fi
    if [[ "$durable_mount_repair_stage" == persistence_contract ]] &&
        ! verify_durable_mount_persistence_contract; then
      durable_mount_repair_stage=persistence_repair
      repair_durable_mount_persistence_contract || true
    fi
    if [[ "$durable_mount_repair_stage" == persistence_contract ||
          "$durable_mount_repair_stage" == persistence_repair ]] &&
        verify_durable_mount_persistence_contract; then
      durable_mount_repair_stage=mount_restart
      systemctl reset-failed junca-validator-state.service || true
      systemctl restart junca-validator-state.service ||
        durable_mount_repair_exit=$?
      if [[ "$durable_mount_repair_exit" == 0 ]] &&
          verify_durable_state_mount; then
        durable_mount_repaired=true
        durable_mount_repair_stage=verified
      fi
    fi
  fi
fi
if [[ "$durable_mount_verified" == true &&
      -f /var/lib/junca/state.sqlite &&
      ! -L /var/lib/junca/state.sqlite ]]; then
  quick_check="$(python3 -c 'import sqlite3; connection=sqlite3.connect("file:/var/lib/junca/state.sqlite?mode=ro", uri=True); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()' 2>/dev/null || true)"
  if [[ "$quick_check" == "ok" ]]; then
    state_store_integrity=true
  fi
fi
if [[ -f /opt/junca/validator-runtime.tar.gz &&
      ! -L /opt/junca/validator-runtime.tar.gz ]] &&
    printf '%s  %s\n' "$expected_runtime_version" \
      /opt/junca/validator-runtime.tar.gz |
      sha256sum --check --strict >/dev/null 2>&1; then
  binary_artifact_verified=true
fi
if [[ -f /etc/junca/genesis.json && ! -L /etc/junca/genesis.json ]] &&
    [[ "$(stat -c '%h' /etc/junca/genesis.json)" == 1 ]] &&
    printf '%s  %s\n' "$expected_genesis_sha256" /etc/junca/genesis.json |
      sha256sum --check --strict >/dev/null 2>&1; then
  genesis_verified=true
fi
if pin_existing_validator_config /etc/junca/validator.toml; then
  validator_config_admissible=true
elif [[ ! -e /etc/junca/validator.toml &&
        ! -L /etc/junca/validator.toml ]]; then
  validator_config_admissible=true
fi
if [[ "$before_status" == "active" &&
      "$durable_mount_verified" == true &&
      "$state_store_integrity" == true &&
      "$binary_artifact_verified" == true &&
      "$genesis_verified" == true ]] &&
    pre_repair_health="$(
      curl -fsS http://127.0.0.1:8545/health 2>/dev/null
    )"; then
  pre_repair_health_status="$(
    jq -r '.status // empty' <<<"$pre_repair_health" 2>/dev/null || true
  )"
  pre_repair_validator_id="$(
    jq -r '.validator_id // empty' <<<"$pre_repair_health" \
      2>/dev/null || true
  )"
fi
if [[ -d /etc/junca &&
      ! -L /etc/junca &&
      "$(stat -c '%U:%G' /etc/junca)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca)" == "750" &&
      -f /etc/junca/genesis.json &&
      ! -L /etc/junca/genesis.json &&
      "$(stat -c '%U:%G' /etc/junca/genesis.json)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/genesis.json)" == "640" &&
      "$(stat -c '%h' /etc/junca/genesis.json)" == 1 &&
      -f /etc/junca/validator.toml &&
      ! -L /etc/junca/validator.toml &&
      "$(stat -c '%U:%G' /etc/junca/validator.toml)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/validator.toml)" == "640" &&
      "$(stat -c '%h' /etc/junca/validator.toml)" == 1 ]] &&
    runuser -u junca -- test -r /etc/junca/genesis.json &&
    runuser -u junca -- test -r /etc/junca/validator.toml; then
  runtime_config_access_verified=true
fi
if [[ "$runtime_config_access_verified" != true ]]; then
  admit_controlled_active_repair || true
fi
verify_junca_system_identity || true
if [[ "$repair_status_admitted" == true &&
      "$system_identity_verified" != true ]]; then
  ensure_junca_system_identity || true
fi
verify_state_path_access || true
if [[ "$state_path_access_verified" != true &&
      "$repair_status_admitted" != true &&
      "$system_identity_verified" == true ]]; then
  # A live-prefix readback can encounter an exact healthy validator whose
  # runtime configuration is already canonical while its retained state still
  # has legacy root ownership. Enter the same identity-bound controlled stop
  # used by the other bounded repairs before changing only the state allowlist.
  admit_controlled_active_repair || true
fi
if [[ "$state_path_access_verified" != true &&
      "$repair_status_admitted" == true ]]; then
  repair_state_path_access || true
fi
if [[ "$repair_status_admitted" == true &&
      "$genesis_verified" == true &&
      -d /etc/junca &&
      ! -L /etc/junca &&
      "$(stat -c '%U' /etc/junca)" == "root" &&
      "$(stat -c '%a' /etc/junca)" =~ ^(700|710|750|755)$ &&
      -f /etc/junca/genesis.json &&
      ! -L /etc/junca/genesis.json &&
      "$(stat -c '%U' /etc/junca/genesis.json)" == "root" &&
      "$(stat -c '%G' /etc/junca/genesis.json)" =~ ^(root|junca)$ &&
      "$(stat -c '%a' /etc/junca/genesis.json)" =~ ^(600|640|644)$ &&
      "$(stat -c '%h' /etc/junca/genesis.json)" == 1 &&
      "$validator_config_admissible" == true &&
      "$system_identity_verified" == true ]] &&
    validator_config_matches_admission /etc/junca/validator.toml; then
  runtime_config_repair_attempted=true
  chown root:junca /etc/junca
  chmod 0750 /etc/junca
  if [[ ! -e /etc/junca/validator.toml &&
        ! -L /etc/junca/validator.toml ]]; then
    validator_config_tmp="$(mktemp /etc/junca/.validator.toml.XXXXXX)"
    trap 'rm -f "$validator_config_tmp"' EXIT
    chown root:junca "$validator_config_tmp"
    chmod 0640 "$validator_config_tmp"
    if sync -f "$validator_config_tmp" &&
        ln "$validator_config_tmp" /etc/junca/validator.toml &&
        rm -f "$validator_config_tmp"; then
      sync -f /etc/junca
    fi
  fi
  if [[ -f /etc/junca/validator.toml &&
        ! -L /etc/junca/validator.toml &&
        "$(stat -c '%h' /etc/junca/validator.toml)" == 1 ]] &&
      { [[ "$validator_config_preexisting" == false &&
           "$(stat -c '%s' /etc/junca/validator.toml)" == 0 ]] ||
        validator_config_matches_admission /etc/junca/validator.toml; }; then
    chown root:junca /etc/junca/genesis.json /etc/junca/validator.toml
    chmod 0640 /etc/junca/genesis.json /etc/junca/validator.toml
  fi
  if [[ -f /etc/junca/validator.toml &&
      ! -L /etc/junca/validator.toml &&
      "$(stat -c '%h' /etc/junca/validator.toml)" == 1 ]] &&
      sync -f /etc/junca/genesis.json &&
      sync -f /etc/junca/validator.toml &&
      sync -f /etc/junca; then
    validator_config_identity="$(
      stat -Lc '%d:%i' /etc/junca/validator.toml
    )"
    validator_config_sha256="$(
      sha256sum /etc/junca/validator.toml | awk '{print $1}'
    )"
    validator_config_size="$(stat -c '%s' /etc/junca/validator.toml)"
    if [[ "$validator_config_identity" =~ ^[0-9]+:[0-9]+$ &&
          "$validator_config_sha256" =~ ^[0-9a-f]{64}$ &&
          "$validator_config_size" =~ ^[0-9]+$ ]] &&
        { [[ "$validator_config_preexisting" == true &&
             "$validator_config_identity" == \
               "$validator_config_pre_identity" &&
             "$validator_config_sha256" == \
               "$validator_config_pre_sha256" &&
             "$validator_config_size" == "$validator_config_pre_size" ]] ||
          [[ "$validator_config_preexisting" == false &&
             "$validator_config_size" == 0 ]]; }; then
      runtime_config_repaired=true
    fi
  fi
fi
if [[ -d /etc/junca &&
      ! -L /etc/junca &&
      "$(stat -c '%U:%G' /etc/junca)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca)" == "750" &&
      -f /etc/junca/genesis.json &&
      ! -L /etc/junca/genesis.json &&
      "$(stat -c '%U:%G' /etc/junca/genesis.json)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/genesis.json)" == "640" &&
      "$(stat -c '%h' /etc/junca/genesis.json)" == 1 &&
      -f /etc/junca/validator.toml &&
      ! -L /etc/junca/validator.toml &&
      "$(stat -c '%U:%G' /etc/junca/validator.toml)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/validator.toml)" == "640" &&
      "$(stat -c '%h' /etc/junca/validator.toml)" == 1 ]] &&
    runuser -u junca -- test -r /etc/junca/genesis.json &&
    runuser -u junca -- test -r /etc/junca/validator.toml; then
  runtime_directory_verified=true
  runtime_config_access_verified=true
  runtime_directory_owner="$(stat -c '%U:%G' /etc/junca)"
  runtime_directory_mode="$(stat -c '%a' /etc/junca)"
  genesis_owner="$(stat -c '%U:%G' /etc/junca/genesis.json)"
  genesis_mode="$(stat -c '%a' /etc/junca/genesis.json)"
  genesis_link_count="$(stat -c '%h' /etc/junca/genesis.json)"
  validator_config_owner="$(stat -c '%U:%G' /etc/junca/validator.toml)"
  validator_config_mode="$(stat -c '%a' /etc/junca/validator.toml)"
  validator_config_link_count="$(stat -c '%h' /etc/junca/validator.toml)"
  validator_config_identity="$(
    stat -Lc '%d:%i' /etc/junca/validator.toml
  )"
  validator_config_sha256="$(
    sha256sum /etc/junca/validator.toml | awk '{print $1}'
  )"
  validator_config_size="$(stat -c '%s' /etc/junca/validator.toml)"
fi
if [[ -f /etc/junca/runtime.env &&
      ! -L /etc/junca/runtime.env &&
      "$(stat -c '%U:%G' /etc/junca/runtime.env)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/runtime.env)" == "640" &&
      "$(stat -c '%h' /etc/junca/runtime.env)" == 1 ]] &&
    verify_runtime_env_schema /etc/junca/runtime.env; then
  runtime_env_schema_verified=true
  runtime_env_required_assignment_count=18
  runtime_version="$(sed -n 's/^NODE_ARTIFACT_SHA256=//p' /etc/junca/runtime.env)"
  runtime_env_sha256="$(sha256sum /etc/junca/runtime.env | awk '{print $1}')"
  runtime_env_verified=true
  runtime_env_source=existing
  runtime_env_admission_identity="$(
    stat -Lc '%d:%i' /etc/junca/runtime.env
  )"
  runtime_env_owner="$(stat -c '%U:%G' /etc/junca/runtime.env)"
  runtime_env_mode="$(stat -c '%a' /etc/junca/runtime.env)"
  runtime_env_link_count="$(stat -c '%h' /etc/junca/runtime.env)"
fi
if [[ "$runtime_env_verified" != true ]] &&
    pin_repairable_runtime_env /etc/junca/runtime.env; then
  runtime_env_repair_admissible=true
fi
if [[ ! -e /etc/junca/runtime.env &&
      ! -L /etc/junca/runtime.env ]]; then
  runtime_env_target_admitted=true
elif [[ "$runtime_env_repair_admissible" == true &&
        "$runtime_env_preexisting" == true &&
        "$(stat -Lc '%d:%i' /etc/junca/runtime.env)" == \
          "$runtime_env_pre_identity" &&
        "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
          "$runtime_env_pre_sha256" &&
        "$(stat -c '%s' /etc/junca/runtime.env)" == \
          "$runtime_env_pre_size" ]]; then
  runtime_env_target_admitted=true
fi

if [[ "$runtime_env_verified" != true &&
      "$allow_runtime_env_repair" == true &&
      "$repair_status_admitted" != true &&
      "$durable_mount_verified" == true &&
      "$state_store_integrity" == true &&
      "$state_path_access_verified" == true &&
      "$binary_artifact_verified" == true &&
      "$genesis_verified" == true &&
      "$runtime_config_access_verified" == true &&
      "$runtime_directory_verified" == true ]]; then
  admit_controlled_active_repair || true
fi

if [[ "$runtime_env_verified" != true &&
      "$allow_runtime_env_repair" == true &&
      "$repair_status_admitted" == true &&
      "$runtime_env_target_admitted" == true &&
      "$durable_mount_verified" == true &&
      "$state_store_integrity" == true &&
      "$state_path_access_verified" == true &&
      "$binary_artifact_verified" == true &&
      "$genesis_verified" == true &&
      "$runtime_config_access_verified" == true &&
      "$runtime_directory_verified" == true ]]; then
  runtime_env_repair_attempted=true
  if systemctl is-active --quiet junca-validator.service; then
    systemctl stop junca-validator.service || service_stop_exit=$?
  fi
  if [[ "$service_stop_exit" == 0 ]]; then
    if [[ "$runtime_env_preexisting" == true ]]; then
      runtime_env_backup_path="/etc/junca/.runtime.env.rollback-${runtime_env_pre_sha256}"
      if [[ ! -e "$runtime_env_backup_path" &&
            ! -L "$runtime_env_backup_path" ]] &&
          ln /etc/junca/runtime.env "$runtime_env_backup_path" &&
          [[ "$(stat -Lc '%d:%i' "$runtime_env_backup_path")" == \
             "$runtime_env_pre_identity" ]] &&
          [[ "$(sha256sum "$runtime_env_backup_path" | awk '{print $1}')" == \
             "$runtime_env_pre_sha256" ]] &&
          [[ "$(stat -c '%s' "$runtime_env_backup_path")" == \
             "$runtime_env_pre_size" ]] &&
          [[ "$(stat -c '%U:%G' "$runtime_env_backup_path")" == \
             "$runtime_env_pre_owner" ]] &&
          [[ "$(stat -c '%a' "$runtime_env_backup_path")" == \
             "$runtime_env_pre_mode" ]]; then
        runtime_env_backup_created=true
      else
        if [[ -f "$runtime_env_backup_path" &&
              ! -L "$runtime_env_backup_path" &&
              "$(stat -Lc '%d:%i' "$runtime_env_backup_path")" == \
                "$runtime_env_pre_identity" ]]; then
          rm -f "$runtime_env_backup_path"
        fi
        runtime_env_backup_path=""
      fi
    fi
    runtime_env_tmp="$(mktemp /etc/junca/.runtime.env.XXXXXX)"
    trap 'rm -f "$runtime_env_tmp"' EXIT
    printf '%s' "$canonical_runtime_b64" |
      base64 -d >"$runtime_env_tmp"
    runtime_env_sha256="$(
      sha256sum "$runtime_env_tmp" |
        awk '{print $1}'
    )"
    if [[ "$runtime_env_sha256" == "$canonical_runtime_env_sha256" ]]; then
      chown root:junca "$runtime_env_tmp"
      chmod 0640 "$runtime_env_tmp"
      if [[ "$runtime_env_preexisting" == true &&
            "$runtime_env_backup_created" == true ]] &&
          sync -f "$runtime_env_tmp" &&
          mv -fT "$runtime_env_tmp" /etc/junca/runtime.env; then
        runtime_env_created=true
        runtime_env_replaced=true
        runtime_env_created_identity="$(stat -Lc '%d:%i' /etc/junca/runtime.env)"
        trap - EXIT
      elif [[ "$runtime_env_preexisting" == false ]] &&
          sync -f "$runtime_env_tmp" &&
          ln "$runtime_env_tmp" /etc/junca/runtime.env; then
        runtime_env_created=true
        runtime_env_created_identity="$(stat -Lc '%d:%i' /etc/junca/runtime.env)"
        if rm -f "$runtime_env_tmp"; then trap - EXIT; fi
      fi
      if [[ "$runtime_env_created" == true &&
            ! -e "$runtime_env_tmp" &&
            ! -L "$runtime_env_tmp" &&
            -f /etc/junca/runtime.env &&
            ! -L /etc/junca/runtime.env &&
            "$(stat -c '%U:%G' /etc/junca/runtime.env)" == "root:junca" &&
            "$(stat -c '%a' /etc/junca/runtime.env)" == "640" &&
            "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
              "$canonical_runtime_env_sha256" &&
            "$(stat -c '%h' /etc/junca/runtime.env)" == 1 ]] &&
          verify_runtime_env_schema /etc/junca/runtime.env &&
          sync -f /etc/junca; then
        runtime_env_persistence_verified=true
        runtime_env_schema_verified=true
        runtime_env_required_assignment_count=18
        runtime_env_repaired=true
        runtime_env_source=canonical
        runtime_env_verified=true
        runtime_version="$expected_runtime_version"
        runtime_env_admission_identity="$runtime_env_created_identity"
        runtime_env_owner="$(stat -c '%U:%G' /etc/junca/runtime.env)"
        runtime_env_mode="$(stat -c '%a' /etc/junca/runtime.env)"
        runtime_env_link_count="$(stat -c '%h' /etc/junca/runtime.env)"
      fi
    fi
  fi
fi

if [[ "$repair_status_admitted" == true &&
      "$durable_mount_verified" == true &&
      "$state_store_integrity" == true &&
      "$state_path_access_verified" == true &&
      "$binary_artifact_verified" == true &&
      "$genesis_verified" == true &&
      "$runtime_config_access_verified" == true &&
      "$runtime_directory_verified" == true &&
      "$runtime_env_verified" == true &&
      "$runtime_env_schema_verified" == true &&
      "$runtime_env_required_assignment_count" == 18 &&
      -f /etc/junca/runtime.env &&
      ! -L /etc/junca/runtime.env &&
      "$(stat -Lc '%d:%i' /etc/junca/runtime.env)" == \
        "$runtime_env_admission_identity" &&
      "$(stat -c '%U:%G' /etc/junca/runtime.env)" == "root:junca" &&
      "$(stat -c '%a' /etc/junca/runtime.env)" == "640" &&
      "$(stat -c '%h' /etc/junca/runtime.env)" == 1 &&
      "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
        "$runtime_env_sha256" ]]; then
  restart_attempted=true
  systemctl restart junca-validator.service || restart_exit=$?
fi

for attempts in $(seq 1 60); do
  after_status="$(systemctl is-active junca-validator.service 2>/dev/null || true)"
  if [[ "$after_status" == "active" ]] &&
      health="$(curl -fsS http://127.0.0.1:8545/health 2>/dev/null)"; then
    health_status="$(jq -r '.status // empty' <<<"$health" 2>/dev/null || true)"
    health_validator_id="$(
      jq -r '.validator_id // empty' <<<"$health" 2>/dev/null || true
    )"
    if [[ -f /etc/junca/runtime.env &&
          ! -L /etc/junca/runtime.env &&
          "$(stat -Lc '%d:%i' /etc/junca/runtime.env)" == \
            "$runtime_env_admission_identity" &&
          "$(stat -c '%U:%G' /etc/junca/runtime.env)" == "root:junca" &&
          "$(stat -c '%a' /etc/junca/runtime.env)" == "640" &&
          "$(stat -c '%h' /etc/junca/runtime.env)" == 1 &&
          "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
            "$runtime_env_sha256" ]]; then
      runtime_env_post_restart_verified=true
    fi
    if [[ "$health_status" == "healthy" &&
          "$health_validator_id" == "$expected_validator_id" &&
          "$restart_exit" == 0 &&
          "$durable_mount_verified" == true &&
          "$state_store_integrity" == true &&
          "$state_path_access_verified" == true &&
          "$binary_artifact_verified" == true &&
          "$genesis_verified" == true &&
          "$runtime_config_access_verified" == true &&
          "$runtime_directory_verified" == true &&
          "$runtime_env_verified" == true &&
          "$runtime_env_schema_verified" == true &&
          "$runtime_env_required_assignment_count" == 18 &&
          "$runtime_env_post_restart_verified" == true ]]; then
      accepted=true
      break
    fi
  fi
  if [[ "$attempts" -lt 60 ]]; then
    sleep 2
  fi
done

if [[ "$accepted" != true &&
      "$runtime_env_created" == true ]]; then
  repair_rollback_attempted=true
  systemctl stop junca-validator.service || true
  if [[ -e "${runtime_env_tmp:-}" &&
        ! -L "${runtime_env_tmp:-}" &&
        "$(stat -Lc '%d:%i' "${runtime_env_tmp:-}")" == \
          "$runtime_env_created_identity" ]]; then
    rm -f "${runtime_env_tmp:-}"
  fi
  if [[ -f /etc/junca/runtime.env &&
        ! -L /etc/junca/runtime.env &&
        "$(stat -Lc '%d:%i' /etc/junca/runtime.env)" == \
          "$runtime_env_created_identity" &&
        "$(stat -c '%h' /etc/junca/runtime.env)" == 1 &&
        "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
          "$canonical_runtime_env_sha256" ]]; then
    rm -f /etc/junca/runtime.env
  fi
  if [[ "$runtime_env_preexisting" == true &&
        "$runtime_env_backup_created" == true &&
        -f "$runtime_env_backup_path" &&
        ! -L "$runtime_env_backup_path" &&
        "$(stat -Lc '%d:%i' "$runtime_env_backup_path")" == \
          "$runtime_env_pre_identity" &&
        "$(sha256sum "$runtime_env_backup_path" | awk '{print $1}')" == \
          "$runtime_env_pre_sha256" &&
        ! -e /etc/junca/runtime.env &&
        ! -L /etc/junca/runtime.env ]] &&
      mv -T "$runtime_env_backup_path" /etc/junca/runtime.env &&
      [[ "$(stat -Lc '%d:%i' /etc/junca/runtime.env)" == \
         "$runtime_env_pre_identity" ]] &&
      [[ "$(sha256sum /etc/junca/runtime.env | awk '{print $1}')" == \
         "$runtime_env_pre_sha256" ]] &&
      sync -f /etc/junca; then
    repair_rollback_succeeded=true
    repair_rollback_persistence_verified=true
  elif [[ "$runtime_env_preexisting" == false &&
          ! -e /etc/junca/runtime.env &&
          ! -L /etc/junca/runtime.env ]] &&
      sync -f /etc/junca; then
    repair_rollback_succeeded=true
    repair_rollback_persistence_verified=true
  fi
  if [[ "$repair_rollback_succeeded" == true ]]; then
    runtime_env_verified=false
    runtime_env_post_restart_verified=false
    runtime_env_source=""
    runtime_env_sha256=""
  fi
fi

if [[ "$accepted" != true &&
      "$controlled_active_repair" == true &&
      "$controlled_stop_verified" == true &&
      "$pre_repair_health_status" == "healthy" &&
      "$pre_repair_validator_id" == "$expected_validator_id" ]] &&
    ! systemctl is-active --quiet junca-validator.service; then
  containment_restart_attempted=true
  systemctl start junca-validator.service || containment_restart_exit=$?
  if [[ "$containment_restart_exit" == 0 ]]; then
    for containment_attempt in $(seq 1 30); do
      if systemctl is-active --quiet junca-validator.service &&
          containment_health="$(
            curl -fsS http://127.0.0.1:8545/health 2>/dev/null
          )"; then
        containment_health_status="$(
          jq -r '.status // empty' <<<"$containment_health" \
            2>/dev/null || true
        )"
        containment_validator_id="$(
          jq -r '.validator_id // empty' <<<"$containment_health" \
            2>/dev/null || true
        )"
        if [[ "$containment_health_status" == "healthy" &&
              "$containment_validator_id" == "$expected_validator_id" ]]; then
          containment_recovered=true
          break
        fi
      fi
      if [[ "$containment_attempt" -lt 30 ]]; then
        sleep 2
      fi
    done
  fi
fi

jq -n \
  --arg schema_version "junca-validator-service-recovery/v8" \
  --arg genesis_sha256 "$expected_genesis_sha256" \
  --arg source_commit "$expected_source_commit" \
  --arg recovery_request_sha256 "$expected_recovery_request_sha256" \
  --argjson recovery_dispatch_sequence "$recovery_dispatch_sequence" \
  --argjson recovery_run_id "$recovery_run_id" \
  --argjson recovery_run_attempt "$recovery_run_attempt" \
  --arg release_request_sha256 "$release_request_sha256" \
  --arg manifest_decision_sha256 "$manifest_decision_sha256" \
  --arg candidate_head_sha "$candidate_head_sha" \
  --argjson allow_runtime_env_repair "$allow_runtime_env_repair" \
  --arg before_status "$before_status" \
  --arg pre_repair_health_status "$pre_repair_health_status" \
  --arg pre_repair_validator_id "$pre_repair_validator_id" \
  --argjson controlled_active_repair "$controlled_active_repair" \
  --argjson controlled_stop_attempted "$controlled_stop_attempted" \
  --argjson controlled_stop_exit "$controlled_stop_exit" \
  --argjson controlled_stop_verified "$controlled_stop_verified" \
  --argjson restart_attempted "$restart_attempted" \
  --argjson restart_exit "$restart_exit" \
  --argjson durable_mount_verified "$durable_mount_verified" \
  --arg durable_mount_volume_id "$durable_mount_volume_id" \
  --arg durable_mount_device "$durable_mount_device" \
  --arg durable_mount_source "$durable_mount_source" \
  --arg durable_mount_filesystem "$durable_mount_filesystem" \
  --argjson durable_mount_persistence_verified \
    "$durable_mount_persistence_verified" \
  --argjson durable_mount_repair_attempted \
    "$durable_mount_repair_attempted" \
  --argjson durable_mount_repaired "$durable_mount_repaired" \
  --argjson durable_mount_repair_exit "$durable_mount_repair_exit" \
  --arg durable_mount_repair_stage "$durable_mount_repair_stage" \
  --arg unmounted_state_target_entries \
    "$unmounted_state_target_entries" \
  --argjson scan_rollbacks_quarantined "$scan_rollbacks_quarantined" \
  --arg scan_rollbacks_quarantine_path "$scan_rollbacks_quarantine_path" \
  --arg scan_rollbacks_manifest_sha256 "$scan_rollbacks_manifest_sha256" \
  --argjson state_store_integrity "$state_store_integrity" \
  --argjson state_path_access_verified "$state_path_access_verified" \
  --argjson state_path_access_repair_attempted \
    "$state_path_access_repair_attempted" \
  --argjson state_path_access_repaired "$state_path_access_repaired" \
  --arg state_directory_owner "$state_directory_owner" \
  --arg state_directory_mode "$state_directory_mode" \
  --arg state_file_owner "$state_file_owner" \
  --arg state_file_mode "$state_file_mode" \
  --argjson state_file_link_count "$state_file_link_count" \
  --argjson state_auxiliary_file_count "$state_auxiliary_file_count" \
  --argjson binary_artifact_verified "$binary_artifact_verified" \
  --argjson genesis_verified "$genesis_verified" \
  --argjson system_identity_verified "$system_identity_verified" \
  --argjson system_identity_repair_attempted \
    "$system_identity_repair_attempted" \
  --argjson system_identity_repaired "$system_identity_repaired" \
  --argjson system_identity_uid "$system_identity_uid" \
  --argjson system_identity_gid "$system_identity_gid" \
  --argjson runtime_config_access_verified \
    "$runtime_config_access_verified" \
  --argjson runtime_config_repair_attempted \
    "$runtime_config_repair_attempted" \
  --argjson runtime_config_repaired "$runtime_config_repaired" \
  --arg runtime_directory_owner "$runtime_directory_owner" \
  --arg runtime_directory_mode "$runtime_directory_mode" \
  --arg genesis_owner "$genesis_owner" \
  --arg genesis_mode "$genesis_mode" \
  --argjson genesis_link_count "$genesis_link_count" \
  --arg validator_config_owner "$validator_config_owner" \
  --arg validator_config_mode "$validator_config_mode" \
  --argjson validator_config_link_count "$validator_config_link_count" \
  --argjson validator_config_preexisting \
    "$validator_config_preexisting" \
  --arg validator_config_pre_identity "$validator_config_pre_identity" \
  --arg validator_config_pre_sha256 "$validator_config_pre_sha256" \
  --argjson validator_config_pre_size "$validator_config_pre_size" \
  --arg validator_config_identity "$validator_config_identity" \
  --arg validator_config_sha256 "$validator_config_sha256" \
  --argjson validator_config_size "$validator_config_size" \
  --argjson runtime_directory_verified "$runtime_directory_verified" \
  --argjson runtime_env_verified "$runtime_env_verified" \
  --arg runtime_version "$runtime_version" \
  --argjson runtime_env_repair_attempted "$runtime_env_repair_attempted" \
  --argjson runtime_env_created "$runtime_env_created" \
  --arg runtime_env_created_identity "$runtime_env_created_identity" \
  --arg runtime_env_admission_identity "$runtime_env_admission_identity" \
  --arg runtime_env_owner "$runtime_env_owner" \
  --arg runtime_env_mode "$runtime_env_mode" \
  --argjson runtime_env_link_count "$runtime_env_link_count" \
  --argjson runtime_env_schema_verified "$runtime_env_schema_verified" \
  --argjson runtime_env_required_assignment_count \
    "$runtime_env_required_assignment_count" \
  --argjson runtime_env_repaired "$runtime_env_repaired" \
  --argjson runtime_env_persistence_verified \
    "$runtime_env_persistence_verified" \
  --argjson runtime_env_post_restart_verified \
    "$runtime_env_post_restart_verified" \
  --argjson runtime_env_repair_admissible \
    "$runtime_env_repair_admissible" \
  --argjson runtime_env_preexisting "$runtime_env_preexisting" \
  --arg runtime_env_pre_identity "$runtime_env_pre_identity" \
  --arg runtime_env_pre_sha256 "$runtime_env_pre_sha256" \
  --argjson runtime_env_pre_size "$runtime_env_pre_size" \
  --arg runtime_env_pre_owner "$runtime_env_pre_owner" \
  --arg runtime_env_pre_mode "$runtime_env_pre_mode" \
  --argjson runtime_env_backup_created "$runtime_env_backup_created" \
  --arg runtime_env_backup_path "$runtime_env_backup_path" \
  --argjson runtime_env_replaced "$runtime_env_replaced" \
  --argjson repair_rollback_attempted "$repair_rollback_attempted" \
  --argjson repair_rollback_succeeded "$repair_rollback_succeeded" \
  --argjson repair_rollback_persistence_verified \
    "$repair_rollback_persistence_verified" \
  --argjson containment_restart_attempted \
    "$containment_restart_attempted" \
  --argjson containment_restart_exit "$containment_restart_exit" \
  --arg containment_health_status "$containment_health_status" \
  --argjson containment_recovered "$containment_recovered" \
  --arg runtime_env_source "$runtime_env_source" \
  --arg runtime_env_sha256 "$runtime_env_sha256" \
  --argjson service_stop_exit "$service_stop_exit" \
  --arg after_status "$after_status" \
  --arg health_status "$health_status" \
  --arg health_validator_id "$health_validator_id" \
  --argjson attempts "$attempts" \
  --argjson accepted "$accepted" '{
    schema_version: $schema_version,
    genesis_sha256: $genesis_sha256,
    source_commit: $source_commit,
    recovery_request_sha256: $recovery_request_sha256,
    recovery_dispatch_sequence: $recovery_dispatch_sequence,
    recovery_run_id: $recovery_run_id,
    recovery_run_attempt: $recovery_run_attempt,
    release_request_sha256: $release_request_sha256,
    manifest_decision_sha256: $manifest_decision_sha256,
    candidate_head_sha: $candidate_head_sha,
    allow_runtime_env_repair: $allow_runtime_env_repair,
    before_status: $before_status,
    pre_repair_health_status: $pre_repair_health_status,
    pre_repair_validator_id: $pre_repair_validator_id,
    controlled_active_repair: $controlled_active_repair,
    controlled_stop_attempted: $controlled_stop_attempted,
    controlled_stop_exit: $controlled_stop_exit,
    controlled_stop_verified: $controlled_stop_verified,
    restart_attempted: $restart_attempted,
    restart_exit: $restart_exit,
    durable_mount_verified: $durable_mount_verified,
    durable_mount_volume_id: $durable_mount_volume_id,
    durable_mount_device: $durable_mount_device,
    durable_mount_source: $durable_mount_source,
    durable_mount_filesystem: $durable_mount_filesystem,
    durable_mount_persistence_verified:
      $durable_mount_persistence_verified,
    durable_mount_repair_attempted: $durable_mount_repair_attempted,
    durable_mount_repaired: $durable_mount_repaired,
    durable_mount_repair_exit: $durable_mount_repair_exit,
    durable_mount_repair_stage: $durable_mount_repair_stage,
    unmounted_state_target_entries: $unmounted_state_target_entries,
    scan_rollbacks_quarantined: $scan_rollbacks_quarantined,
    scan_rollbacks_quarantine_path:
      (if $scan_rollbacks_quarantine_path == "" then null
       else $scan_rollbacks_quarantine_path end),
    scan_rollbacks_manifest_sha256:
      (if $scan_rollbacks_manifest_sha256 == "" then null
       else $scan_rollbacks_manifest_sha256 end),
    state_store_integrity: $state_store_integrity,
    state_path_access_verified: $state_path_access_verified,
    state_path_access_repair_attempted:
      $state_path_access_repair_attempted,
    state_path_access_repaired: $state_path_access_repaired,
    state_directory_owner: $state_directory_owner,
    state_directory_mode: $state_directory_mode,
    state_file_owner: $state_file_owner,
    state_file_mode: $state_file_mode,
    state_file_link_count: $state_file_link_count,
    state_auxiliary_file_count: $state_auxiliary_file_count,
    binary_artifact_verified: $binary_artifact_verified,
    genesis_verified: $genesis_verified,
    system_identity_verified: $system_identity_verified,
    system_identity_repair_attempted: $system_identity_repair_attempted,
    system_identity_repaired: $system_identity_repaired,
    system_identity_uid: $system_identity_uid,
    system_identity_gid: $system_identity_gid,
    runtime_config_access_verified: $runtime_config_access_verified,
    runtime_config_repair_attempted: $runtime_config_repair_attempted,
    runtime_config_repaired: $runtime_config_repaired,
    runtime_directory_owner: $runtime_directory_owner,
    runtime_directory_mode: $runtime_directory_mode,
    genesis_owner: $genesis_owner,
    genesis_mode: $genesis_mode,
    genesis_link_count: $genesis_link_count,
    validator_config_owner: $validator_config_owner,
    validator_config_mode: $validator_config_mode,
    validator_config_link_count: $validator_config_link_count,
    validator_config_preexisting: $validator_config_preexisting,
    validator_config_pre_identity: $validator_config_pre_identity,
    validator_config_pre_sha256: $validator_config_pre_sha256,
    validator_config_pre_size: $validator_config_pre_size,
    validator_config_identity: $validator_config_identity,
    validator_config_sha256: $validator_config_sha256,
    validator_config_size: $validator_config_size,
    runtime_directory_verified: $runtime_directory_verified,
    runtime_env_verified: $runtime_env_verified,
    runtime_version: $runtime_version,
    runtime_env_repair_attempted: $runtime_env_repair_attempted,
    runtime_env_created: $runtime_env_created,
    runtime_env_created_identity: $runtime_env_created_identity,
    runtime_env_admission_identity: $runtime_env_admission_identity,
    runtime_env_owner: $runtime_env_owner,
    runtime_env_mode: $runtime_env_mode,
    runtime_env_link_count: $runtime_env_link_count,
    runtime_env_schema_verified: $runtime_env_schema_verified,
    runtime_env_required_assignment_count:
      $runtime_env_required_assignment_count,
    runtime_env_repaired: $runtime_env_repaired,
    runtime_env_persistence_verified: $runtime_env_persistence_verified,
    runtime_env_post_restart_verified:
      $runtime_env_post_restart_verified,
    runtime_env_repair_admissible: $runtime_env_repair_admissible,
    runtime_env_preexisting: $runtime_env_preexisting,
    runtime_env_pre_identity: $runtime_env_pre_identity,
    runtime_env_pre_sha256: $runtime_env_pre_sha256,
    runtime_env_pre_size: $runtime_env_pre_size,
    runtime_env_pre_owner: $runtime_env_pre_owner,
    runtime_env_pre_mode: $runtime_env_pre_mode,
    runtime_env_backup_created: $runtime_env_backup_created,
    runtime_env_backup_path: $runtime_env_backup_path,
    runtime_env_replaced: $runtime_env_replaced,
    repair_rollback_attempted: $repair_rollback_attempted,
    repair_rollback_succeeded: $repair_rollback_succeeded,
    repair_rollback_persistence_verified:
      $repair_rollback_persistence_verified,
    containment_restart_attempted: $containment_restart_attempted,
    containment_restart_exit: $containment_restart_exit,
    containment_health_status: $containment_health_status,
    containment_recovered: $containment_recovered,
    runtime_env_source: $runtime_env_source,
    runtime_env_sha256: $runtime_env_sha256,
    service_stop_exit: $service_stop_exit,
    after_status: $after_status,
    health_status: $health_status,
    health_validator_id: $health_validator_id,
    attempts: $attempts,
    accepted: $accepted,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false,
    mainnet_activation_authorized: false
  }'

if [[ "$accepted" != true ]]; then
  systemctl status junca-validator.service --no-pager -l >&2 || true
  journalctl -u junca-validator.service --no-pager -n 100 >&2 || true
  exit 1
fi
EOF
  )"
  jq -n --arg command "$recovery_command" '{commands: [$command]}' \
    >"artifacts/ssm-service-recovery-${validator_id}.json"
  command_id="$(
    aws ssm send-command \
      --instance-ids "$instance_id" \
      --document-name AWS-RunShellScript \
      --parameters \
        "file://artifacts/ssm-service-recovery-${validator_id}.json" \
      --comment "JUNCA Public Testnet bounded validator service recovery" \
      --query Command.CommandId \
      --output text
  )"
  invocation="artifacts/service-recovery-command-${validator_id}-${instance_id}.json"
  wait_for_ssm_command_result "$command_id" "$instance_id" "$invocation"
  jq -e \
    --arg command_id "$command_id" \
    --arg instance_id "$instance_id" '
      .CommandId == $command_id and
      .InstanceId == $instance_id
    ' "$invocation" >/dev/null
  jq -er \
    '.StandardOutputContent |
      select(type == "string" and length > 0)' \
    "$invocation" |
    jq \
      --arg validator_id "$validator_id" \
      --arg instance_id "$instance_id" \
      --arg ami_id "$ami_id" \
      --arg recovery_command_id "$command_id" \
      '. + {
        validator_id: $validator_id,
        instance_id: $instance_id,
        ami_id: $ami_id,
        recovery_command_id: $recovery_command_id
      }' >"$output_path"
  validate_validator_service_recovery_evidence \
    "$output_path" "$validator_id" "$instance_id" "$expected_ami_id" \
    "$expected_runtime_version" "$canonical_runtime_env_sha256" \
    "$expected_state_volume_id" "$genesis_sha256" "$SOURCE_COMMIT" \
    "$recovery_request_sha256" "$command_id" "$GITHUB_RUN_ID" \
    "$GITHUB_RUN_ATTEMPT" "$REQUEST_SHA256" \
    "$MANIFEST_DECISION_SHA256" "$ROLLING_CANDIDATE_HEAD_SHA" \
    "$allow_runtime_env_repair"
  jq -e '.Status == "Success"' "$invocation" >/dev/null
}

write_live_rollout_prefix_readback() {
  local evidence_updated_count="$1"
  local evidence_validators_path="$2"
  local previous_artifact_sha256="$3"
  local previous_ami_id="$4"
  local rollback_path="$5"
  local -a current_instances
  local -a validator_signer_arns
  local allow_runtime_env_repair
  local baseline_automatic_finality_enabled
  local baseline_block_interval_seconds
  local baseline_slot_epoch_seconds
  local binding_ami_id
  local binding_runtime_version
  local evidence_ami_id
  local evidence_instance_id
  local evidence_runtime_version
  local recovered_uncommitted_target_replacement
  local expected_ami_id
  local expected_runtime_version
  local index
  local ami_binding_path
  local peer_endpoints
  local signer_bindings
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
  mapfile -t validator_signer_arns < <(
    jq -er '.validator_signer_readback.value[].arn' \
      artifacts/live-prefix-foundation-outputs.json
  )
  test "${#validator_signer_arns[@]}" = 3
  for signer_arn in "${validator_signer_arns[@]}"; do
    [[ "$signer_arn" =~ ^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$ ]]
  done
  signer_bindings="$(
    jq -er '
      .validator_signer_readback.value
      | to_entries
      | map("validator-0\(.key + 1)=\(.value.arn)")
      | join(",")
    ' artifacts/live-prefix-foundation-outputs.json
  )"
  peer_endpoints="validator-01=10.67.16.10:30303,validator-02=10.67.32.10:30303,validator-03=10.67.48.10:30303"
  baseline_automatic_finality_enabled="$(
    read_required_json_boolean \
      '["automatic_finality_readback","value","enabled"]' \
      artifacts/live-prefix-foundation-outputs.json
  )"
  baseline_block_interval_seconds="$(
    jq -er '.automatic_finality_readback.value.block_interval_seconds' \
      artifacts/live-prefix-foundation-outputs.json
  )"
  baseline_slot_epoch_seconds="$(
    jq -er '.automatic_finality_readback.value.slot_epoch_seconds' \
      artifacts/live-prefix-foundation-outputs.json
  )"
  case "$baseline_automatic_finality_enabled" in
    true)
      test "$baseline_block_interval_seconds" = 30
      [[ "$baseline_slot_epoch_seconds" =~ ^[1-9][0-9]*$ ]]
      test "$((baseline_slot_epoch_seconds % 30))" = 0
      ;;
    false)
      test "$baseline_block_interval_seconds" = 0
      test "$baseline_slot_epoch_seconds" = 0
      ;;
    *) return 2 ;;
  esac
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
    ami_binding_path="artifacts/live-prefix-ami-binding-$((index + 1)).json"
    read_instance_ami_binding \
      "${current_instances[$index]}" \
      "$ami_binding_path"
    binding_ami_id="$(
      jq -er '.ami_id | select(test("^ami-[0-9a-f]{8,17}$"))' \
        "$ami_binding_path"
    )"
    binding_runtime_version="$(
      jq -er '.runtime_version | select(test("^[0-9a-f]{64}$"))' \
        "$ami_binding_path"
    )"
    evidence_ami_id=""
    evidence_instance_id=""
    evidence_runtime_version=""
    recovered_uncommitted_target_replacement=false
    if [[ -n "$evidence_validators_path" ]]; then
      evidence_ami_id="$(
        jq -er \
          --argjson index "$index" \
          --arg validator_id "validator-0$((index + 1))" '
            .[$index]
            | select(.validator_id == $validator_id)
            | .ami_id
            | select(type == "string" and
                test("^ami-[0-9a-f]{8,17}$"))
          ' "$evidence_validators_path"
      )"
      evidence_runtime_version="$(
        jq -er \
          --argjson index "$index" '
            .[$index].runtime_version
            | select(type == "string" and test("^[0-9a-f]{64}$"))
          ' "$evidence_validators_path"
      )"
      evidence_instance_id="$(
        jq -er \
          --argjson index "$index" '
            .[$index].instance_id
            | select(type == "string" and
                test("^i-[0-9a-f]{8,17}$"))
          ' "$evidence_validators_path"
      )"
      if [[ "$evidence_instance_id" != "${current_instances[$index]}" ]]; then
        [[ "$index" -eq "$evidence_updated_count" &&
          "$binding_ami_id" == "$NODE_AMI_ID" &&
          "$binding_runtime_version" == "$NODE_ARTIFACT_SHA256" ]]
        recovered_uncommitted_target_replacement=true
      fi
    fi
    if [[ "$index" -lt "$evidence_updated_count" ]]; then
      expected_ami_id="$NODE_AMI_ID"
      expected_runtime_version="$NODE_ARTIFACT_SHA256"
      if [[ -n "$evidence_validators_path" ]]; then
        test "$evidence_ami_id" = "$expected_ami_id"
        test "$evidence_runtime_version" = "$expected_runtime_version"
      fi
    elif [[ "$recovered_uncommitted_target_replacement" == true ]]; then
      expected_ami_id="$NODE_AMI_ID"
      expected_runtime_version="$NODE_ARTIFACT_SHA256"
    elif [[ -n "$evidence_validators_path" ]]; then
      expected_ami_id="$evidence_ami_id"
      expected_runtime_version="$evidence_runtime_version"
    else
      expected_ami_id="$binding_ami_id"
      expected_runtime_version="$binding_runtime_version"
    fi
    jq -e \
      --arg instance_id "${current_instances[$index]}" \
      --arg expected_ami_id "$expected_ami_id" \
      --arg expected_runtime_version "$expected_runtime_version" '
        .schema_version == "junca-validator-instance-ami-binding/v1" and
        .instance_id == $instance_id and
        .instance_state == "running" and
        .ami_id == $expected_ami_id and
        .runtime_version == $expected_runtime_version and
        .accepted == true and
        .mainnet_changed == false and
        .assets_moved == false and
        .bridge_activated == false and
        .mainnet_activation_authorized == false
      ' "$ami_binding_path" >/dev/null
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
    if [[ "$evidence_updated_count" == 0 ||
          "$recovered_uncommitted_target_replacement" == true ]]; then
      allow_runtime_env_repair=true
    else
      allow_runtime_env_repair=false
    fi
    observation_path="artifacts/live-prefix-validator-$((index + 1)).json"
    ensure_validator_service_available \
      "validator-0$((index + 1))" \
      "${current_instances[$index]}" \
      "$expected_ami_id" \
      "$expected_runtime_version" \
      "$GENESIS_SHA256" \
      "${validator_signer_arns[$index]}" \
      "$signer_bindings" \
      "$peer_endpoints" \
      "$baseline_automatic_finality_enabled" \
      "$baseline_block_interval_seconds" \
      "$baseline_slot_epoch_seconds" \
      "$state_volume_id" \
      "$allow_runtime_env_repair" \
      "artifacts/live-prefix-service-recovery-$((index + 1)).json"
    capture_validator_observation \
      "validator-0$((index + 1))" \
      "${current_instances[$index]}" \
      "$observation_path"
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
    artifacts/resume-evidence-bound-rollout-baseline.json
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
  local finality_activation_contract="${3:-false}"
  local -a current_instances
  local index
  local validator_id
  local state_volume_id
  local rollback_volume_id
  local observation_path
  local enriched_observation_path
  case "$finality_activation_contract" in
    true|false) ;;
    *) return 2 ;;
  esac
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
    --argjson finality_activation_contract \
      "$finality_activation_contract" \
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
      finality_activation_contract: $finality_activation_contract,
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

# A narrowly scoped recovery workflow may reuse the audited, evidence-bound
# service recovery helpers without entering Terraform plan/apply.  The caller
# must still satisfy the required environment validation above and perform its
# own exact AWS/Terraform admission before invoking any helper.
if [[ "${JUNCA_FOUNDATION_LIBRARY_ONLY:-false}" == "true" ]]; then
  return 0
fi

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
  read_required_json_boolean \
    '["public_services_acceptance_readback","value","enabled"]' \
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
    MANIFEST_DECISION_SHA256 GITHUB_RUN_ID GITHUB_RUN_ATTEMPT GITHUB_SHA \
    GITHUB_REPOSITORY \
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
  [[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]
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
  recovered_uncommitted_count="$(
    jq -er '.recovered_uncommitted_count' artifacts/live-prefix-decision.json
  )"
  evidence_bound_baseline_updated_count="$(
    jq -er '.evidence_updated_count' artifacts/live-prefix-decision.json
  )"
  if [[ "$rolling_epoch_renewal_performed" == "true" ]]; then
    if [[ "$live_updated_count" != "$rolling_epoch_renewal_prefix_count" ]]; then
      # Epoch renewal is resolved before the live-prefix readback and service
      # recovery. The only admissible advance is the one next exact candidate
      # that the evidence-bound gate recovered during this same run.
      test "$recovered_uncommitted_count" = "1"
      test "$rolling_epoch_renewal_prefix_count" = \
        "$evidence_bound_baseline_updated_count"
      test "$live_updated_count" = \
        "$((evidence_bound_baseline_updated_count + 1))"
    fi
  else
    test "$rolling_epoch_renewal_prefix_count" = "0"
  fi

  # The strict gate may recover exactly one completed-but-uncommitted target
  # replacement. Promote that fully observed contiguous live prefix as the
  # run-local evidence floor before any further mutation. The checksummed
  # producer artifact remains immutable and is still recorded separately.
  evidence_bound_baseline_updated_count="$live_updated_count"
  evidence_bound_baseline_bindings="$(
    jq -ce '
      .promoted_bindings
      | select(
          length == 3 and
          [.[].validator_id] ==
            ["validator-01", "validator-02", "validator-03"] and
          all(.[]; .runtime_version | test("^[0-9a-f]{64}$")) and
          all(.[]; .instance_id | test("^i-[0-9a-f]{8,17}$"))
        )
    ' artifacts/live-prefix-decision.json
  )"
  cp artifacts/live-prefix-validators.json \
    artifacts/evidence-bound-rollout-baseline.json

  # Stop automatic finality before the next replacement. The observed target
  # prefix is bound strictly to the candidate artifact; only the remaining
  # legacy suffix may initialize all-absent false/0/0 keys.
  pre_rollout_quiesce_decision_path=\
artifacts/pre-rollout-finality-quiesce-decision.json
  if write_pre_rollout_quiesce_reuse_decision \
    artifacts/live-prefix-validators.json \
    "$live_updated_count" "$NODE_ARTIFACT_SHA256" \
    "$pre_rollout_quiesce_decision_path"
  then
    :
  else
    if ! pre_rollout_finality_bindings="$(
      build_pre_rollout_finality_bindings \
        "$live_updated_count" \
        "$NODE_ARTIFACT_SHA256" "$evidence_bound_baseline_bindings" \
        "${pre_rollout_instances[@]}"
    )"; then
      jq -n '{
        schema_version: "junca-pre-rollout-finality-quiesce/v1",
        state: "BINDING_REJECTED",
        mutation_performed: false,
        accepted: false,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' >"$pre_rollout_quiesce_decision_path"
      exit 1
    fi
    if ! set_runtime_finality \
      0 0 "$pre_rollout_finality_bindings"
    then
      jq -n '{
        schema_version: "junca-pre-rollout-finality-quiesce/v1",
        state: "QUIESCE_MUTATION_FAILED",
        mutation_performed: true,
        accepted: false,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' >"$pre_rollout_quiesce_decision_path"
      exit 1
    fi
    jq -n \
      --argjson updated_count "$live_updated_count" '{
        schema_version: "junca-pre-rollout-finality-quiesce/v1",
        state: "QUIESCE_MUTATION_ACCEPTED",
        updated_count: $updated_count,
        mutation_performed: true,
        automatic_finality_enabled: false,
        block_interval_seconds: 0,
        slot_epoch_seconds: 0,
        accepted: true,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' >"$pre_rollout_quiesce_decision_path"
  fi
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

      # Terraform replacement is intentionally allowed to boot without a
      # mutable runtime.env in the immutable image. Reconstruct that file only
      # after the exact candidate AMI, retained state volume and SSM identity
      # have been read back. The existing bounded recovery helper binds the
      # canonical file to this run, attempt, release request, manifest
      # decision, candidate head, validator signer and peer set. A failed or
      # ambiguous recovery stops before finality mutation or serial advance.
      write_post_apply_checkpoint \
        "$index" service-recovery started "$new_instance" \
        "${state_volume_id:-}"
      if [[ "$validator_state_enabled" != "true" ||
            ! "$state_volume_id" =~ ^vol-[0-9a-f]{8,17}$ ]]; then
        write_post_apply_checkpoint \
          "$index" service-recovery failed "$new_instance" \
          "${state_volume_id:-}"
        exit 1
      fi
      if ! post_apply_signer_arn="$(
        jq -er \
          ".[${index}].arn |
            select(test(\"^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]{36}$\"))" \
          <<<"$(
            jq -ce '.validator_signer_readback.value' \
              artifacts/pre-foundation-outputs.json
          )"
      )"; then
        write_post_apply_checkpoint \
          "$index" service-recovery failed "$new_instance" "$state_volume_id"
        exit 1
      fi
      if ! post_apply_signer_bindings="$(
        jq -er '
          .validator_signer_readback.value
          | to_entries
          | select(length == 3)
          | map("validator-0\(.key + 1)=\(.value.arn)")
          | join(",")
        ' artifacts/pre-foundation-outputs.json
      )"; then
        write_post_apply_checkpoint \
          "$index" service-recovery failed "$new_instance" "$state_volume_id"
        exit 1
      fi
      post_apply_peer_endpoints="validator-01=10.67.16.10:30303,validator-02=10.67.32.10:30303,validator-03=10.67.48.10:30303"
      if ! ensure_validator_service_available \
        "validator-0$((index + 1))" \
        "$new_instance" \
        "$NODE_AMI_ID" \
        "$NODE_ARTIFACT_SHA256" \
        "$GENESIS_SHA256" \
        "$post_apply_signer_arn" \
        "$post_apply_signer_bindings" \
        "$post_apply_peer_endpoints" \
        true \
        "$validator_block_interval_seconds" \
        "$validator_slot_epoch_seconds" \
        "$state_volume_id" \
        true \
        "artifacts/post-apply-validator-$((index + 1))-service-recovery.json"
      then
        write_post_apply_checkpoint \
          "$index" service-recovery failed "$new_instance" "$state_volume_id"
        exit 1
      fi
      write_post_apply_checkpoint \
        "$index" service-recovery succeeded "$new_instance" "$state_volume_id"

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
        write_post_apply_checkpoint \
          "$index" public-gateway started "$new_instance" \
          "${state_volume_id:-}"
        if ! ensure_public_gateways_available \
          "$new_instance" \
          "artifacts/post-apply-validator-${index}-public-gateway-command.json" \
          "artifacts/post-apply-validator-${index}-public-gateway.json"
        then
          write_post_apply_checkpoint \
            "$index" public-gateway failed "$new_instance" \
            "${state_volume_id:-}"
          exit 1
        fi
        write_post_apply_checkpoint \
          "$index" public-gateway succeeded "$new_instance" \
          "${state_volume_id:-}"

        current_outputs="$(
          terraform -chdir=infra/aws/public-testnet output -json
        )"
        target_group_index=0
        for target_group in \
          "$(jq -er '.public_target_group_arns.value.rpc' <<<"$current_outputs")" \
          "$(jq -er '.public_target_group_arns.value.explorer' <<<"$current_outputs")"
        do
          target_health_path="artifacts/post-apply-validator-${index}-target-health-${target_group_index}.json"
          if ! aws elbv2 wait target-in-service \
              --target-group-arn "$target_group" \
              --targets "Id=${new_instance}"
          then
            aws elbv2 describe-target-health \
              --target-group-arn "$target_group" \
              --targets "Id=${new_instance}" \
              >"$target_health_path" || true
            write_post_apply_checkpoint \
              "$index" target-health failed "$new_instance" \
              "${state_volume_id:-}"
            exit 1
          fi
          aws elbv2 describe-target-health \
            --target-group-arn "$target_group" \
            --targets "Id=${new_instance}" \
            >"$target_health_path"
          jq -e '
            (.TargetHealthDescriptions | length) >= 1 and
            all(.TargetHealthDescriptions[]; .TargetHealth.State == "healthy")
          ' "$target_health_path" >/dev/null
          target_group_index="$((target_group_index + 1))"
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
    rollout_slot_epoch_seconds="$validator_slot_epoch_seconds"
    activation_interval_seconds=30
    activation_delay_seconds=180
    activation_now_seconds="$(date +%s)"
    validator_slot_epoch_seconds="$(
      echo $((
        ((activation_now_seconds + activation_delay_seconds +
          activation_interval_seconds - 1) /
          activation_interval_seconds) * activation_interval_seconds
      ))
    )"
    test "$validator_slot_epoch_seconds" -gt "$activation_now_seconds"
    test "$((validator_slot_epoch_seconds % activation_interval_seconds))" -eq 0
    test "$((validator_slot_epoch_seconds - activation_now_seconds))" -ge \
      "$activation_delay_seconds"
    jq -n \
      --argjson rollout_slot_epoch_seconds "$rollout_slot_epoch_seconds" \
      --argjson slot_epoch_seconds "$validator_slot_epoch_seconds" \
      --argjson block_interval_seconds "$activation_interval_seconds" \
      --argjson activation_delay_seconds "$activation_delay_seconds" \
      --argjson observed_at "$activation_now_seconds" \
      --arg node_artifact_sha256 "$NODE_ARTIFACT_SHA256" \
      --argjson bindings "$activated_finality_bindings" '{
        schema_version: "junca-finality-activation/v1",
        state: "NEXT_CANONICAL_SLOT_PENDING",
        rollout_slot_epoch_seconds: $rollout_slot_epoch_seconds,
        enabled: true,
        block_interval_seconds: $block_interval_seconds,
        slot_epoch_seconds: $slot_epoch_seconds,
        activation_delay_seconds: $activation_delay_seconds,
        observed_at: $observed_at,
        node_artifact_sha256: $node_artifact_sha256,
        bindings: $bindings,
        accepted: false,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }' > artifacts/finality-activation.json
    set_runtime_finality \
      0 "$validator_slot_epoch_seconds" "$activated_finality_bindings"
    write_rolling_compatibility_evidence \
      READY_FOR_FINALITY_ENABLE "" true
    test "$validator_slot_epoch_seconds" -gt "$(date +%s)"
    set_runtime_finality \
      30 "$validator_slot_epoch_seconds" "$activated_finality_bindings"
    activation_evidence_tmp="$(
      mktemp artifacts/.finality-activation.XXXXXX
    )"
    jq --argjson accepted_at "$(date +%s)" '
      .state = "NEXT_CANONICAL_SLOT_BOUND" |
      .accepted = true |
      .accepted_at = $accepted_at
    ' artifacts/finality-activation.json >"$activation_evidence_tmp"
    mv -f "$activation_evidence_tmp" artifacts/finality-activation.json
    write_rolling_compatibility_evidence ACCEPTED "" true
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
