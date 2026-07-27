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
jq -e --argjson public_services_enabled "$public_services_enabled" '
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
          $deletions[]
          | select(.address | test(
              "^aws_lb_target_group_attachment\\.(rpc|explorer)\\[[0-2]\\]$"
            ))
        ] as $attachments
      | ($validators | length) >= 1 and
        ($validators | length) <= 3 and
        ([ $deletions[].address ] | unique | length) == ($deletions | length) and
        (
          if $public_services_enabled then
            ([ $attachments[].address ] | sort) == ($expected_attachments | sort) and
            ($deletions | length) == (($validators | length) * 3)
          else
            ($attachments | length) == 0 and
            ($deletions | length) == ($validators | length)
          end
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
            )
          )
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
                (.replace_paths | any(.[]; . == ["target_id"]))
              )
            )
          )
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
