#!/usr/bin/env bash
# Shared fail-closed caller contract for the six fixed Public Testnet SSM
# Command documents. This file is sourced by reviewed controllers; it performs
# only readback and local evidence writes until junca_fixed_ssm_send_command
# reaches its final aws ssm send-command call.

JUNCA_FIXED_SSM_CALLER_DIRECTORY="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
)"
JUNCA_FIXED_SSM_REPOSITORY_ROOT="$(
  cd "${JUNCA_FIXED_SSM_CALLER_DIRECTORY}/.." && pwd
)"
JUNCA_FIXED_SSM_DOCUMENT_ROOT="${JUNCA_FIXED_SSM_REPOSITORY_ROOT}/infrastructure/aws/ssm-documents"

junca_fixed_ssm_document_version_environment() {
  local document_name="$1"
  case "$document_name" in
    JuncaPTBootstrapReadiness)
      printf '%s\n' JUNCA_PT_BOOTSTRAP_READINESS_VERSION
      ;;
    JuncaPTFinalityInspect)
      printf '%s\n' JUNCA_PT_FINALITY_INSPECT_VERSION
      ;;
    JuncaPTFinalitySet)
      printf '%s\n' JUNCA_PT_FINALITY_SET_VERSION
      ;;
    JuncaPTHealthReadback)
      printf '%s\n' JUNCA_PT_HEALTH_READBACK_VERSION
      ;;
    JuncaPTRestartHealth)
      printf '%s\n' JUNCA_PT_RESTART_HEALTH_VERSION
      ;;
    JuncaPTRuntimeObservation)
      printf '%s\n' JUNCA_PT_RUNTIME_OBSERVATION_VERSION
      ;;
    *)
      printf 'unknown fixed SSM document: %s\n' "$document_name" >&2
      return 2
      ;;
  esac
}

junca_fixed_ssm_document_version() {
  local document_name="$1"
  local environment_name
  local version
  environment_name="$(
    junca_fixed_ssm_document_version_environment "$document_name"
  )" || return
  version="${!environment_name:-}"
  if [[ ! "$version" =~ ^[1-9][0-9]*$ ]]; then
    printf 'missing accepted numeric SSM document version: %s\n' \
      "$environment_name" >&2
    return 2
  fi
  printf '%s\n' "$version"
}

junca_fixed_ssm_validate_repository() {
  local evidence_directory="$1"
  mkdir -p "$evidence_directory"
  python3 -S \
    "${JUNCA_FIXED_SSM_REPOSITORY_ROOT}/scripts/junca_fixed_ssm_document_contract.py" \
    --root "$JUNCA_FIXED_SSM_DOCUMENT_ROOT" \
    >"${evidence_directory}/repository-contract.json"
  jq -e '
    .accepted == true and
    .document_count == 6 and
    .status == "REPOSITORY_CONTRACT_ONLY_NOT_DEPLOYED" and
    .operational_decision ==
      "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT" and
    .mainnet_changed == false and
    .assets_moved == false and
    .bridge_activated == false and
    .transaction_submission_enabled == false
  ' "${evidence_directory}/repository-contract.json" >/dev/null
}

