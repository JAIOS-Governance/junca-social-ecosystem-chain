#!/usr/bin/env bash
set -euo pipefail
umask 027

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-595710543956}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_BUCKET_NAME="${STATE_BUCKET_NAME:-junca-social-ecosystem-chain-tfstate-595710543956-us-east-1}"
LOCK_TABLE_NAME="${LOCK_TABLE_NAME:-junca-social-ecosystem-chain-testnet-lock}"
DEPLOYMENT_ROLE_ARN="${DEPLOYMENT_ROLE_ARN:-arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment}"
DOMAIN_NAME="${DOMAIN_NAME:-jaios-governance.org}"
ROUTE53_ZONE_ID="${ROUTE53_ZONE_ID:-Z0336017285464TX0NT1G}"
MIGRATION_AUTHORIZATION="${MIGRATION_AUTHORIZATION:-}"
MIGRATION_REQUEST_SHA256="${MIGRATION_REQUEST_SHA256:-}"
GITHUB_RUN_ID="${GITHUB_RUN_ID:-}"
GITHUB_RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-}"
GITHUB_SHA="${GITHUB_SHA:-}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
GITHUB_EVENT_PATH="${GITHUB_EVENT_PATH:-}"

test "$AWS_ACCOUNT_ID" = "595710543956"
test "$AWS_REGION" = "us-east-1"
test "$STATE_BUCKET_NAME" = \
  "junca-social-ecosystem-chain-tfstate-595710543956-us-east-1"
test "$LOCK_TABLE_NAME" = "junca-social-ecosystem-chain-testnet-lock"
test "$DEPLOYMENT_ROLE_ARN" = \
  "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment"
test "$MIGRATION_AUTHORIZATION" = \
  "PUBLIC_TESTNET_VALIDATOR_STATE_MIGRATION"
[[ "$MIGRATION_REQUEST_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ ]]
[[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
test "$GITHUB_REPOSITORY" = \
  "JAIOS-Governance/junca-social-ecosystem-chain"
test -f "$GITHUB_EVENT_PATH"
test "$(aws sts get-caller-identity --query Account --output text)" = \
  "$AWS_ACCOUNT_ID"

artifact_dir="${GITHUB_WORKSPACE:-$PWD}/artifacts/validator-state-migration"
mkdir -p "$artifact_dir/readback" "$artifact_dir/ssm"
runtime_dir=infra/aws/public-testnet
node_script=scripts/junca_migrate_validator_state_node.sh
test -f "$node_script"
github_event_sha256="$(sha256sum "$GITHUB_EVENT_PATH" | cut -d' ' -f1)"
[[ "$github_event_sha256" =~ ^[0-9a-f]{64}$ ]]

aws dynamodb describe-table --table-name "$LOCK_TABLE_NAME" \
  >"$artifact_dir/readback/lock-table.json"
jq -e '.Table.TableStatus == "ACTIVE"' \
  "$artifact_dir/readback/lock-table.json" >/dev/null
aws s3api get-bucket-encryption --bucket "$STATE_BUCKET_NAME" \
  >"$artifact_dir/readback/state-bucket-encryption.json"
state_kms_key_id="$(
  jq -er '
    [
      .ServerSideEncryptionConfiguration.Rules[]
      | .ApplyServerSideEncryptionByDefault
      | select(.SSEAlgorithm == "aws:kms")
      | .KMSMasterKeyID
    ]
    | if length == 1 then .[0] else error("exact KMS encryption rule required") end
  ' "$artifact_dir/readback/state-bucket-encryption.json"
)"

terraform -chdir="$runtime_dir" init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$LOCK_TABLE_NAME" \
  -backend-config="encrypt=true" \
  -backend-config="kms_key_id=$state_kms_key_id"
terraform -chdir="$runtime_dir" output -json \
  >"$artifact_dir/readback/pre-migration-outputs.json"

outputs="$artifact_dir/readback/pre-migration-outputs.json"
jq -e \
  --arg account "$AWS_ACCOUNT_ID" \
  --arg region "$AWS_REGION" '
  .aws_account_id.value == $account and
  .region.value == $region and
  .runtime_boundary.value.mainnet_changed == false and
  .runtime_boundary.value.assets_moved == false and
  .runtime_boundary.value.bridge_activated == false and
  (.validator_instance_ids.value | length) == 3 and
  (.validator_instance_ids.value | unique | length) == 3 and
  (.validator_signer_readback.value | length) == 3
' "$outputs" >/dev/null

write_tfvars() {
  accepted="$1"
  rollback_snapshot_ids="$2"
  state_volume_count="$(
    jq -er '.validator_state_volume_readback.value | length' "$outputs"
  )"
  if [[ "$state_volume_count" == 3 ]]; then
    restored_snapshot_ids="$(
      jq -ce '
        .validator_state_volume_readback.value
        | map(.restored_snapshot) as $values
        | if all($values[]; . == null) then null else $values end
      ' "$outputs"
    )"
  else
    restored_snapshot_ids=null
  fi
  public_services_enabled="$(
    jq -r '.public_services_acceptance_readback.value.enabled // false' \
      "$outputs"
  )"
  case "$public_services_enabled" in
    true|false) ;;
    *) echo "public services readback must be boolean" >&2; exit 1 ;;
  esac
  quorum_sha256="$(
    jq -cr '
      .public_services_acceptance_readback.value.quorum_evidence_sha256
    ' "$outputs"
  )"
  runtime_sha256="$(
    jq -cr '
      .public_services_acceptance_readback.value.runtime_evidence_sha256
    ' "$outputs"
  )"
  jq -n \
    --arg aws_account_id "$AWS_ACCOUNT_ID" \
    --arg aws_region "$AWS_REGION" \
    --arg domain_name "$DOMAIN_NAME" \
    --arg route53_zone_id "$ROUTE53_ZONE_ID" \
    --arg deployment_principal_arn "$DEPLOYMENT_ROLE_ARN" \
    --argjson availability_zones \
      "$(jq -c '.availability_zones.value' "$outputs")" \
    --argjson validator_signer_arns \
      "$(jq -c '.validator_signer_readback.value | map(.arn)' "$outputs")" \
    --arg node_ami_id \
      "$(jq -er '.approved_node_ami_readback.value.id' "$outputs")" \
    --arg node_artifact_sha256 \
      "$(jq -er '.approved_node_ami_readback.value.node_sha256' "$outputs")" \
    --arg genesis_sha256 \
      "$(jq -er '.approved_node_ami_readback.value.genesis_sha256' "$outputs")" \
    --arg source_commit \
      "$(jq -er '.approved_node_ami_readback.value.source_commit' "$outputs")" \
    --argjson automatic_finality_enabled \
      "$(jq -c '.automatic_finality_readback.value.enabled' "$outputs")" \
    --argjson validator_block_interval_seconds \
      "$(jq -c '
        if .automatic_finality_readback.value.enabled
        then .automatic_finality_readback.value.block_interval_seconds
        else 30 end
      ' "$outputs")" \
    --argjson validator_slot_epoch_seconds \
      "$(jq -c '
        if .automatic_finality_readback.value.enabled
        then .automatic_finality_readback.value.slot_epoch_seconds
        else 0 end
      ' "$outputs")" \
    --argjson enable_public_services "$public_services_enabled" \
    --argjson quorum_acceptance_sha256 "$quorum_sha256" \
    --argjson runtime_acceptance_sha256 "$runtime_sha256" \
    --argjson validator_state_snapshot_ids "$restored_snapshot_ids" \
    --argjson validator_state_migration_accepted "$accepted" \
    --argjson validator_state_rollback_snapshot_ids \
      "$rollback_snapshot_ids" '
    {
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
      provision_validator_state_volumes: true,
      enable_validator_state_volumes: false,
      validator_state_migration_accepted:
        $validator_state_migration_accepted,
      validator_state_rollback_snapshot_ids:
        $validator_state_rollback_snapshot_ids,
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
    }
  ' >"$artifact_dir/validator-state-migration.auto.tfvars.json"
}

