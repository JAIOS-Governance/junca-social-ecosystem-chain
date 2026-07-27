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
EXPECTED_GENESIS_HASH="${EXPECTED_GENESIS_HASH:-0xdc8200c498d28d23ec834fde6559d5b14f0b05a4ed5178c4b90642310b8660a6}"
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
test "$EXPECTED_GENESIS_HASH" = \
  "0xdc8200c498d28d23ec834fde6559d5b14f0b05a4ed5178c4b90642310b8660a6"
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
backfill_request_path="$artifact_dir/finality-certificate-backfill-request.json"
backfill_request_sha256=""
runtime_dir=infra/aws/public-testnet
node_script=scripts/junca_migrate_validator_state_node.sh
backfill_script=scripts/junca_finality_certificate_backfill.py
test -f "$node_script"
test -f "$backfill_script"
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
terraform -chdir="$runtime_dir" version -json \
  >"$artifact_dir/readback/terraform-version.json"
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
      jq -c '
        .validator_state_volume_readback.value
        | map(.restored_snapshot) as $values
        | if all($values[]; . == null or . == "") then null else $values end
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
    jq -c '
      .public_services_acceptance_readback.value.quorum_evidence_sha256
    ' "$outputs"
  )"
  runtime_sha256="$(
    jq -c '
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
      "$(jq -c '
        .automatic_finality_readback.value.enabled // false
      ' "$outputs")" \
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
      -target=aws_ebs_volume.validator_state \
      -out="$artifact_dir/validator-state-provision.tfplan"
    terraform -chdir="$runtime_dir" show -json \
      "$artifact_dir/validator-state-provision.tfplan" \
      >"$artifact_dir/validator-state-provision-plan.json"
    jq -e '
      [
        .resource_changes[]?
        | select(.change.actions != ["no-op"] and .change.actions != ["read"])
      ] as $changes
      | ($changes | length) <= 3 and
        ($changes | map(.address) | unique | length) == ($changes | length) and
        all(
          $changes[];
          .change.actions == ["create"] and
          (
            .address |
            test("^aws_ebs_volume\\.validator_state\\[[0-2]\\]$")
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

# The live validators may legitimately have user-data drift from newly merged
# immutable-runtime source. Planning the attachment resources directly would
# therefore also schedule validator replacement. Attach only the exact new
# volumes, verify the AWS binding, and adopt that binding into the existing
# Terraform state using the provider's canonical import identity.
for validator_index in 0 1 2; do
  instance_id="${instances[$validator_index]}"
  volume_id="${volumes[$validator_index]}"
  expected_az="$(
    jq -er ".availability_zones.value[$validator_index]" "$outputs"
  )"
  attachment_address="aws_volume_attachment.validator_state[$validator_index]"
  attachment_identity="/dev/sdf:${volume_id}:${instance_id}"
  aws ec2 describe-instances --instance-ids "$instance_id" \
    >"$artifact_dir/readback/attachment-${validator_index}-instance.json"
  jq -e \
    --arg instance_id "$instance_id" \
    --arg expected_az "$expected_az" \
    --arg volume_id "$volume_id" '
    [.Reservations[].Instances[]] as $instances
    | [
        $instances[0].BlockDeviceMappings[]?
        | select(.DeviceName == "/dev/sdf")
      ] as $state_devices
    | ($instances | length) == 1 and
      $instances[0].InstanceId == $instance_id and
      $instances[0].State.Name == "running" and
      $instances[0].Placement.AvailabilityZone == $expected_az and
      (
        ($state_devices | length) == 0 or
        (
          ($state_devices | length) == 1 and
          $state_devices[0].Ebs.VolumeId == $volume_id
        )
      )
  ' "$artifact_dir/readback/attachment-${validator_index}-instance.json" \
    >/dev/null
  aws ec2 describe-volumes --volume-ids "$volume_id" \
    >"$artifact_dir/readback/attachment-${validator_index}-before.json"
  jq -e \
    --arg volume_id "$volume_id" \
    --arg expected_az "$expected_az" '
    (.Volumes | length) == 1 and
    .Volumes[0].VolumeId == $volume_id and
    .Volumes[0].AvailabilityZone == $expected_az and
    .Volumes[0].Encrypted == true and
    .Volumes[0].VolumeType == "gp3" and
    .Volumes[0].Size == 200 and
    .Volumes[0].Iops == 6000 and
    .Volumes[0].Throughput == 250 and
    (
      [.Volumes[0].Tags[]? | select(
        .Key == "StatePath" and .Value == "/var/lib/junca"
      )] | length
    ) == 1 and
    (
      [.Volumes[0].Tags[]? | select(
        .Key == "PublicTestnetOnly" and .Value == "true"
      )] | length
    ) == 1 and
    (
      [.Volumes[0].Tags[]? | select(
        .Key == "MigrationRequired" and .Value == "true"
      )] | length
    ) == 1
  ' "$artifact_dir/readback/attachment-${validator_index}-before.json" \
    >/dev/null
  attachment_count="$(
    jq -er '.Volumes[0].Attachments | length' \
      "$artifact_dir/readback/attachment-${validator_index}-before.json"
  )"
  case "$attachment_count" in
    0)
      aws ec2 attach-volume \
        --volume-id "$volume_id" \
        --instance-id "$instance_id" \
        --device /dev/sdf \
        >"$artifact_dir/readback/attachment-${validator_index}-request.json"
      aws ec2 wait volume-in-use --volume-ids "$volume_id"
      ;;
    1)
      jq -e \
        --arg instance_id "$instance_id" '
        .Volumes[0].Attachments[0].InstanceId == $instance_id and
        .Volumes[0].Attachments[0].Device == "/dev/sdf" and
        (
          .Volumes[0].Attachments[0].State == "attaching" or
          .Volumes[0].Attachments[0].State == "attached"
        )
      ' "$artifact_dir/readback/attachment-${validator_index}-before.json" \
        >/dev/null
      aws ec2 wait volume-in-use --volume-ids "$volume_id"
      ;;
    *)
      echo "state volume has an unexpected attachment set: $volume_id" >&2
      exit 1
      ;;
  esac
  aws ec2 describe-volumes --volume-ids "$volume_id" \
    >"$artifact_dir/readback/attachment-${validator_index}-after.json"
  jq -e \
    --arg instance_id "$instance_id" '
    (.Volumes | length) == 1 and
    (.Volumes[0].Attachments | length) == 1 and
    .Volumes[0].Attachments[0].InstanceId == $instance_id and
    .Volumes[0].Attachments[0].Device == "/dev/sdf" and
    .Volumes[0].Attachments[0].State == "attached"
  ' "$artifact_dir/readback/attachment-${validator_index}-after.json" \
    >/dev/null
  if ! terraform -chdir="$runtime_dir" state list |
    grep -Fxq "$attachment_address"; then
    terraform -chdir="$runtime_dir" import -input=false \
      -lock-timeout=5m \
      -var-file="$artifact_dir/validator-state-migration.auto.tfvars.json" \
      "$attachment_address" "$attachment_identity"
  fi
  terraform -chdir="$runtime_dir" state show -no-color \
    "$attachment_address" \
    >"$artifact_dir/readback/attachment-${validator_index}-terraform-state.txt"
  grep -Eq '^[[:space:]]*device_name[[:space:]]*=[[:space:]]*"/dev/sdf"$' \
    "$artifact_dir/readback/attachment-${validator_index}-terraform-state.txt"
  grep -Eq \
    "^[[:space:]]*instance_id[[:space:]]*=[[:space:]]*\"${instance_id}\"$" \
    "$artifact_dir/readback/attachment-${validator_index}-terraform-state.txt"
  grep -Eq \
    "^[[:space:]]*volume_id[[:space:]]*=[[:space:]]*\"${volume_id}\"$" \
    "$artifact_dir/readback/attachment-${validator_index}-terraform-state.txt"
  aws ec2 describe-instance-status \
    --include-all-instances \
    --instance-ids "${instances[@]}" \
    >"$artifact_dir/readback/attachment-${validator_index}-instance-status.json"
  jq -e \
    --argjson instance_ids \
      "$(printf '%s\n' "${instances[@]}" | jq -Rsc 'split("\n")[:-1]')" '
    (.InstanceStatuses | length) == 3 and
    ([.InstanceStatuses[].InstanceId] | sort) == ($instance_ids | sort) and
    all(
      .InstanceStatuses[];
      .InstanceState.Name == "running" and
      .InstanceStatus.Status == "ok" and
      .SystemStatus.Status == "ok"
    )
  ' "$artifact_dir/readback/attachment-${validator_index}-instance-status.json" \
    >/dev/null
