#!/usr/bin/env bash
set -euo pipefail

required_env=(
  AWS_ACCOUNT_ID AWS_REGION STATE_BUCKET_NAME DOMAIN_NAME ROUTE53_ZONE_ID
  DEPLOYMENT_ROLE_ARN AVAILABILITY_ZONES_JSON SOURCE_COMMIT
  EXPECTED_VALIDATOR_ID EXPECTED_INSTANCE_ID EXPECTED_AMI_ID
  EXPECTED_RUNTIME_SHA256 EXPECTED_GENESIS_SHA256 EXPECTED_STATE_VOLUME_ID
)
for name in "${required_env[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "missing required recovery environment: $name" >&2
    exit 2
  }
done

test "$AWS_ACCOUNT_ID" = "595710543956"
test "$AWS_REGION" = "us-east-1"
test "$DEPLOYMENT_ROLE_ARN" = \
  "arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment"
test "$EXPECTED_VALIDATOR_ID" = "validator-01"
[[ "$EXPECTED_INSTANCE_ID" =~ ^i-[0-9a-f]{8,17}$ ]]
[[ "$EXPECTED_AMI_ID" =~ ^ami-[0-9a-f]{8,17}$ ]]
[[ "$EXPECTED_RUNTIME_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$EXPECTED_GENESIS_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$EXPECTED_STATE_VOLUME_ID" =~ ^vol-[0-9a-f]{8,17}$ ]]
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
[[ "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]]
test "${GITHUB_REPOSITORY:-}" = \
  "JAIOS-Governance/junca-social-ecosystem-chain"

mkdir -p artifacts/runtime-recovery

aws sts get-caller-identity > artifacts/runtime-recovery/aws-identity.json
jq -e --arg account "$AWS_ACCOUNT_ID" \
  '.Account == $account and (.Arn | contains("JuncaChainPublicTestnetDeployment"))' \
  artifacts/runtime-recovery/aws-identity.json >/dev/null

aws ec2 describe-instances --instance-ids "$EXPECTED_INSTANCE_ID" \
  > artifacts/runtime-recovery/instance.json
jq -e \
  --arg expected_instance "$EXPECTED_INSTANCE_ID" \
  --arg ami "$EXPECTED_AMI_ID" \
  --arg volume "$EXPECTED_STATE_VOLUME_ID" '
    (.Reservations | length) == 1 and
    (.Reservations[0].Instances | length) == 1 and
    .Reservations[0].Instances[0] as $instance |
    $instance.InstanceId == $expected_instance and
    $instance.ImageId == $ami and
    $instance.State.Name == "running" and
    any($instance.Tags[]?; .Key == "Validator" and .Value == "01") and
    any($instance.Tags[]?; .Key == "Network" and .Value == "Public Testnet") and
    any($instance.Tags[]?; .Key == "MonetaryUse" and .Value == "None") and
    any($instance.BlockDeviceMappings[]?;
      .DeviceName == "/dev/sdf" and
      .Ebs.VolumeId == $volume and
      .Ebs.Status == "attached" and
      .Ebs.DeleteOnTermination == false)
  ' artifacts/runtime-recovery/instance.json >/dev/null

aws ec2 describe-volumes --volume-ids "$EXPECTED_STATE_VOLUME_ID" \
  > artifacts/runtime-recovery/volume.json
jq -e \
  --arg expected_instance "$EXPECTED_INSTANCE_ID" \
  --arg volume "$EXPECTED_STATE_VOLUME_ID" '
    (.Volumes | length) == 1 and
    .[0].VolumeId == $volume and
    .[0].Encrypted == true and
    .[0].State == "in-use" and
    (.[0].Attachments | length) == 1 and
    .[0].Attachments[0].InstanceId == $expected_instance and
    .[0].Attachments[0].Device == "/dev/sdf" and
    .[0].Attachments[0].State == "attached" and
    .[0].Attachments[0].DeleteOnTermination == false and
    any(.[0].Tags[]?; .Key == "Validator" and .Value == "01") and
    any(.[0].Tags[]?; .Key == "PublicTestnetOnly" and .Value == "true") and
    any(.[0].Tags[]?; .Key == "MainnetChanged" and .Value == "false") and
    any(.[0].Tags[]?; .Key == "AssetsMoved" and .Value == "false") and
    any(.[0].Tags[]?; .Key == "BridgeActivated" and .Value == "false")
  ' artifacts/runtime-recovery/volume.json >/dev/null

terraform -chdir=infra/aws/bootstrap init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/bootstrap.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="encrypt=true"
terraform -chdir=infra/aws/bootstrap output -json \
  > artifacts/runtime-recovery/bootstrap-outputs.json
lock_table="$(
  jq -er '.lock_table.value' artifacts/runtime-recovery/bootstrap-outputs.json
)"
state_kms_key_arn="$(
  jq -er '.state_kms_key_arn.value' \
    artifacts/runtime-recovery/bootstrap-outputs.json
)"
terraform -chdir=infra/aws/public-testnet init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$lock_table" \
  -backend-config="encrypt=true" \
  -backend-config="kms_key_id=$state_kms_key_arn"
