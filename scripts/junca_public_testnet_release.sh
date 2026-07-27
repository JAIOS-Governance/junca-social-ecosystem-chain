#!/usr/bin/env bash
set -euo pipefail

required_env=(
  AWS_ACCOUNT_ID AWS_REGION STATE_BUCKET_NAME DOMAIN_NAME ROUTE53_ZONE_ID
  NODE_AMI_ID NODE_ARTIFACT_SHA256 GENESIS_SHA256 SOURCE_COMMIT
  AVAILABILITY_ZONES_JSON DEPLOYMENT_ROLE_ARN
  QUORUM_ACCEPTANCE_SHA256 RUNTIME_ACCEPTANCE_SHA256
)
for name in "${required_env[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "missing required environment: $name" >&2; exit 2; }
done

[[ "$AWS_ACCOUNT_ID" == "595710543956" ]]
[[ "$AWS_REGION" == "us-east-1" ]]
[[ "$DEPLOYMENT_ROLE_ARN" == "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment" ]]
[[ "$QUORUM_ACCEPTANCE_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$RUNTIME_ACCEPTANCE_SHA256" =~ ^[0-9a-f]{64}$ ]]

mkdir -p artifacts
terraform -chdir=infra/aws/bootstrap init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/bootstrap.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="encrypt=true"
terraform -chdir=infra/aws/bootstrap output -json > artifacts/bootstrap-outputs.json

state_kms_key_arn="$(jq -er .state_kms_key_arn.value artifacts/bootstrap-outputs.json)"
lock_table="$(jq -er .lock_table.value artifacts/bootstrap-outputs.json)"
signer_arns="$(jq -ce '.validator_signer_arns.value | select(length == 3 and (unique | length) == 3)' artifacts/bootstrap-outputs.json)"

terraform -chdir=infra/aws/public-testnet init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$lock_table" \
  -backend-config="encrypt=true" \
  -backend-config="kms_key_id=$state_kms_key_arn"

terraform -chdir=infra/aws/public-testnet output -json \
  > artifacts/pre-public-release-outputs.json

# Public-service publication must preserve the durable validator state exactly.
# Omitting these opt-in values would make Terraform plan their removal even
# though the retained volumes themselves are protected by prevent_destroy.
validator_state="$(
  jq -ce '
    .validator_state_volume_readback.value
    | select(
        length == 3 and
        (map(.validator_id) | sort) ==
          ["validator-01", "validator-02", "validator-03"] and
        all(.encrypted == true) and
        all(.type == "gp3") and
        all(.migration_required == false) and
        all(.migration_accepted == true) and
        all(.state_path == "/var/lib/junca") and
        (map(.volume_id) | unique | length) == 3 and
        all(.volume_id | test("^vol-[0-9a-f]{8,17}$")) and
        (map(.size_gib) | unique | length) == 1 and
        (map(.iops) | unique | length) == 1 and
        (map(.throughput_mibps) | unique | length) == 1
      )
  ' artifacts/pre-public-release-outputs.json
)"
validator_state_volume_size_gib="$(
  jq -er '.[0].size_gib' <<<"$validator_state"
)"
validator_state_volume_iops="$(
  jq -er '.[0].iops' <<<"$validator_state"
)"
validator_state_volume_throughput_mibps="$(
  jq -er '.[0].throughput_mibps' <<<"$validator_state"
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
  ' <<<"$validator_state"
)"
validator_state_rollback_snapshot_ids="$(
  jq -ce '
    map(.rollback_snapshot_id)
    | select(
        length == 3 and
        (unique | length) == 3 and
        all(.[]; type == "string" and test("^snap-[0-9a-f]{8,17}$"))
      )
  ' <<<"$validator_state"
)"

automatic_finality="$(
  jq -ce '
    .automatic_finality_readback.value
    | select(
        .enabled == true and
        .block_interval_seconds == 30 and
        (.slot_epoch_seconds | type) == "number" and
        .slot_epoch_seconds > 0 and
        .slot_epoch_seconds % 30 == 0
      )
  ' artifacts/pre-public-release-outputs.json
)"
automatic_finality_enabled="$(jq -er .enabled <<<"$automatic_finality")"
validator_block_interval_seconds="$(
  jq -er .block_interval_seconds <<<"$automatic_finality"
)"
validator_slot_epoch_seconds="$(
  jq -er .slot_epoch_seconds <<<"$automatic_finality"
)"

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
  --arg quorum "$QUORUM_ACCEPTANCE_SHA256" \
  --arg runtime "$RUNTIME_ACCEPTANCE_SHA256" \
  --argjson enable_validator_state_volumes true \
  --argjson provision_validator_state_volumes true \
  --argjson validator_state_migration_accepted true \
  --argjson validator_state_rollback_snapshot_ids \
    "$validator_state_rollback_snapshot_ids" \
  --argjson validator_state_volume_size_gib \
    "$validator_state_volume_size_gib" \
  --argjson validator_state_volume_iops "$validator_state_volume_iops" \
  --argjson validator_state_volume_throughput_mibps \
    "$validator_state_volume_throughput_mibps" \
  --argjson validator_state_snapshot_ids "$validator_state_snapshot_ids" \
  --argjson automatic_finality_enabled "$automatic_finality_enabled" \
  --argjson validator_block_interval_seconds \
    "$validator_block_interval_seconds" \
  --argjson validator_slot_epoch_seconds "$validator_slot_epoch_seconds" \
  --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
  --argjson validator_signer_arns "$signer_arns" \
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
    enable_public_services: true,
    quorum_acceptance_sha256: $quorum,
    runtime_acceptance_sha256: $runtime
  }' > artifacts/public-release.auto.tfvars.json