done
terraform -chdir="$runtime_dir" output -json >"$outputs"

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
    -target=aws_ebs_volume.validator_state \
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
  local command_id="$1"
  local instance_id="$2"
  local max_attempts="$3"
  local attempt status
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
    local instance_id="$1"
    local volume_id="$2"
    local signer_arn="$3"
    local phase="$4"
    local output_path="$5"
    local encoded backfill_encoded backfill_request_encoded
    local command request_sha256 command_id wait_status submission_path
    encoded="$(gzip -c "$node_script" | base64 -w0)"
    backfill_encoded="$(gzip -c "$backfill_script" | base64 -w0)"
    backfill_request_encoded="$(
      gzip -c "$backfill_request_path" | base64 -w0
    )"
    command="printf '%s' '$encoded' | base64 -d | gzip -d > /tmp/junca-migrate-validator-state; printf '%s' '$backfill_encoded' | base64 -d | gzip -d > /tmp/junca-finality-certificate-backfill.py; printf '%s' '$backfill_request_encoded' | base64 -d | gzip -d > /tmp/junca-finality-certificate-backfill-request.json; chmod 0750 /tmp/junca-migrate-validator-state /tmp/junca-finality-certificate-backfill.py; JUNCA_STATE_VOLUME_ID='$volume_id' JUNCA_EXPECTED_SIGNER_ARN='$signer_arn' JUNCA_MIGRATION_TOKEN='$migration_token' JUNCA_MIGRATION_PHASE='$phase' JUNCA_FINALITY_BACKFILL_TOOL=/tmp/junca-finality-certificate-backfill.py JUNCA_FINALITY_BACKFILL_REQUEST=/tmp/junca-finality-certificate-backfill-request.json JUNCA_FINALITY_BACKFILL_REQUEST_SHA256='$backfill_request_sha256' /tmp/junca-migrate-validator-state"
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
    submission_path="${output_path%.json}-submission.json"
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
      --arg finality_backfill_request_sha256 "$backfill_request_sha256" \
      --arg github_event_sha256 "$github_event_sha256" '{
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
        finality_backfill_request_sha256:
          $finality_backfill_request_sha256,
        github_event_sha256: $github_event_sha256
      }' >"$submission_path"
    active_command_id="$command_id"
    if wait_ssm_command "$command_id" "$instance_id" 180; then
      wait_status=0
    else
      wait_status=$?
    fi
    if ! aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$instance_id" \
      >"$output_path"; then
      test "$wait_status" -ne 0 && return "$wait_status"
      return 125
    fi
    aws ssm list-command-invocations \
      --command-id "$command_id" --details \
      >"${output_path%.json}-details.json" 2>/dev/null || true
    aws ssm list-commands --command-id "$command_id" \
      >"${output_path%.json}-command.json" 2>/dev/null || true
    if [[ "$wait_status" -ne 0 ]]; then
      jq -r '.StandardErrorContent // empty' "$output_path" >&2 || true
      return "$wait_status"
    fi
    jq -e '.Status == "Success"' "$output_path" >/dev/null
    last_node_binding="${output_path%.json}-binding.json"
    cp "$submission_path" "$last_node_binding"
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
    --arg finality_backfill_request_sha256 "$backfill_request_sha256" \
    --arg certificate_hash \
      "$(jq -er '.certificate_hash' "$backfill_request_path")" \
    --slurpfile invocation "$invocation_path" \
    --slurpfile binding "$binding_path" '
    ($invocation[0].StandardOutputContent | fromjson) as $result
    | ($binding[0]) as $request
    | if (
        $invocation | length == 1 and
        $binding | length == 1 and
        $request.instance_id == $instance_id and
        $request.state_volume_id == $state_volume_id and
        $request.finality_backfill_request_sha256 ==
          $finality_backfill_request_sha256 and
        $result.volume_id == $state_volume_id and
        $result.certificate_hash == $certificate_hash and
        $result.state == "VERIFIED_PASS"
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

capture_peer_health_set() {
  local checkpoint="$1"
  local output_path="$2"
  local peer request invocation command_id
  local -a invocation_paths=()
  [[ "$checkpoint" =~ ^[a-z0-9-]+$ ]] || return 1
  for peer in "${instances[@]}"; do
    request="$artifact_dir/ssm/health-set-${checkpoint}-${peer}.json"
    invocation="$artifact_dir/ssm/health-set-${checkpoint}-${peer}-invocation.json"
    if ! jq -n '{
      commands: [
        "set -euo pipefail",
        "curl -fsS http://127.0.0.1:8545/health",
        "systemctl is-active --quiet junca-validator"
      ]
    }' >"$request"; then
      return 1
    fi
    if ! command_id="$(
      aws ssm send-command --instance-ids "$peer" \
        --document-name AWS-RunShellScript \
        --parameters "file://$request" \
        --comment "JUNCA exact runtime health readback ${checkpoint}" \
        --timeout-seconds 300 \
        --query Command.CommandId --output text
    )"; then
      return 1
    fi
    if ! wait_ssm_command "$command_id" "$peer" 30; then
      return 1
    fi
    if ! aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$peer" >"$invocation"; then
      return 1
    fi
    if ! jq -e '.Status == "Success"' "$invocation" >/dev/null; then
      return 1
    fi
    invocation_paths+=("$invocation")
  done
  if ! jq -s '
    map({
      instance_id: .InstanceId,
      command_id: .CommandId,
      health: (
        .StandardOutputContent
        | sub("[\r\n]+$"; "")
        | fromjson
      )
    })
  ' "${invocation_paths[@]}" >"$output_path"; then
    return 1
  fi
  return 0
}