state_volume_count="$(
  jq -er '.validator_state_volume_readback.value | length' "$outputs"
)"
case "$state_volume_count" in
  0|1|2)
    write_tfvars false null
    terraform -chdir="$runtime_dir" plan -input=false \
      -var-file="$artifact_dir/validator-state-migration.auto.tfvars.json" \
      -out="$artifact_dir/validator-state-provision.tfplan"
    terraform -chdir="$runtime_dir" show -json \
      "$artifact_dir/validator-state-provision.tfplan" \
      >"$artifact_dir/validator-state-provision-plan.json"
    jq -e '
      [
        .resource_changes[]?
        | select(.change.actions != ["no-op"] and .change.actions != ["read"])
      ] as $changes
      | ($changes | length) <= 6 and
        ($changes | map(.address) | unique | length) == ($changes | length) and
        all(
          $changes[];
          .change.actions == ["create"] and
          (
            .address | test(
              "^aws_(ebs_volume|volume_attachment)\\.validator_state\\[[0-2]\\]$"
            )
          )
        ) and
        all(
          $changes[]
          | select(.address | startswith("aws_ebs_volume."));
          .change.after.encrypted == true and
          .change.after.type == "gp3" and
          .change.after.size == 200 and
          .change.after.iops == 6000 and
          .change.after.throughput == 250 and
          .change.after.snapshot_id == null and
          .change.after.tags.StatePath == "/var/lib/junca" and
          .change.after.tags.MigrationRequired == "true" and
          .change.after.tags.PublicTestnetOnly == "true"
        ) and
        all(
          $changes[]
          | select(.address | startswith("aws_volume_attachment."));
          .change.after.device_name == "/dev/sdf" and
          .change.after.force_detach == false and
          .change.after.stop_instance_before_detaching == true
        )
    ' "$artifact_dir/validator-state-provision-plan.json" >/dev/null
    terraform -chdir="$runtime_dir" apply -input=false -auto-approve \
      "$artifact_dir/validator-state-provision.tfplan"
    terraform -chdir="$runtime_dir" output -json >"$outputs"
    ;;
  3) ;;
  *)
    echo "validator durable state must contain exactly zero or three volumes" >&2
    exit 1
    ;;
esac

mapfile -t instances < <(
  jq -er '.validator_instance_ids.value[]' "$outputs"
)
mapfile -t volumes < <(
  jq -er '.validator_state_volume_readback.value[].volume_id' "$outputs"
)
mapfile -t signer_arns < <(
  jq -er '.validator_signer_readback.value[].arn' "$outputs"
)
test "${#instances[@]}" = 3
test "${#volumes[@]}" = 3
test "${#signer_arns[@]}" = 3
test "$(printf '%s\n' "${instances[@]}" | sort -u | wc -l)" = 3
test "$(printf '%s\n' "${volumes[@]}" | sort -u | wc -l)" = 3
health_bindings="$(
  jq -n \
    --arg instance_0 "${instances[0]}" \
    --arg instance_1 "${instances[1]}" \
    --arg instance_2 "${instances[2]}" \
    --arg signer_0 \
      "$(printf '%s' "${signer_arns[0]}" | sha256sum | cut -d' ' -f1)" \
    --arg signer_1 \
      "$(printf '%s' "${signer_arns[1]}" | sha256sum | cut -d' ' -f1)" \
    --arg signer_2 \
      "$(printf '%s' "${signer_arns[2]}" | sha256sum | cut -d' ' -f1)" '
    [
      {
        instance_id: $instance_0,
        validator_id: "validator-01",
        signer_resource_digest: $signer_0
      },
      {
        instance_id: $instance_1,
        validator_id: "validator-02",
        signer_resource_digest: $signer_1
      },
      {
        instance_id: $instance_2,
        validator_id: "validator-03",
        signer_resource_digest: $signer_2
      }
    ]
  '
)"

aws ec2 describe-instances --instance-ids "${instances[@]}" \
  >"$artifact_dir/readback/instances.json"
aws ec2 describe-volumes --volume-ids "${volumes[@]}" \
  >"$artifact_dir/readback/volumes-before.json"
jq -e --argjson instances \
  "$(printf '%s\n' "${instances[@]}" | jq -Rsc 'split("\n")[:-1]')" '
  [.Reservations[].Instances[]] as $actual
  | ($actual | length) == 3 and
    ([ $actual[].InstanceId ] | sort) == ($instances | sort) and
    all($actual[]; .State.Name == "running")