terraform -chdir=infra/aws/public-testnet output -json \
  > artifacts/runtime-recovery/foundation-outputs.json

jq -e \
  --arg instance "$EXPECTED_INSTANCE_ID" \
  --arg volume "$EXPECTED_STATE_VOLUME_ID" '
    .validator_instance_ids.value[0] == $instance and
    .validator_state_volume_readback.value[0].validator_id == "validator-01" and
    .validator_state_volume_readback.value[0].volume_id == $volume and
    .validator_state_volume_readback.value[0].runtime_required == true and
    .validator_state_volume_readback.value[0].migration_accepted == true and
    (.validator_signer_readback.value | length) == 3 and
    all(.validator_signer_readback.value[];
      .enabled == true and
      .key_usage == "SIGN_VERIFY" and
      .customer_master_key_spec == "ECC_SECG_P256K1") and
    .automatic_finality_readback.value == {
      enabled: false,
      block_interval_seconds: 0,
      slot_epoch_seconds: 0
    } and
    .runtime_boundary.value.mainnet_changed == false and
    .runtime_boundary.value.assets_moved == false and
    .runtime_boundary.value.bridge_activated == false
  ' artifacts/runtime-recovery/foundation-outputs.json >/dev/null

signer_arn="$(
  jq -er '.validator_signer_readback.value[0].arn' \
    artifacts/runtime-recovery/foundation-outputs.json
)"
signer_bindings="$(
  jq -er '
    .validator_signer_readback.value
    | to_entries
    | map("validator-0\(.key + 1)=\(.value.arn)")
    | join(",")
  ' artifacts/runtime-recovery/foundation-outputs.json
)"
peer_endpoints="validator-01=10.67.16.10:30303,validator-02=10.67.32.10:30303,validator-03=10.67.48.10:30303"

NODE_AMI_ID="$EXPECTED_AMI_ID"
NODE_ARTIFACT_SHA256="$EXPECTED_RUNTIME_SHA256"
GENESIS_SHA256="$EXPECTED_GENESIS_SHA256"
export NODE_AMI_ID NODE_ARTIFACT_SHA256 GENESIS_SHA256
REQUEST_SHA256="$(
  jq -cnS \
    --arg validator "$EXPECTED_VALIDATOR_ID" \
    --arg instance "$EXPECTED_INSTANCE_ID" \
    --arg ami "$EXPECTED_AMI_ID" \
    --arg runtime "$EXPECTED_RUNTIME_SHA256" \
    --arg volume "$EXPECTED_STATE_VOLUME_ID" \
    --arg source "$SOURCE_COMMIT" \
    --argjson run_id "$GITHUB_RUN_ID" \
    --argjson run_attempt "$GITHUB_RUN_ATTEMPT" '{
      schema_version: "junca-single-validator-runtime-recovery-request/v1",
      validator_id: $validator,
      instance_id: $instance,
      ami_id: $ami,
      runtime_sha256: $runtime,
      state_volume_id: $volume,
      source_commit: $source,
      run_id: $run_id,
      run_attempt: $run_attempt,
      public_testnet_only: true,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false,
      mainnet_activation_authorized: false
    }' | sha256sum | awk '{print $1}'
)"
MANIFEST_DECISION_SHA256="$(
  jq -cnS \
    --arg request "$REQUEST_SHA256" \
    --arg instance "$EXPECTED_INSTANCE_ID" \
    --arg volume "$EXPECTED_STATE_VOLUME_ID" '{
      schema_version: "junca-single-validator-runtime-recovery-decision/v1",
      request_sha256: $request,
      decision: "ALLOW_EXACT_RUNTIME_ENV_REPAIR",
      exact_instance_id: $instance,
      exact_state_volume_id: $volume,
      dispatch_limit: 1,
      terraform_apply_authorized: false,
      instance_replacement_authorized: false,
      public_testnet_only: true
    }' | sha256sum | awk '{print $1}'
)"
ROLLING_CANDIDATE_HEAD_SHA="$SOURCE_COMMIT"
export REQUEST_SHA256 MANIFEST_DECISION_SHA256 ROLLING_CANDIDATE_HEAD_SHA