capture_peer_state_heads() {
  local checkpoint="$1"
  local output_path="$2"
  local peer request invocation command_id state_read_command
  local -a invocation_paths=()
  [[ "$checkpoint" =~ ^[a-z0-9-]+$ ]] || return 1
  state_read_command="python3 -c 'import json,sqlite3; db=sqlite3.connect(\"file:/var/lib/junca/state.sqlite?mode=ro\",uri=True); db.row_factory=sqlite3.Row; check=db.execute(\"PRAGMA quick_check\").fetchone()[0]; row=db.execute(\"SELECT height,block_hash,parent_hash,state_root,base_fee_per_gas,gas_used,finalized,certificate_hash FROM blocks ORDER BY height DESC LIMIT 1\").fetchone(); table=db.execute(\"SELECT 1 FROM sqlite_master WHERE type=\\\"table\\\" AND name=\\\"finality_certificates\\\"\").fetchone(); cert=None if table is None else db.execute(\"SELECT certificate_json FROM finality_certificates WHERE height=?\",(row[\"height\"],)).fetchone(); print(json.dumps({\"quick_check\":check,\"head\":dict(row),\"certificate\":None if cert is None else json.loads(cert[\"certificate_json\"])},sort_keys=True,separators=(\",\",\":\")))'"
  for peer in "${instances[@]}"; do
    request="$artifact_dir/ssm/state-head-${checkpoint}-${peer}.json"
    invocation="$artifact_dir/ssm/state-head-${checkpoint}-${peer}-invocation.json"
    if ! jq -n --arg command "$state_read_command" '{
      commands: [
        "set -euo pipefail",
        $command
      ]
    }' >"$request"; then
      return 1
    fi
    if ! command_id="$(
      aws ssm send-command --instance-ids "$peer" \
        --document-name AWS-RunShellScript \
        --parameters "file://$request" \
        --comment "JUNCA read-only durable state head ${checkpoint}" \
        --timeout-seconds 300 \
        --query Command.CommandId --output text
    )"; then
      return 1
    fi
    if ! wait_ssm_command "$command_id" "$peer" 30; then
      return 1
    fi
    if ! aws ssm get-command-invocation \
      --command-id "$command_id" --instance-id "$peer" >"$invocation"; then
      return 1
    fi
    if ! jq -e '.Status == "Success"' "$invocation" >/dev/null; then
      return 1
    fi
    invocation_paths+=("$invocation")
  done
  if ! jq -s '
    map({
      instance_id: .InstanceId,
      command_id: .CommandId,
      state: (
        .StandardOutputContent
        | sub("[\r\n]+$"; "")
        | fromjson
      )
    })
  ' "${invocation_paths[@]}" >"$output_path"; then
    return 1
  fi
  return 0
}