' "$artifact_dir/readback/instances.json" >/dev/null
jq -e --argjson instances \
  "$(printf '%s\n' "${instances[@]}" | jq -Rsc 'split("\n")[:-1]')" \
  --argjson availability_zones \
  "$(jq -c '.availability_zones.value' "$outputs")" '
  .Volumes as $actual_volumes
  | ($actual_volumes | length) == 3 and
  ([.Volumes[].AvailabilityZone] | sort) == ($availability_zones | sort) and
  all(
    .Volumes[];
    .Encrypted == true and
    .VolumeType == "gp3" and
    .Size == 200 and
    .Iops == 6000 and
    .Throughput == 250 and
    .State == "in-use" and
    (.Attachments | length) == 1 and
    (.Attachments[0].InstanceId as $id | $instances | index($id)) != null and
    .Attachments[0].State == "attached"
  )
' "$artifact_dir/readback/volumes-before.json" >/dev/null

already_accepted="$(
  jq -r '
    [.validator_state_volume_readback.value[].migration_accepted] |
    all(. == true)
  ' "$outputs"
)"
existing_migration_tag_count="$(
  jq -er '
    [
      .Volumes[].Tags[]?
      | select(.Key == "JuncaMigrationState")
    ] | length
  ' "$artifact_dir/readback/volumes-before.json"
)"
if [[ "$already_accepted" == false && "$existing_migration_tag_count" == 0 ]]; then
  write_tfvars false null
  terraform -chdir="$runtime_dir" plan -input=false \
    -var-file="$artifact_dir/validator-state-migration.auto.tfvars.json" \
    -out="$artifact_dir/validator-state-preflight.tfplan"
  terraform -chdir="$runtime_dir" show -json \
    "$artifact_dir/validator-state-preflight.tfplan" \
    >"$artifact_dir/validator-state-preflight-plan.json"
  jq -e '
    [
      .resource_changes[]?
      | select(.change.actions != ["no-op"] and .change.actions != ["read"])
    ] | length == 0
  ' "$artifact_dir/validator-state-preflight-plan.json" >/dev/null
fi
rollback_snapshots=()
migration_token="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
active_command_id=""
current_instance=""
last_node_binding=""
validator_evidence_jsonl="$artifact_dir/readback/validator-mapping.jsonl"
quorum_evidence_jsonl="$artifact_dir/readback/quorum-checkpoints.jsonl"
: >"$validator_evidence_jsonl"
: >"$quorum_evidence_jsonl"
last_quorum_height=-1
last_quorum_hash=""
last_quorum_certificate=""

wait_ssm_command() {
  command_id="$1"
  instance_id="$2"
  max_attempts="$3"
  for attempt in $(seq 1 "$max_attempts"); do
    status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" --instance-id "$instance_id" \
        --query Status --output text 2>/dev/null || true
    )"
    case "$status" in
      Success) return 0 ;;
      Failed|Cancelled|TimedOut|Cancelling) return 1 ;;
      Pending|InProgress|Delayed|"") ;;
      *) echo "unexpected SSM command state: $status" >&2; return 1 ;;
    esac
    sleep 10
  done
  aws ssm cancel-command --command-id "$command_id" >/dev/null
  for attempt in $(seq 1 60); do
    status="$(
      aws ssm get-command-invocation \
        --command-id "$command_id" --instance-id "$instance_id" \
        --query Status --output text 2>/dev/null || true
    )"
    case "$status" in
      Success|Failed|Cancelled|TimedOut) break ;;
    esac
    test "$attempt" -lt 60
    sleep 5
  done
  return 124
}

run_node_phase() {
    instance_id="$1"
    volume_id="$2"
    signer_arn="$3"
    phase="$4"
    output_path="$5"
    encoded="$(base64 -w0 "$node_script")"
    command="printf '%s' '$encoded' | base64 -d > /tmp/junca-migrate-validator-state; chmod 0750 /tmp/junca-migrate-validator-state; JUNCA_STATE_VOLUME_ID='$volume_id' JUNCA_EXPECTED_SIGNER_ARN='$signer_arn' JUNCA_MIGRATION_TOKEN='$migration_token' JUNCA_MIGRATION_PHASE='$phase' /tmp/junca-migrate-validator-state"
    jq -n --arg command "$command" '{commands: [$command]}' \
      >"$artifact_dir/ssm/request-${instance_id}-${phase}.json"
    request_sha256="$(
      sha256sum "$artifact_dir/ssm/request-${instance_id}-${phase}.json" |
        cut -d' ' -f1
    )"
    [[ "$request_sha256" =~ ^[0-9a-f]{64}$ ]]
    command_id="$(
      aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name AWS-RunShellScript \
        --parameters \
          "file://$artifact_dir/ssm/request-${instance_id}-${phase}.json" \
        --comment "JUNCA validator state migration ${phase}" \
        --timeout-seconds 1800 \
        --query Command.CommandId --output text
    )"
    active_command_id="$command_id"
    wait_ssm_command "$command_id" "$instance_id" 180
    aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$instance_id" \
      >"$output_path"
    jq -e '.Status == "Success"' "$output_path" >/dev/null
    last_node_binding="${output_path%.json}-binding.json"
    jq -n \
      --arg command_id "$command_id" \
      --arg instance_id "$instance_id" \
      --arg state_volume_id "$volume_id" \
      --arg signer_arn "$signer_arn" \
      --arg phase "$phase" \
      --arg migration_token "$migration_token" \
      --arg request_sha256 "$request_sha256" \
      --arg run_id "$GITHUB_RUN_ID" \
      --argjson run_attempt "$GITHUB_RUN_ATTEMPT" \
      --arg head_sha "$GITHUB_SHA" \
      --arg migration_request_sha256 "$MIGRATION_REQUEST_SHA256" \
      --arg github_event_sha256 "$github_event_sha256" '
      {
        command_id: $command_id,
        instance_id: $instance_id,
        state_volume_id: $state_volume_id,
        signer_arn: $signer_arn,
        phase: $phase,
        migration_token: $migration_token,
        ssm_request_sha256: $request_sha256,
        run_id: $run_id,
        run_attempt: $run_attempt,
        head_sha: $head_sha,
        migration_request_sha256: $migration_request_sha256,
        github_event_sha256: $github_event_sha256
      }
    ' >"$last_node_binding"
    active_command_id=""
}