junca_fixed_ssm_validate_document() {
  local document_name="$1"
  local evidence_directory="$2"
  local account_id="${AWS_ACCOUNT_ID:-}"
  local region="${AWS_REGION:-}"
  local version
  local expected_sha256
  local accepted_manifest_version
  local accepted_manifest_sha256
  local observed_sha256
  local get_path
  local describe_path
  local content_path
  local decision_path

  [[ "$account_id" == "595710543956" ]]
  [[ "$region" == "us-east-1" ]]
  version="$(junca_fixed_ssm_document_version "$document_name")" || return
  mkdir -p "$evidence_directory"
  junca_fixed_ssm_validate_repository "$evidence_directory"
  expected_sha256="$(
    jq -er --arg document_name "$document_name" '
      [
        .documents[]
        | select(.name == $document_name)
        | .repository_sha256
      ]
      | select(length == 1)
      | .[0]
      | select(type == "string" and test("^[0-9a-f]{64}$"))
    ' "${JUNCA_FIXED_SSM_DOCUMENT_ROOT}/manifest.json"
  )" || return
  accepted_manifest_version="$(
    jq -er --arg document_name "$document_name" '
      [
        .documents[]
        | select(.name == $document_name)
        | select(.live_readback_present == true)
        | .accepted_live_document_version
      ]
      | select(length == 1)
      | .[0]
      | select(type == "string" and test("^[1-9][0-9]*$"))
    ' "${JUNCA_FIXED_SSM_DOCUMENT_ROOT}/manifest.json"
  )" || {
    printf 'fixed SSM live version is not accepted in manifest: %s\n' \
      "$document_name" >&2
    return 1
  }
  accepted_manifest_sha256="$(
    jq -er --arg document_name "$document_name" '
      [
        .documents[]
        | select(.name == $document_name)
        | select(.live_readback_present == true)
        | .accepted_live_content_sha256
      ]
      | select(length == 1)
      | .[0]
      | select(type == "string" and test("^[0-9a-f]{64}$"))
    ' "${JUNCA_FIXED_SSM_DOCUMENT_ROOT}/manifest.json"
  )" || {
    printf 'fixed SSM live digest is not accepted in manifest: %s\n' \
      "$document_name" >&2
    return 1
  }
  [[ "$accepted_manifest_version" == "$version" ]]
  [[ "$accepted_manifest_sha256" == "$expected_sha256" ]]

  get_path="${evidence_directory}/${document_name}-v${version}-get.json"
  describe_path="${evidence_directory}/${document_name}-describe.json"
  content_path="${evidence_directory}/${document_name}-v${version}-content.yaml"
  decision_path="${evidence_directory}/${document_name}-v${version}-decision.json"

  aws ssm get-document \
    --name "$document_name" \
    --document-version "$version" \
    --document-format YAML \
    --region "$region" \
    --output json >"$get_path"
  jq -e \
    --arg document_name "$document_name" \
    --arg document_version "$version" '
      .Name == $document_name and
      .DocumentVersion == $document_version and
      .Status == "Active" and
      .DocumentType == "Command" and
      .DocumentFormat == "YAML" and
      (.Content | type) == "string"
    ' "$get_path" >/dev/null
  jq -j '.Content' "$get_path" >"$content_path"
  observed_sha256="$(sha256sum "$content_path" | awk '{print $1}')"
  [[ "$observed_sha256" == "$expected_sha256" ]]

  aws ssm describe-document \
    --name "$document_name" \
    --region "$region" \
    --output json >"$describe_path"
  jq -e \
    --arg account_id "$account_id" \
    --arg document_name "$document_name" \
    --arg document_version "$version" '
      .Document.Name == $document_name and
      .Document.Owner == $account_id and
      .Document.DocumentType == "Command" and
      .Document.DocumentFormat == "YAML" and
      .Document.SchemaVersion == "2.2" and
      .Document.Status == "Active" and
      .Document.DocumentVersion == $document_version and
      .Document.LatestVersion == $document_version and
      .Document.DefaultVersion == $document_version
    ' "$describe_path" >/dev/null

  jq -n \
    --arg document_name "$document_name" \
    --arg document_version "$version" \
    --arg repository_sha256 "$expected_sha256" \
    --arg live_content_sha256 "$observed_sha256" '{
      schema_version: "junca-fixed-ssm-live-document-readback/v1",
      document_name: $document_name,
      document_version: $document_version,
      repository_sha256: $repository_sha256,
      live_content_sha256: $live_content_sha256,
      exact_version_is_latest_and_default: true,
      accepted: true,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false
    }' >"$decision_path"
}

junca_fixed_ssm_validate_target() {
  local validator_id="$1"
  local expected_instance_id="$2"
  local evidence_path="$3"
  local account_id="${AWS_ACCOUNT_ID:-}"
  local region="${AWS_REGION:-}"

  [[ "$account_id" == "595710543956" ]]
  [[ "$region" == "us-east-1" ]]
  [[ "$validator_id" =~ ^validator-0[1-3]$ ]]
  [[ "$expected_instance_id" =~ ^i-[0-9a-f]{8,17}$ ]]
  mkdir -p "$(dirname "$evidence_path")"
  aws ec2 describe-instances \
    --region "$region" \
    --filters \
      "Name=instance-state-name,Values=running" \
      "Name=tag:Project,Values=JUNCA Social Ecosystem Chain" \
      "Name=tag:Network,Values=Public Testnet" \
      "Name=tag:Role,Values=Validator" \
      "Name=tag:LaunchContract,Values=JuncaValidatorLaunchV1" \
    --output json >"$evidence_path"
  jq -e \
    --arg validator_id "$validator_id" \
    --arg expected_instance_id "$expected_instance_id" '
      def tag($key):
        [.Tags[]? | select(.Key == $key) | .Value]
        | if length == 1 then .[0] else null end;
      [.Reservations[].Instances[]] as $instances
      | ($instances | length) == 3 and
        ($instances | map(.InstanceId) | unique | length) == 3 and
        (
          $instances
          | map(tag("ValidatorId"))
          | sort
        ) == ["validator-01", "validator-02", "validator-03"] and
        all(
          $instances[];
          .State.Name == "running" and
          (tag("Project")) == "JUNCA Social Ecosystem Chain" and
          (tag("Network")) == "Public Testnet" and
          (tag("Role")) == "Validator" and
          (tag("LaunchContract")) == "JuncaValidatorLaunchV1" and
          (tag("MainnetChanged")) == "false" and
          (tag("AssetsMoved")) == "false" and
          (tag("BridgeActivated")) == "false" and
          (.InstanceId | type) == "string" and
          (.InstanceId | test("^i-[0-9a-f]{8,17}$"))
        ) and
        (
          [
            $instances[]
            | select((tag("ValidatorId")) == $validator_id)
            | .InstanceId
          ]
          == [$expected_instance_id]
        )
    ' "$evidence_path" >/dev/null
}