prepare_finality_backfill_request() {
  local health_path state_path
  jq -e '
    .automatic_finality_readback.value.enabled == false and
    .runtime_boundary.value.mainnet_changed == false and
    .runtime_boundary.value.assets_moved == false and
    .runtime_boundary.value.bridge_activated == false
  ' "$outputs" >/dev/null
  health_path="$artifact_dir/readback/finality-backfill-source-health.json"
  state_path="$artifact_dir/readback/finality-backfill-source-state.json"
  capture_peer_health_set "finality-backfill-source" "$health_path"
  capture_peer_state_heads "finality-backfill-source" "$state_path"
  jq -n -e \
    --arg expected_genesis_hash "$EXPECTED_GENESIS_HASH" \
    --argjson health_bindings "$health_bindings" \
    --slurpfile health "$health_path" \
    --slurpfile states "$state_path" '
    ($health[0]) as $peers
    | ($states[0]) as $durable
    | (
        [
          $peers[]
          | select(.health.consensus.last_certificate != null)
          | {
              instance_id,
              validator_id: .health.validator_id,
              head_height: .health.head_height,
              head_hash: .health.head_hash,
              certificate_hash:
                .health.consensus.last_certificate_hash,
              certificate: .health.consensus.last_certificate
            }
        ] + [
          $durable[]
          | select(.state.certificate != null)
          | . as $state
          | (
              $health_bindings[]
              | select(.instance_id == $state.instance_id)
            ) as $binding
          | {
              instance_id,
              validator_id: $binding.validator_id,
              head_height: .state.head.height,
              head_hash: .state.head.block_hash,
              certificate_hash: .state.head.certificate_hash,
              certificate: .state.certificate
            }
        ]
        | sort_by(.instance_id)
        | group_by(.instance_id)
        | map(
            if (map(.certificate | tojson) | unique | length) == 1
            then .[0]
            else error("certificate sources disagree for one validator")
            end
          )
      ) as $observations
    | (
        $observations
        | map(.certificate | tojson)
        | unique
      ) as $certificate_bodies
    | (
        $observations
        | map(.certificate_hash)
        | unique
      ) as $certificate_hashes
    | (
        $observations
        | map(.head_height)
        | unique
      ) as $heights
    | (
        $observations
        | map(.head_hash)
        | unique
      ) as $head_hashes
    | if (
        ($peers | length) == 3 and
        ($durable | length) == 3 and
        ($peers | map(.instance_id) | sort) ==
          ($health_bindings | map(.instance_id) | sort) and
        ($durable | map(.instance_id) | sort) ==
          ($health_bindings | map(.instance_id) | sort) and
        ($observations | length) >= 2 and
        ($observations | map(.instance_id) | unique | length) >= 2 and
        ($observations | map(.validator_id) | unique | length) >= 2 and
        ($certificate_bodies | length) == 1 and
        ($certificate_hashes | length) == 1 and
        ($heights | length) == 1 and
        ($head_hashes | length) == 1 and
        all(
          $peers[];
          . as $peer
          | (
              $health_bindings[]
              | select(.instance_id == $peer.instance_id)
            ) as $binding
          | $peer.health.status == "healthy" and
            $peer.health.network == "Public Testnet / No Monetary Value" and
            $peer.health.chain_id == 20260723 and
            $peer.health.genesis_hash == $expected_genesis_hash and
            $peer.health.validator_id == $binding.validator_id and
            $peer.health.signer_resource_digest ==
              $binding.signer_resource_digest and
            $peer.health.private_key_material_accepted == false and
            $peer.health.head_height == $heights[0] and
            $peer.health.head_hash == $head_hashes[0] and
            $peer.health.consensus.chain_id == 20260723 and
            $peer.health.consensus.pending_height == null and
            $peer.health.consensus.required_vote_count == 3 and
            $peer.health.consensus.quorum_rule ==
              "strictly-greater-than-two-thirds" and
            $peer.health.consensus.private_key_material_accepted == false and
            $peer.health.consensus.mainnet_changed == false and
            $peer.health.consensus.assets_moved == false and
            $peer.health.consensus.bridge_activated == false and
            (
              $peer.health.consensus.signer_bindings
              | map({
                  validator_id,
                  kms_resource_digest
                })
              | sort_by(.validator_id)
            ) == (
              $health_bindings
              | map({
                  validator_id,
                  kms_resource_digest: .signer_resource_digest
                })
              | sort_by(.validator_id)
            ) and
            (
              (
                $peer.health.consensus.last_certificate == null and
                $peer.health.consensus.last_certificate_hash == null and
                $peer.health.consensus.authenticated_vote_count == 0
              ) or (
                ($peer.health.consensus.last_certificate | tojson) ==
                  $certificate_bodies[0] and
                $peer.health.consensus.last_certificate_hash ==
                  $certificate_hashes[0] and
                $peer.health.consensus.authenticated_vote_count == 3
              )
            ) and
            $peer.health.mainnet_changed == false and
            $peer.health.assets_moved == false and
            $peer.health.bridge_activated == false
        ) and
        all(
          $durable[];
          .state.quick_check == "ok" and
          .state.head.height == $heights[0] and
          .state.head.block_hash == $head_hashes[0] and
          .state.head.finalized == 1 and
          .state.head.certificate_hash == $certificate_hashes[0] and
          (
            .state.certificate == null or
            (.state.certificate | tojson) == $certificate_bodies[0]
          )
        )
      )
      then {
        schema_version:
          "junca-finality-certificate-backfill-request/v1",
        network: "Public Testnet / No Monetary Value",
        chain_id: 20260723,
        head_height: $heights[0],
        head_hash: $head_hashes[0],
        certificate_hash: $certificate_hashes[0],
        certificate: ($certificate_bodies[0] | fromjson),
        corroborating_observations: $observations,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }
      else error("durable finality backfill evidence is insufficient")
      end
  ' >"$backfill_request_path"
  python3 - "$backfill_script" "$backfill_request_path" <<'PY'
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("junca_backfill", sys.argv[1])
if spec is None or spec.loader is None:
    raise SystemExit("unable to load certificate backfill validator")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.load_request(Path(sys.argv[2]))
PY
  backfill_request_sha256="$(
    python3 - "$backfill_request_path" <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
canonical = json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
print(hashlib.sha256(canonical).hexdigest())
PY
  )"
  [[ "$backfill_request_sha256" =~ ^[0-9a-f]{64}$ ]]
}