JUNCA_FOUNDATION_LIBRARY_ONLY=true \
  source scripts/junca_public_testnet_foundation.sh foundation-plan

read_instance_ami_binding \
  "$EXPECTED_INSTANCE_ID" \
  artifacts/runtime-recovery/ami-binding.json
jq -e \
  --arg instance "$EXPECTED_INSTANCE_ID" \
  --arg ami "$EXPECTED_AMI_ID" \
  --arg runtime "$EXPECTED_RUNTIME_SHA256" '
    .instance_id == $instance and
    .instance_state == "running" and
    .ami_id == $ami and
    .runtime_version == $runtime and
    .accepted == true and
    .mainnet_changed == false and
    .assets_moved == false and
    .bridge_activated == false and
    .mainnet_activation_authorized == false
  ' artifacts/runtime-recovery/ami-binding.json >/dev/null

ensure_validator_service_available \
  "$EXPECTED_VALIDATOR_ID" \
  "$EXPECTED_INSTANCE_ID" \
  "$EXPECTED_AMI_ID" \
  "$EXPECTED_RUNTIME_SHA256" \
  "$EXPECTED_GENESIS_SHA256" \
  "$signer_arn" \
  "$signer_bindings" \
  "$peer_endpoints" \
  false 0 0 \
  "$EXPECTED_STATE_VOLUME_ID" \
  true \
  artifacts/runtime-recovery/service-recovery.json

jq -e '
  .accepted == true and
  .runtime_env_repaired == true and
  .runtime_env_source == "canonical" and
  .after_status == "active" and
  .health_status == "healthy" and
  .health_validator_id == "validator-01" and
  .mainnet_changed == false and
  .assets_moved == false and
  .bridge_activated == false and
  .mainnet_activation_authorized == false
' artifacts/runtime-recovery/service-recovery.json >/dev/null

jq -n \
  --arg request_sha256 "$REQUEST_SHA256" \
  --arg decision_sha256 "$MANIFEST_DECISION_SHA256" \
  --arg source_commit "$SOURCE_COMMIT" \
  --arg validator_id "$EXPECTED_VALIDATOR_ID" \
  --arg instance_id "$EXPECTED_INSTANCE_ID" \
  --arg state_volume_id "$EXPECTED_STATE_VOLUME_ID" \
  --slurpfile recovery artifacts/runtime-recovery/service-recovery.json '{
    schema_version: "junca-single-validator-runtime-recovery-acceptance/v1",
    result: "PASS",
    request_sha256: $request_sha256,
    decision_sha256: $decision_sha256,
    source_commit: $source_commit,
    validator_id: $validator_id,
    instance_id: $instance_id,
    state_volume_id: $state_volume_id,
    recovery: $recovery[0],
    terraform_apply_executed: false,
    instance_replacement_executed: false,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false,
    mainnet_activation_authorized: false
  }' > artifacts/runtime-recovery/acceptance.json
sha256sum artifacts/runtime-recovery/acceptance.json \
  > artifacts/runtime-recovery/acceptance.json.sha256