record_validator_evidence() {
  validator_index="$1"
  instance_id="$2"
  volume_id="$3"
  signer_arn="$4"
  snapshot_id="$5"
  root_volume_id="$6"
  invocation_path="$7"
  binding_path="$8"
  disposition="$9"
  [[ "$root_volume_id" =~ ^vol-[0-9a-f]{8,17}$ ]]
  jq -cn \
    --arg validator_id "$(printf 'validator-%02d' "$((validator_index + 1))")" \
    --arg instance_id "$instance_id" \
    --arg state_volume_id "$volume_id" \
    --arg signer_arn "$signer_arn" \
    --arg rollback_snapshot_id "$snapshot_id" \
    --arg root_volume_id "$root_volume_id" \
    --arg disposition "$disposition" \
    --slurpfile invocation "$invocation_path" \
    --slurpfile binding "$binding_path" '
    ($invocation[0].StandardOutputContent | fromjson) as $result
    | ($binding[0]) as $request
    | if (
        $invocation | length == 1 and
        $binding | length == 1 and
        $request.instance_id == $instance_id and
        $request.state_volume_id == $state_volume_id and
        $result.volume_id == $state_volume_id and
        ($result.state == "VERIFIED_PASS" or
         $result.state == "ALREADY_MIGRATED")
      )
      then {
        validator_id: $validator_id,
        instance_id: $instance_id,
        state_volume_id: $state_volume_id,
        signer_arn: $signer_arn,
        rollback_snapshot_id: $rollback_snapshot_id,
        root_volume_id: $root_volume_id,
        disposition: $disposition,
        node_result: $result,
        request_binding: $request
      }
      else error("validator result/request mapping mismatch")
      end
  ' >>"$validator_evidence_jsonl"
}

read_snapshot_root_volume() {
  snapshot_id="$1"
  output_path="$2"
  aws ec2 describe-snapshots --snapshot-ids "$snapshot_id" >"$output_path"
  root_volume_id="$(
    jq -er \
      --arg owner "$AWS_ACCOUNT_ID" \
      --arg snapshot "$snapshot_id" '
      .Snapshots
      | if (
          length == 1 and
          .[0].SnapshotId == $snapshot and
          .[0].OwnerId == $owner and
          .[0].Encrypted == true and
          .[0].State == "completed" and
          (.[0].VolumeId | test("^vol-[0-9a-f]{8,17}$"))
        )
        then .[0].VolumeId
        else error("exact completed encrypted rollback snapshot required")
        end
    ' "$output_path"
  )"
  printf '%s\n' "$root_volume_id"
}

require_peer_health() {
  excluded="$1"
  checkpoint="$2"
  [[ "$checkpoint" =~ ^[a-z0-9-]+$ ]]
  invocation_paths=()
  for peer in "${instances[@]}"; do
    [[ "$peer" == "$excluded" ]] && continue
    request="$artifact_dir/ssm/health-${checkpoint}-${peer}.json"
    invocation="$artifact_dir/ssm/health-${checkpoint}-${peer}-invocation.json"
    jq -n '{
      commands: [
        "set -euo pipefail",
        "curl -fsS http://127.0.0.1:8545/health",
        "systemctl is-active --quiet junca-validator"
      ]
    }' >"$request"
    command_id="$(
      aws ssm send-command --instance-ids "$peer" \
        --document-name AWS-RunShellScript \
        --parameters "file://$request" \
        --comment "JUNCA migration peer quorum readback ${checkpoint}" \
        --timeout-seconds 300 \
        --query Command.CommandId --output text
    )"
    wait_ssm_command "$command_id" "$peer" 30
    aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$peer" >"$invocation"
    jq -e '.Status == "Success"' "$invocation" >/dev/null
    invocation_paths+=("$invocation")
  done
  expected_peer_count=3
  [[ -n "$excluded" ]] && expected_peer_count=2
  checkpoint_path="$artifact_dir/readback/quorum-${checkpoint}.json"
  jq -s \
    --arg checkpoint "$checkpoint" \
    --arg excluded "$excluded" \
    --argjson expected_peer_count "$expected_peer_count" \
    --argjson previous_height "$last_quorum_height" \
    --arg previous_hash "$last_quorum_hash" \
    --arg previous_certificate "$last_quorum_certificate" \
    --argjson health_bindings "$health_bindings" '
    map({
      instance_id: .InstanceId,
      command_id: .CommandId,
      health: (
        .StandardOutputContent
        | sub("[\r\n]+$"; "")
        | fromjson
      )
    }) as $peers
    | ($peers | map(.health.head_height) | unique) as $heights
    | ($peers | map(.health.head_hash) | unique) as $hashes
    | (
        $peers
        | map(.health.consensus.last_certificate_hash)
        | unique
      ) as $certificates
    | if (
        ($peers | length) == $expected_peer_count and
        ($peers | map(.instance_id) | unique | length) ==
          $expected_peer_count and
        all(
          $peers[];
          .instance_id as $peer_instance
          | any(
              $health_bindings[];
              .instance_id == $peer_instance
            )
        ) and
        ($peers | map(.health.validator_id) | unique | length) ==
          $expected_peer_count and
        all(
          $peers[];
          . as $peer
          | (
              $health_bindings[]
              | select(.instance_id == $peer.instance_id)
            ) as $binding
          | $peer.health.status == "healthy" and
            $peer.health.network == "Public Testnet" and
            $peer.health.validator_id == $binding.validator_id and
            $peer.health.signer_resource_digest ==
              $binding.signer_resource_digest and
            $peer.health.private_key_material_accepted == false and
            $peer.health.mainnet_changed == false and
            $peer.health.assets_moved == false and
            $peer.health.bridge_activated == false and
            ($peer.health.head_height | type) == "number" and
            ($peer.health.head_height | floor) ==
              $peer.health.head_height and
            $peer.health.head_height >= 0 and
            ($peer.health.head_hash | test("^0x[0-9a-f]{64}$")) and
            ($peer.health.consensus.last_certificate_hash |
              test("^0x[0-9a-f]{64}$")) and
            $peer.health.consensus.last_certificate.finality_status ==
              "FINALIZED" and
            $peer.health.consensus.last_certificate.signed_power == 3 and
            $peer.health.consensus.last_certificate.total_power == 3 and
            $peer.health.consensus.last_certificate.validator_ids == [
              "validator-01",
              "validator-02",
              "validator-03"
            ] and
            $peer.health.consensus.last_certificate.mainnet_changed ==
              false and
            $peer.health.consensus.last_certificate.assets_moved == false and
            $peer.health.consensus.last_certificate.bridge_activated ==
              false and
            $peer.health.consensus.last_certificate.height ==
              $peer.health.head_height and
            $peer.health.consensus.last_certificate.block_hash ==
              $peer.health.head_hash
        ) and
        ($heights | length) == 1 and
        ($hashes | length) == 1 and
        ($certificates | length) == 1 and
        $heights[0] >= $previous_height and
        (
          $previous_height < 0 or
          $heights[0] > $previous_height or
          (
            $hashes[0] == $previous_hash and
            $certificates[0] == $previous_certificate
          )
        )
      )
      then {
        checkpoint: $checkpoint,
        excluded_instance_id: (
          if $excluded == "" then null else $excluded end
        ),
        peer_count: ($peers | length),
        quorum: "3/3",
        head_height: $heights[0],
        head_hash: $hashes[0],
        certificate_hash: $certificates[0],
        peers: $peers
      }
      else error("validator quorum/finality continuity check failed")
      end
  ' "${invocation_paths[@]}" >"$checkpoint_path"
  jq -c . "$checkpoint_path" >>"$quorum_evidence_jsonl"
  last_quorum_height="$(jq -er '.head_height' "$checkpoint_path")"
  last_quorum_hash="$(jq -er '.head_hash' "$checkpoint_path")"
  last_quorum_certificate="$(jq -er '.certificate_hash' "$checkpoint_path")"
}