require_migration_continuity() {
  local checkpoint="$1"
  local health_path state_path checkpoint_path
  health_path="$artifact_dir/readback/continuity-${checkpoint}-health.json"
  state_path="$artifact_dir/readback/continuity-${checkpoint}-state.json"
  checkpoint_path="$artifact_dir/readback/quorum-${checkpoint}.json"
  capture_peer_health_set "continuity-${checkpoint}" "$health_path"
  capture_peer_state_heads "continuity-${checkpoint}" "$state_path"
  jq -n -e \
    --arg checkpoint "$checkpoint" \
    --arg expected_genesis_hash "$EXPECTED_GENESIS_HASH" \
    --argjson health_bindings "$health_bindings" \
    --slurpfile request "$backfill_request_path" \
    --slurpfile health "$health_path" \
    --slurpfile states "$state_path" '
    ($request[0]) as $expected
    | ($health[0]) as $peers
    | ($states[0]) as $durable
    | if (
        ($peers | length) == 3 and
        ($durable | length) == 3 and
        ($peers | map(.instance_id) | sort) ==
          ($health_bindings | map(.instance_id) | sort) and
        ($durable | map(.instance_id) | sort) ==
          ($health_bindings | map(.instance_id) | sort) and
        all(
          $peers[];
          . as $peer
          | (
              $health_bindings[]
              | select(.instance_id == $peer.instance_id)
            ) as $binding
          | $peer.health.status == "healthy" and
            $peer.health.network == "Public Testnet / No Monetary Value" and
            $peer.health.chain_id == 20260723 and
            $peer.health.genesis_hash == $expected_genesis_hash and
            $peer.health.validator_id == $binding.validator_id and
            $peer.health.signer_resource_digest ==
              $binding.signer_resource_digest and
            $peer.health.private_key_material_accepted == false and
            $peer.health.head_height == $expected.head_height and
            $peer.health.head_hash == $expected.head_hash and
            $peer.health.consensus.chain_id == 20260723 and
            $peer.health.consensus.pending_height == null and
            $peer.health.consensus.required_vote_count == 3 and
            $peer.health.consensus.quorum_rule ==
              "strictly-greater-than-two-thirds" and
            $peer.health.consensus.private_key_material_accepted == false and
            $peer.health.consensus.mainnet_changed == false and
            $peer.health.consensus.assets_moved == false and
            $peer.health.consensus.bridge_activated == false and
            (
              $peer.health.consensus.signer_bindings
              | map({
                  validator_id,
                  kms_resource_digest
                })
              | sort_by(.validator_id)
            ) == (
              $health_bindings
              | map({
                  validator_id,
                  kms_resource_digest: .signer_resource_digest
                })
              | sort_by(.validator_id)
            ) and
            (
              (
                $peer.health.consensus.last_certificate == null and
                $peer.health.consensus.last_certificate_hash == null and
                $peer.health.consensus.authenticated_vote_count == 0
              ) or (
                $peer.health.consensus.last_certificate ==
                  $expected.certificate and
                $peer.health.consensus.last_certificate_hash ==
                  $expected.certificate_hash and
                $peer.health.consensus.authenticated_vote_count == 3
              )
            ) and
            $peer.health.mainnet_changed == false and
            $peer.health.assets_moved == false and
            $peer.health.bridge_activated == false
        ) and
        all(
          $durable[];
          .state.quick_check == "ok" and
          .state.head.height == $expected.head_height and
          .state.head.block_hash == $expected.head_hash and
          .state.head.finalized == 1 and
          .state.head.certificate_hash == $expected.certificate_hash and
          (
            .state.certificate == null or
            .state.certificate == $expected.certificate
          )
        )
      )
      then {
        checkpoint: $checkpoint,
        peer_count: 3,
        quorum: "durable-certificate-3/3",
        head_height: $expected.head_height,
        head_hash: $expected.head_hash,
        certificate_hash: $expected.certificate_hash,
        certificate_backfilled_instance_ids: (
          [
            $durable[]
            | select(.state.certificate == $expected.certificate)
            | .instance_id
          ] | sort
        ),
        peers: $peers,
        durable_state: $durable,
        mainnet_changed: false,
        assets_moved: false,
        bridge_activated: false
      }
      else error("durable migration continuity check failed")
      end
  ' >"$checkpoint_path"
  jq -c . "$checkpoint_path" >>"$quorum_evidence_jsonl"
  last_quorum_height="$(jq -er '.head_height' "$checkpoint_path")"
  last_quorum_hash="$(jq -er '.head_hash' "$checkpoint_path")"
  last_quorum_certificate="$(jq -er '.certificate_hash' "$checkpoint_path")"
}