junca_fixed_ssm_validate_list_command_readback() {
  local readback_path="$1"
  local expected_command_id="$2"
  local document_name="$3"
  local document_version="$4"
  local expected_instance_id="$5"
  jq -e \
    --arg command_id "$expected_command_id" \
    --arg document_name "$document_name" \
    --arg document_version "$document_version" \
    --arg expected_instance_id "$expected_instance_id" '
      (.Commands | type) == "array" and
      (.Commands | length) == 1 and
      .Commands[0].CommandId == $command_id and
      .Commands[0].DocumentName == $document_name and
      .Commands[0].DocumentVersion == $document_version and
      .Commands[0].InstanceIds == [$expected_instance_id] and
      .Commands[0].Targets == [] and
      .Commands[0].TargetCount == 1
    ' "$readback_path" >/dev/null
}

junca_fixed_ssm_send_command() {
  local document_name="$1"
  local validator_id="$2"
  local expected_instance_id="$3"
  local parameters_path="$4"
  local comment="$5"
  local evidence_directory="$6"
  local operation_id="$7"
  local version
  local normalized_parameters_path
  local response_path
  local list_path
  local command_id
  local now_epoch
  local target_count_accepted=false

  [[ "$operation_id" =~ ^[A-Za-z0-9._-]{1,96}$ ]]
  test -f "$parameters_path"
  test ! -L "$parameters_path"
  version="$(junca_fixed_ssm_document_version "$document_name")" || return
  now_epoch="$(date +%s)"
  [[ "$now_epoch" =~ ^[0-9]{1,11}$ ]]
  mkdir -p "$evidence_directory"

  # Every repository, parameter, live-version, digest, fleet-cardinality, tag,
  # and exact-instance readback completes before SendCommand is reachable.
  python3 -S \
    "${JUNCA_FIXED_SSM_REPOSITORY_ROOT}/scripts/junca_fixed_ssm_document_contract.py" \
    --document-name "$document_name" \
    --parameters-file "$parameters_path" \
    --now-epoch "$now_epoch" \
    >"${evidence_directory}/${operation_id}-parameters-decision.json"
  junca_fixed_ssm_validate_document "$document_name" "$evidence_directory"
  junca_fixed_ssm_validate_target \
    "$validator_id" "$expected_instance_id" \
    "${evidence_directory}/${operation_id}-target-readback.json"

  normalized_parameters_path="${evidence_directory}/${operation_id}-parameters.json"
  jq -e '
    type == "object" and
    all(to_entries[]; (.value | type) == "string")
  ' "$parameters_path" >/dev/null
  jq -c 'with_entries(.value = [.value])' \
    "$parameters_path" >"$normalized_parameters_path"
  response_path="${evidence_directory}/${operation_id}-submission.json"

  aws ssm send-command \
    --region "${AWS_REGION}" \
    --instance-ids "$expected_instance_id" \
    --document-name "$document_name" \
    --document-version "$version" \
    --parameters "file://${normalized_parameters_path}" \
    --comment "$comment" \
    --timeout-seconds 300 \
    --max-concurrency 1 \
    --max-errors 0 \
    --output json >"$response_path"
  jq -e \
    --arg document_name "$document_name" \
    --arg document_version "$version" \
    --arg expected_instance_id "$expected_instance_id" '
      .Command.DocumentName == $document_name and
      .Command.DocumentVersion == $document_version and
      .Command.InstanceIds == [$expected_instance_id] and
      .Command.Targets == [] and
      (.Command.TargetCount == 0 or .Command.TargetCount == 1) and
      (.Command.CommandId | type) == "string" and
      (.Command.CommandId |
        test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))
    ' "$response_path" >/dev/null
  command_id="$(jq -er '.Command.CommandId' "$response_path")"
  list_path="${evidence_directory}/${operation_id}-list-command.json"
  for attempt in $(seq 1 30); do
    aws ssm list-commands \
      --region "${AWS_REGION}" \
      --command-id "$command_id" \
      --output json >"$list_path"
    if junca_fixed_ssm_validate_list_command_readback \
      "$list_path" "$command_id" "$document_name" "$version" \
      "$expected_instance_id"
    then
      target_count_accepted=true
      break
    fi
    test "$attempt" -lt 30
    sleep 1
  done
  test "$target_count_accepted" = true
  printf '%s\n' "$command_id"
}

junca_fixed_ssm_validate_invocation_readback() {
  local invocation_path="$1"
  local expected_instance_id="$2"
  local document_name="$3"
  local document_version="$4"
  local expected_command_id="$5"
  jq -e \
    --arg expected_instance_id "$expected_instance_id" \
    --arg document_name "$document_name" \
    --arg document_version "$document_version" \
    --arg expected_command_id "$expected_command_id" '
      .Status == "Success" and
      .CommandId == $expected_command_id and
      .InstanceId == $expected_instance_id and
      .DocumentName == $document_name and
      .DocumentVersion == $document_version and
      (.StandardOutputContent | type) == "string" and
      (.StandardErrorContent | type) == "string"
    ' "$invocation_path" >/dev/null
}