restart_on_controller_error() {
  status=$?
  trap - ERR EXIT INT TERM
  set +e
  if [[ -n "$active_command_id" && -n "$current_instance" ]]; then
    aws ssm cancel-command --command-id "$active_command_id" >/dev/null 2>&1
    wait_ssm_command "$active_command_id" "$current_instance" 1
  fi
  if [[ -n "$current_instance" ]]; then
    recovery_id="$(
      aws ssm send-command \
        --instance-ids "$current_instance" \
        --document-name AWS-RunShellScript \
        --parameters \
          '{"commands":["systemctl start junca-validator","for attempt in $(seq 1 60); do curl -fsS http://127.0.0.1:8545/health >/dev/null && exit 0; sleep 2; done; exit 1"]}' \
        --comment "JUNCA validator state migration rollback" \
        --timeout-seconds 180 \
        --query Command.CommandId --output text 2>/dev/null
    )"
    if [[ -n "$recovery_id" ]]; then
      wait_ssm_command "$recovery_id" "$current_instance" 24
    fi
  fi
  exit "$status"
}

if [[ "$already_accepted" == true ]]; then
  mapfile -t rollback_snapshots < <(
    jq -er '.validator_state_volume_readback.value[].rollback_snapshot_id' \
      "$outputs"
  )
  for validator_index in 0 1 2; do
    run_node_phase \
      "${instances[$validator_index]}" \
      "${volumes[$validator_index]}" \
      "${signer_arns[$validator_index]}" \
      verify \
      "$artifact_dir/ssm/verify-${validator_index}.json"
    accepted_root_volume="$(
      read_snapshot_root_volume \
        "${rollback_snapshots[$validator_index]}" \
        "$artifact_dir/readback/accepted-snapshot-${validator_index}.json"
    )"
    record_validator_evidence \
      "$validator_index" \
      "${instances[$validator_index]}" \
      "${volumes[$validator_index]}" \
      "${signer_arns[$validator_index]}" \
      "${rollback_snapshots[$validator_index]}" \
      "$accepted_root_volume" \
      "$artifact_dir/ssm/verify-${validator_index}.json" \
      "$last_node_binding" \
      accepted-rerun
    require_peer_health "" "accepted-verify-${validator_index}"
  done