terraform -chdir=infra/aws/public-testnet plan -input=false \
  -var-file="$GITHUB_WORKSPACE/artifacts/public-release.auto.tfvars.json" \
  -out="$GITHUB_WORKSPACE/artifacts/public-release.tfplan"
terraform -chdir=infra/aws/public-testnet show -json \
  "$GITHUB_WORKSPACE/artifacts/public-release.tfplan" > artifacts/public-release-plan.json

jq -e '
  [.resource_changes[]? | select(.change.actions | index("delete"))] | length == 0
' artifacts/public-release-plan.json >/dev/null

jq -e '
  [
    .resource_changes[]?
    | select(.address | test("^aws_instance\\.validator\\[[0-2]\\]$"))
    | select(.change.actions != ["no-op"] and .change.actions != ["read"])
  ] | length == 0
' artifacts/public-release-plan.json >/dev/null

jq -e '
  [
    .resource_changes[]?
    | select(.change.actions != ["no-op"] and .change.actions != ["read"])
    | select((
        (.address | test("^aws_security_group\\.validator$")) or
        (.address | test("^aws_security_group\\.public_alb\\[0\\]$")) or
        (.address | test("^aws_lb\\.public\\[0\\]$")) or
        (.address | test("^aws_lb_target_group\\.(rpc|explorer)\\[0\\]$")) or
        (.address | test("^aws_lb_target_group_attachment\\.(rpc|explorer)\\[[0-2]\\]$")) or
        (.address | test("^aws_wafv2_web_acl\\.public\\[0\\]$")) or
        (.address | test("^aws_wafv2_web_acl_association\\.public\\[0\\]$")) or
        (.address | test("^aws_lb_listener\\.https\\[0\\]$")) or
        (.address | test("^aws_lb_listener_certificate\\.scan\\[0\\]$")) or
        (.address | test("^aws_lb_listener_rule\\.(rpc|explorer|scan_redirect)\\[0\\]$")) or
        (.address | test("^aws_route53_record\\.public\\[")) or
        (.address | test("^aws_acm_certificate\\.scan$")) or
        (.address | test("^aws_route53_record\\.scan_certificate_validation\\[")) or
        (.address | test("^aws_acm_certificate_validation\\.scan$"))
      ) | not)
    | .address
  ] | length == 0
' artifacts/public-release-plan.json >/dev/null

terraform -chdir=infra/aws/public-testnet apply -input=false -auto-approve \
  "$GITHUB_WORKSPACE/artifacts/public-release.tfplan"
terraform -chdir=infra/aws/public-testnet output -json > artifacts/public-release-outputs.json

jq -e --arg quorum "$QUORUM_ACCEPTANCE_SHA256" --arg runtime "$RUNTIME_ACCEPTANCE_SHA256" '
  .deployment_stage.value == "public-services" and
  .public_rpc_url.value == "https://rpc.jaios-governance.org" and
  .explorer_url.value == "https://explorer.jaios-governance.org" and
  .scan_url.value == "https://scan.jaios-governance.org" and
  .health_url.value == "https://health.jaios-governance.org" and
  .public_services_acceptance_readback.value.enabled == true and
  .public_services_acceptance_readback.value.quorum_evidence_sha256 == $quorum and
  .public_services_acceptance_readback.value.runtime_evidence_sha256 == $runtime and
  .automatic_finality_readback.value.enabled == true and
  .automatic_finality_readback.value.block_interval_seconds == 30 and
  (.automatic_finality_readback.value.slot_epoch_seconds | type) == "number" and
  .automatic_finality_readback.value.slot_epoch_seconds > 0 and
  .automatic_finality_readback.value.slot_epoch_seconds % 30 == 0 and
  .runtime_boundary.value.mainnet_changed == false and
  .runtime_boundary.value.assets_moved == false and
  .runtime_boundary.value.bridge_activated == false
' artifacts/public-release-outputs.json >/dev/null
