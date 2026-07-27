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
    enable_public_services: false,
    quorum_acceptance_sha256: null,
    runtime_acceptance_sha256: null
  }' > artifacts/foundation.auto.tfvars.json

terraform -chdir=infra/aws/public-testnet plan -input=false \
  -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
  -out="$GITHUB_WORKSPACE/artifacts/foundation.tfplan"
terraform -chdir=infra/aws/public-testnet show -json \
  "$GITHUB_WORKSPACE/artifacts/foundation.tfplan" > artifacts/foundation-plan.json

# Destructive changes remain fail-closed. The only permitted delete action is
# an AMI-driven replacement of one or more of the three canonical validators.
jq -e '
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
      ($deletions | length) >= 1 and
      ($deletions | length) <= 3 and
      ([ $deletions[].address ] | unique | length) == ($deletions | length) and
      all(
        $deletions[];
        (.address == "aws_instance.validator[0]" or
         .address == "aws_instance.validator[1]" or
         .address == "aws_instance.validator[2]") and
        (.actions | index("create")) != null and
        (.actions | index("delete")) != null and
        (.replace_paths | index(["ami"])) != null
      )
    )
' artifacts/foundation-plan.json >/dev/null

mapfile -t validator_replacements < <(
  jq -r '
    .resource_changes[]?
    | select(.change.actions | index("delete"))
    | .address
  ' artifacts/foundation-plan.json
)

apply_executed=false
if [[ "$phase" == "foundation-apply" ]]; then
  if (( ${#validator_replacements[@]} > 0 )); then
    # Rotate one validator at a time. Fixed private IPs require destroy-before-
    # create; SSM Online readback prevents advancing before the replacement is
    # manageable. Other resources remain untouched during each targeted step.
    for address in "${validator_replacements[@]}"; do
      index="${address##*[}"
      index="${index%]}"
      target_plan="$GITHUB_WORKSPACE/artifacts/foundation-validator-${index}.tfplan"
      target_json="artifacts/foundation-validator-${index}-plan.json"

      terraform -chdir=infra/aws/public-testnet plan -input=false \
        -var-file="$GITHUB_WORKSPACE/artifacts/foundation.auto.tfvars.json" \
        -target="$address" \
        -out="$target_plan"
      terraform -chdir=infra/aws/public-testnet show -json "$target_plan" \
        > "$target_json"
      jq -e --arg address "$address" '
        [
          .resource_changes[]?
          | select(.change.actions | index("delete"))
          | {
              address,
              actions: .change.actions,
              replace_paths: (.change.replace_paths // [])
            }
        ] as $deletions
        | ($deletions | length) == 1 and
          $deletions[0].address == $address and
          ($deletions[0].actions | index("create")) != null and
          ($deletions[0].actions | index("delete")) != null and
          ($deletions[0].replace_paths | index(["ami"])) != null
      ' "$target_json" >/dev/null

      terraform -chdir=infra/aws/public-testnet apply -input=false -auto-approve \
        "$target_plan"

      new_instance="$(terraform -chdir=infra/aws/public-testnet output -json \
        validator_instance_ids | jq -er ".[${index}]")"
      for attempt in $(seq 1 60); do
        ping_status="$(aws ssm describe-instance-information \
          --filters "Key=InstanceIds,Values=${new_instance}" \
          --query 'InstanceInformationList[0].PingStatus' --output text)"
        [[ "$ping_status" == "Online" ]] && break
        test "$attempt" -lt 60
        sleep 10
      done
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

  apply_executed=true
  terraform -chdir=infra/aws/public-testnet output -json > artifacts/foundation-outputs.json
  jq -e '
    (.validator_instance_ids.value | length) == 3 and
    .deployment_stage.value == "validators-only" and
    .public_rpc_url.value == null and
    .explorer_url.value == null and
    .health_url.value == null and
    .runtime_boundary.value.governance == "JAIOS Institutional Governance" and
    .runtime_boundary.value.mainnet_changed == false and
    .runtime_boundary.value.assets_moved == false and
    .runtime_boundary.value.bridge_activated == false
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
    deployment_stage: "validators-only",
    apply_executed: $apply_executed,
    quorum_verified: false,
    public_services_enabled: false,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false
  }' > artifacts/foundation-execution-evidence.json