else
  trap restart_on_controller_error ERR EXIT INT TERM

  for validator_index in 0 1 2; do
    instance_id="${instances[$validator_index]}"
    volume_id="${volumes[$validator_index]}"
    signer_arn="${signer_arns[$validator_index]}"
    current_instance="$instance_id"
    existing_migration_state="$(
      jq -r --arg volume "$volume_id" '
        [
          .Volumes[]
          | select(.VolumeId == $volume)
          | .Tags[]?
          | select(.Key == "JuncaMigrationState")
          | .Value
        ]
        | if length == 0 then "" elif length == 1 then .[0]
          else error("duplicate migration state tag") end
      ' "$artifact_dir/readback/volumes-before.json"
    )"
    if [[ "$existing_migration_state" == "VERIFIED_PASS" ]]; then
      existing_snapshot="$(
        jq -er --arg volume "$volume_id" '
          [
            .Volumes[]
            | select(.VolumeId == $volume)
            | .Tags[]?
            | select(.Key == "JuncaRollbackSnapshotId")
            | .Value
          ]
          | if length == 1 then .[0]
            else error("exact rollback snapshot tag required") end
        ' "$artifact_dir/readback/volumes-before.json"
      )"
      [[ "$existing_snapshot" =~ ^snap-[0-9a-f]{8,17}$ ]]
      jq -e --arg volume "$volume_id" '
        [
          .Volumes[]
          | select(.VolumeId == $volume)
          | .Tags
          | map({(.Key): .Value})
          | add
        ]
        | if length == 1 then .[0] else error("exact volume required") end
        | .MigrationRequired == "false" and
          .JuncaMigrationState == "VERIFIED_PASS" and
          .JuncaFilesystemVerified == "true" and
          .JuncaStateStoreIntegrity == "true" and
          .JuncaFinalityCertificateRecovered == "true"
      ' "$artifact_dir/readback/volumes-before.json" >/dev/null
      run_node_phase "$instance_id" "$volume_id" "$signer_arn" verify \
        "$artifact_dir/ssm/verify-${validator_index}.json"
      existing_root_volume="$(
        read_snapshot_root_volume \
          "$existing_snapshot" \
          "$artifact_dir/readback/resume-snapshot-${validator_index}.json"
      )"
      record_validator_evidence \
        "$validator_index" "$instance_id" "$volume_id" "$signer_arn" \
        "$existing_snapshot" "$existing_root_volume" \
        "$artifact_dir/ssm/verify-${validator_index}.json" \
        "$last_node_binding" partial-apply-resume
      rollback_snapshots+=("$existing_snapshot")
      current_instance=""
      require_peer_health "" "resume-${validator_index}-after"
      continue
    fi
    test -z "$existing_migration_state"
    require_peer_health "$instance_id" "validator-${validator_index}-before"
    run_node_phase "$instance_id" "$volume_id" "$signer_arn" prepare \
      "$artifact_dir/ssm/prepare-${validator_index}.json"

    instance_json="$artifact_dir/readback/instance-${validator_index}.json"
    aws ec2 describe-instances --instance-ids "$instance_id" \
      >"$instance_json"
    root_device="$(
      jq -er '
        [.Reservations[].Instances[]]
        | if length == 1 then .[0].RootDeviceName
          else error("exact instance required") end
      ' "$instance_json"
    )"
    root_volume="$(
      jq -er --arg root "$root_device" '
        [.Reservations[].Instances[].BlockDeviceMappings[]
         | select(.DeviceName == $root)
         | .Ebs.VolumeId]
        | if length == 1 then .[0]
          else error("exact root volume required") end
      ' "$instance_json"
    )"
    [[ "$root_volume" =~ ^vol-[0-9a-f]{8,17}$ ]]
    jq -n \
      --arg validator "$(printf 'validator-%02d' "$((validator_index + 1))")" \
      --arg instance "$instance_id" \
      --arg state_volume "$volume_id" \
      --arg token "$migration_token" \
      --arg run_id "$GITHUB_RUN_ID" \
      --arg run_attempt "$GITHUB_RUN_ATTEMPT" \
      --arg head_sha "$GITHUB_SHA" \
      --arg migration_request_sha256 "$MIGRATION_REQUEST_SHA256" \
      --arg github_event_sha256 "$github_event_sha256" '
      [{
        ResourceType: "snapshot",
        Tags: [
          {Key: "Name", Value: ("junca-public-testnet-" + $validator + "-rollback")},
          {Key: "Validator", Value: $validator},
          {Key: "InstanceId", Value: $instance},
          {Key: "StateVolumeId", Value: $state_volume},
          {Key: "MigrationToken", Value: $token},
          {Key: "GitHubRunId", Value: $run_id},
          {Key: "GitHubRunAttempt", Value: $run_attempt},
          {Key: "HeadCommit", Value: $head_sha},
          {Key: "MigrationRequestSHA256", Value: $migration_request_sha256},
          {Key: "GitHubEventSHA256", Value: $github_event_sha256},
          {Key: "Network", Value: "Public Testnet"},
          {Key: "MainnetChanged", Value: "false"},
          {Key: "AssetsMoved", Value: "false"},
          {Key: "BridgeActivated", Value: "false"}
        ]
      }]
    ' >"$artifact_dir/readback/snapshot-tags-${validator_index}.json"
    snapshot_id="$(
      aws ec2 create-snapshot \
        --volume-id "$root_volume" \
        --description \
          "JUNCA Public Testnet validator root rollback before durable-state migration" \
        --tag-specifications \
          "file://$artifact_dir/readback/snapshot-tags-${validator_index}.json" \
        --query SnapshotId --output text
    )"
    [[ "$snapshot_id" =~ ^snap-[0-9a-f]{8,17}$ ]]
    aws ec2 wait snapshot-completed --snapshot-ids "$snapshot_id"
    aws ec2 describe-snapshots --snapshot-ids "$snapshot_id" \
      >"$artifact_dir/readback/snapshot-${validator_index}.json"
    jq -e \
      --arg owner "$AWS_ACCOUNT_ID" \
      --arg snapshot "$snapshot_id" \
      --arg root_volume "$root_volume" '
      (.Snapshots | length) == 1 and
      .Snapshots[0].SnapshotId == $snapshot and
      .Snapshots[0].VolumeId == $root_volume and
      .Snapshots[0].OwnerId == $owner and
      .Snapshots[0].Encrypted == true and
      .Snapshots[0].State == "completed"
    ' "$artifact_dir/readback/snapshot-${validator_index}.json" >/dev/null

    run_node_phase "$instance_id" "$volume_id" "$signer_arn" migrate \
      "$artifact_dir/ssm/migrate-${validator_index}.json"
    jq -e '
      .StandardOutputContent
      | fromjson
      | .state == "VERIFIED_PASS" or .state == "ALREADY_MIGRATED"
    ' "$artifact_dir/ssm/migrate-${validator_index}.json" >/dev/null
    record_validator_evidence \
      "$validator_index" "$instance_id" "$volume_id" "$signer_arn" \
      "$snapshot_id" "$root_volume" \
      "$artifact_dir/ssm/migrate-${validator_index}.json" \
      "$last_node_binding" migrated
    aws ec2 create-tags --resources "$volume_id" --tags \
      Key=MigrationRequired,Value=false \
      Key=JuncaMigrationState,Value=VERIFIED_PASS \
      Key=JuncaFilesystemVerified,Value=true \
      Key=JuncaStateStoreIntegrity,Value=true \
      Key=JuncaFinalityCertificateRecovered,Value=true \
      Key=JuncaRollbackSnapshotId,Value="$snapshot_id" \
      Key=MainnetChanged,Value=false \
      Key=AssetsMoved,Value=false \
      Key=BridgeActivated,Value=false
    rollback_snapshots+=("$snapshot_id")
    current_instance=""
    require_peer_health "" "validator-${validator_index}-after"
  done
  trap - ERR EXIT
fi

test "${#rollback_snapshots[@]}" = 3
rollback_json="$(
  printf '%s\n' "${rollback_snapshots[@]}" |
    jq -Rsc 'split("\n")[:-1]'
)"
outputs="$artifact_dir/readback/pre-migration-outputs.json"
write_tfvars true "$rollback_json"
terraform -chdir="$runtime_dir" plan -input=false \
  -var-file="$artifact_dir/validator-state-migration.auto.tfvars.json" \
  -out="$artifact_dir/validator-state-acceptance.tfplan"
terraform -chdir="$runtime_dir" show -json \
  "$artifact_dir/validator-state-acceptance.tfplan" \
  >"$artifact_dir/validator-state-acceptance-plan.json"