restart_on_controller_error() {
  local controller_status="$1"
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
          '{"commands":["systemctl start junca-validator","for attempt in $(seq 1 60); do curl -fsS http://127.0.0.1:8545/health && exit 0; sleep 2; done; exit 1"]}' \
        --comment "JUNCA validator state migration rollback" \
        --timeout-seconds 180 \
        --query Command.CommandId --output text 2>/dev/null
    )"
    if [[ -n "$recovery_id" ]]; then
      wait_ssm_command "$recovery_id" "$current_instance" 24
      aws ssm get-command-invocation \
        --command-id "$recovery_id" --instance-id "$current_instance" \
        >"$artifact_dir/ssm/recovery-${current_instance}.json" 2>/dev/null
    fi
  fi
  exit "$controller_status"
}

prepare_finality_backfill_request

if [[ "$already_accepted" == true ]]; then
  require_migration_continuity "accepted-start"
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
    require_migration_continuity "accepted-verify-${validator_index}"
  done
else
  trap 'restart_on_controller_error "$?"' ERR EXIT
  trap 'restart_on_controller_error 130' INT
  trap 'restart_on_controller_error 143' TERM
  require_migration_continuity "migration-start"

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
          .JuncaFinalityCertificateBackfilled == "true"
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
      require_migration_continuity "resume-${validator_index}-after"
      continue
    fi
    test -z "$existing_migration_state"
    require_migration_continuity "validator-${validator_index}-preflight"
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
      | .state == "MOUNT_ACTIVATED_PENDING_FINALITY"
    ' "$artifact_dir/ssm/migrate-${validator_index}.json" >/dev/null
    current_instance=""
    require_migration_continuity "validator-${validator_index}-after"
    current_instance="$instance_id"
    run_node_phase "$instance_id" "$volume_id" "$signer_arn" verify \
      "$artifact_dir/ssm/verify-${validator_index}.json"
    jq -e '
      .StandardOutputContent
      | fromjson
      | .state == "VERIFIED_PASS"
    ' "$artifact_dir/ssm/verify-${validator_index}.json" >/dev/null
    record_validator_evidence \
      "$validator_index" "$instance_id" "$volume_id" "$signer_arn" \
      "$snapshot_id" "$root_volume" \
      "$artifact_dir/ssm/verify-${validator_index}.json" \
      "$last_node_binding" migrated-and-finality-backfilled
    current_instance=""
    aws ec2 create-tags --resources "$volume_id" --tags \
      Key=MigrationRequired,Value=false \
      Key=JuncaMigrationState,Value=VERIFIED_PASS \
      Key=JuncaFilesystemVerified,Value=true \
      Key=JuncaStateStoreIntegrity,Value=true \
      Key=JuncaFinalityCertificateBackfilled,Value=true \
      Key=JuncaRollbackSnapshotId,Value="$snapshot_id" \
      Key=MainnetChanged,Value=false \
      Key=AssetsMoved,Value=false \
      Key=BridgeActivated,Value=false
    rollback_snapshots+=("$snapshot_id")
  done
  trap - ERR EXIT INT TERM
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
  -target=aws_ebs_volume.validator_state \
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
          .change.after.tags.JuncaFinalityCertificateBackfilled == "true" and
          .change.after.tags.JuncaRollbackSnapshotId ==
            $snapshot_ids[$index] and
          (
            .change.after.tags | keys | sort
          ) == (
            [
              "FailureDomain",
              "JuncaFilesystemVerified",
              "JuncaFinalityCertificateBackfilled",
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
       | select(.Key == "JuncaFinalityCertificateBackfilled")
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
  --arg finality_backfill_request_sha256 "$backfill_request_sha256" \
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
    .request_binding.finality_backfill_request_sha256 ==
      $finality_backfill_request_sha256 and
    .request_binding.github_event_sha256 == $github_event_sha256 and
    (.request_binding.ssm_request_sha256 |
      test("^[0-9a-f]{64}$")) and
    (.request_binding.command_id | length) > 0 and
    .node_result.state == "VERIFIED_PASS" and
    .node_result.certificate_hash ==
      $quorum[0][-1].certificate_hash and
    (.node_result.state_sha256 | test("^[0-9a-f]{64}$")) and
    (
      (.node_result.after_height // .node_result.head_height)
      <= $quorum[0][-1].head_height
    )
  ) and
  ($quorum[0] | length) >= 3 and
  $quorum[0][-1].peer_count == 3 and
  $quorum[0][-1].quorum == "durable-certificate-3/3"
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
  --arg finality_backfill_request_sha256 "$backfill_request_sha256" \
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
      finality_backfill_request_sha256:
        $finality_backfill_request_sha256,
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
    immutable_runtime_certificate_activation_pending: true,
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