jq -e --argjson snapshot_ids "$rollback_json" '
  [
    .resource_changes[]?
    | select(.change.actions != ["no-op"] and .change.actions != ["read"])
  ] as $changes
  | ($changes | length) <= 3 and
    ($changes | map(.address) | unique | length) == ($changes | length) and
    all(
      $changes[];
      .change.actions == ["update"] and
      (.address | test("^aws_ebs_volume\\.validator_state\\[[0-2]\\]$")) and
      (
        (.address | capture("\\[(?<index>[0-2])\\]$").index | tonumber)
        as $index
        | (
            .change.before | del(.tags, .tags_all)
          ) == (
            .change.after | del(.tags, .tags_all)
          ) and
          .change.after.encrypted == true and
          .change.after.type == "gp3" and
          .change.after.size == 200 and
          .change.after.iops == 6000 and
          .change.after.throughput == 250 and
          .change.after.snapshot_id == null and
          .change.after.tags.Name == .change.before.tags.Name and
          .change.after.tags.Validator == .change.before.tags.Validator and
          .change.after.tags.FailureDomain ==
            .change.before.tags.FailureDomain and
          .change.after.tags.StatePath == "/var/lib/junca" and
          .change.after.tags.PublicTestnetOnly == "true" and
          .change.after.tags.MigrationRequired == "false" and
          .change.after.tags.JuncaMigrationState == "VERIFIED_PASS" and
          .change.after.tags.JuncaFilesystemVerified == "true" and
          .change.after.tags.JuncaStateStoreIntegrity == "true" and
          .change.after.tags.JuncaFinalityCertificateRecovered == "true" and
          .change.after.tags.JuncaRollbackSnapshotId ==
            $snapshot_ids[$index] and
          (
            .change.after.tags | keys | sort
          ) == (
            [
              "FailureDomain",
              "JuncaFilesystemVerified",
              "JuncaFinalityCertificateRecovered",
              "JuncaMigrationState",
              "JuncaRollbackSnapshotId",
              "JuncaStateStoreIntegrity",
              "MigrationRequired",
              "Name",
              "PublicTestnetOnly",
              "StatePath",
              "Validator"
            ] | sort
          )
      )
    )
' "$artifact_dir/validator-state-acceptance-plan.json" >/dev/null
terraform -chdir="$runtime_dir" apply -input=false -auto-approve \
  "$artifact_dir/validator-state-acceptance.tfplan"

terraform -chdir="$runtime_dir" output -json \
  >"$artifact_dir/readback/post-migration-outputs.json"
aws ec2 describe-volumes --volume-ids "${volumes[@]}" \
  >"$artifact_dir/readback/volumes-after.json"
aws ec2 describe-snapshots --snapshot-ids "${rollback_snapshots[@]}" \
  >"$artifact_dir/readback/rollback-snapshots.json"
jq -s '
  if (
    length == 3 and
    (map(.validator_id) | unique | length) == 3 and
    (map(.instance_id) | unique | length) == 3 and
    (map(.state_volume_id) | unique | length) == 3 and
    (map(.root_volume_id) | unique | length) == 3 and
    (map(.rollback_snapshot_id) | unique | length) == 3
  )
  then sort_by(.validator_id)
  else error("exact one-to-one validator migration mapping required")
  end
' "$validator_evidence_jsonl" \
  >"$artifact_dir/readback/validator-mapping.json"
jq -s '.' "$quorum_evidence_jsonl" \
  >"$artifact_dir/readback/quorum-checkpoints.json"
jq -e \
  --argjson volume_ids \
    "$(printf '%s\n' "${volumes[@]}" | jq -Rsc 'split("\n")[:-1]')" \
  --argjson instance_ids \
    "$(printf '%s\n' "${instances[@]}" | jq -Rsc 'split("\n")[:-1]')" \
  --argjson snapshot_ids \
    "$(printf '%s\n' "${rollback_snapshots[@]}" |
      jq -Rsc 'split("\n")[:-1]')" \
  --slurpfile validator_mappings \
    "$artifact_dir/readback/validator-mapping.json" '
  .Volumes as $actual_volumes
  | ($actual_volumes | length) == 3 and
  ([.Volumes[].VolumeId] | sort) == ($volume_ids | sort) and
  all(
    .Volumes[];
    .Encrypted == true and
    .VolumeType == "gp3" and
    .Size == 200 and
    .Iops == 6000 and
    .Throughput == 250 and
    .State == "in-use" and
    (.Attachments | length) == 1 and
    (.Attachments[0].InstanceId as $id | $instance_ids | index($id)) != null and
    .Attachments[0].State == "attached" and
    (
      [.Tags[] | select(.Key == "MigrationRequired") | .Value] ==
      ["false"]
    ) and
    (
      [.Tags[] | select(.Key == "JuncaMigrationState") | .Value] ==
      ["VERIFIED_PASS"]
    ) and
    (
      [.Tags[] | select(.Key == "JuncaFilesystemVerified") | .Value] ==
      ["true"]
    ) and
    (
      [.Tags[] | select(.Key == "JuncaStateStoreIntegrity") | .Value] ==
      ["true"]
    ) and
    (
      [.Tags[]
       | select(.Key == "JuncaFinalityCertificateRecovered")
       | .Value] == ["true"]
    ) and
    (
      [.Tags[] | select(.Key == "JuncaRollbackSnapshotId") | .Value][0]
      as $snapshot
      | ($snapshot_ids | index($snapshot)) != null
    )
  ) and
  all(
    $validator_mappings[0][];
    . as $mapping
    | any(
        $actual_volumes[];
        .VolumeId == $mapping.state_volume_id and
        .Attachments[0].InstanceId == $mapping.instance_id
      )
  )
' "$artifact_dir/readback/volumes-after.json" >/dev/null
jq -e \
  --arg owner "$AWS_ACCOUNT_ID" \
  --argjson snapshot_ids \
    "$(printf '%s\n' "${rollback_snapshots[@]}" |
      jq -Rsc 'split("\n")[:-1]')" \
  --slurpfile validator_mappings \
    "$artifact_dir/readback/validator-mapping.json" '
  def tags:
    .Tags | map({(.Key): .Value}) | add;
  .Snapshots as $snapshots
  | ($snapshots | length) == 3 and
  ([.Snapshots[].SnapshotId] | sort) == ($snapshot_ids | sort) and
  all(
    .Snapshots[];
    .OwnerId == $owner and
    .Encrypted == true and
    .State == "completed"
  ) and
  all(
    $validator_mappings[0][];
    . as $mapping
    | any(
        $snapshots[];
        .SnapshotId == $mapping.rollback_snapshot_id and
        .VolumeId == $mapping.root_volume_id and
        (tags) as $tags
        | $tags.Validator == $mapping.validator_id and
          $tags.InstanceId == $mapping.instance_id and
          $tags.StateVolumeId == $mapping.state_volume_id and
          ($tags.MigrationToken | test("^[0-9]+-[1-9][0-9]*$")) and
          ($tags.GitHubRunId | test("^[0-9]+$")) and
          ($tags.GitHubRunAttempt | test("^[1-9][0-9]*$")) and
          ($tags.HeadCommit | test("^[0-9a-f]{40}$")) and
          ($tags.MigrationRequestSHA256 | test("^[0-9a-f]{64}$")) and
          ($tags.GitHubEventSHA256 | test("^[0-9a-f]{64}$")) and
          $tags.Network == "Public Testnet" and
          $tags.MainnetChanged == "false" and
          $tags.AssetsMoved == "false" and
          $tags.BridgeActivated == "false"
      )
  )
' "$artifact_dir/readback/rollback-snapshots.json" >/dev/null
jq -e \
  --argjson snapshots \
    "$(printf '%s\n' "${rollback_snapshots[@]}" |
      jq -Rsc 'split("\n")[:-1]')" '
  (.validator_state_volume_readback.value | length) == 3 and
  all(.validator_state_volume_readback.value[];
    .migration_required == false and
    .migration_accepted == true and
    .runtime_required == false
  ) and
  (
    [.validator_state_volume_readback.value[].rollback_snapshot_id] | sort
  ) == ($snapshots | sort) and
  .runtime_boundary.value.mainnet_changed == false and
  .runtime_boundary.value.assets_moved == false and
  .runtime_boundary.value.bridge_activated == false
' "$artifact_dir/readback/post-migration-outputs.json" >/dev/null

jq -e \
  --arg run_id "$GITHUB_RUN_ID" \
  --argjson run_attempt "$GITHUB_RUN_ATTEMPT" \
  --arg head_sha "$GITHUB_SHA" \
  --arg migration_request_sha256 "$MIGRATION_REQUEST_SHA256" \
  --arg github_event_sha256 "$github_event_sha256" \
  --slurpfile quorum "$artifact_dir/readback/quorum-checkpoints.json" '
  length == 3 and
  all(
    .[];
    .request_binding.run_id == $run_id and
    .request_binding.run_attempt == $run_attempt and
    .request_binding.head_sha == $head_sha and
    .request_binding.migration_request_sha256 ==
      $migration_request_sha256 and
    .request_binding.github_event_sha256 == $github_event_sha256 and
    (.request_binding.ssm_request_sha256 |
      test("^[0-9a-f]{64}$")) and
    (.request_binding.command_id | length) > 0 and
    (.node_result.state == "VERIFIED_PASS" or
     .node_result.state == "ALREADY_MIGRATED") and
    (.node_result.state_sha256 | test("^[0-9a-f]{64}$")) and
    (
      (.node_result.after_height // .node_result.head_height)
      <= $quorum[0][-1].head_height
    )
  ) and
  ($quorum[0] | length) >= 3 and
  $quorum[0][-1].peer_count == 3 and
  $quorum[0][-1].quorum == "3/3"
' "$artifact_dir/readback/validator-mapping.json" >/dev/null

jq \
  --slurpfile mappings "$artifact_dir/readback/validator-mapping.json" \
  --slurpfile snapshots "$artifact_dir/readback/rollback-snapshots.json" '
  def tags:
    .Tags | map({(.Key): .Value}) | add;
  $mappings[0]
  | map(
      . as $mapping
      | (
          $snapshots[0].Snapshots[]
          | select(.SnapshotId == $mapping.rollback_snapshot_id)
          | tags
        ) as $snapshot_tags
      | . + {
          snapshot_binding: {
            migration_token: $snapshot_tags.MigrationToken,
            run_id: $snapshot_tags.GitHubRunId,
            run_attempt: ($snapshot_tags.GitHubRunAttempt | tonumber),
            head_sha: $snapshot_tags.HeadCommit,
            migration_request_sha256:
              $snapshot_tags.MigrationRequestSHA256,
            github_event_sha256: $snapshot_tags.GitHubEventSHA256
          }
        }
    )
' >"$artifact_dir/readback/validator-mapping-bound.json"

jq -n \
  --arg account_id "$AWS_ACCOUNT_ID" \
  --arg region "$AWS_REGION" \
  --arg role_arn "$DEPLOYMENT_ROLE_ARN" \
  --arg repository "$GITHUB_REPOSITORY" \
  --arg run_id "$GITHUB_RUN_ID" \
  --argjson run_attempt "$GITHUB_RUN_ATTEMPT" \
  --arg head_sha "$GITHUB_SHA" \
  --arg migration_request_sha256 "$MIGRATION_REQUEST_SHA256" \
  --arg github_event_sha256 "$github_event_sha256" \
  --arg migration_token "$migration_token" \
  --argjson instance_ids \
    "$(printf '%s\n' "${instances[@]}" | jq -Rsc 'split("\n")[:-1]')" \
  --argjson state_volume_ids \
    "$(printf '%s\n' "${volumes[@]}" | jq -Rsc 'split("\n")[:-1]')" \
  --argjson rollback_snapshot_ids \
    "$(printf '%s\n' "${rollback_snapshots[@]}" |
      jq -Rsc 'split("\n")[:-1]')" \
  --slurpfile validator_mappings \
    "$artifact_dir/readback/validator-mapping-bound.json" \
  --slurpfile quorum_checkpoints \
    "$artifact_dir/readback/quorum-checkpoints.json" '
  {
    schema_version: "junca-validator-state-migration/v1",
    state: "VERIFIED_PASS",
    network: "Public Testnet",
    notice: "Public Testnet / No Monetary Value",
    account_id: $account_id,
    region: $region,
    deployment_role_arn: $role_arn,
    instance_ids: $instance_ids,
    state_volume_ids: $state_volume_ids,
    rollback_snapshot_ids: $rollback_snapshot_ids,
    execution_binding: {
      repository: $repository,
      run_id: $run_id,
      run_attempt: $run_attempt,
      head_sha: $head_sha,
      migration_request_sha256: $migration_request_sha256,
      github_event_sha256: $github_event_sha256,
      migration_token: $migration_token
    },
    validator_mappings: $validator_mappings[0],
    quorum_checkpoints: $quorum_checkpoints[0],
    finalized_head: {
      height: $quorum_checkpoints[0][-1].head_height,
      hash: $quorum_checkpoints[0][-1].head_hash,
      certificate_hash:
        $quorum_checkpoints[0][-1].certificate_hash
    },
    serial_migration: true,
    terraform_canonicalized: true,
    runtime_mount_verified: true,
    immutable_runtime_mount_activation_pending: true,
    bootstrap_changed: false,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false
  }
' >"$artifact_dir/junca-validator-state-migration.json"
(
  cd "$artifact_dir"
  sha256sum junca-validator-state-migration.json >SHA256SUMS
)
