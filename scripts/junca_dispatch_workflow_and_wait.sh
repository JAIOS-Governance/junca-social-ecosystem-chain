#!/usr/bin/env bash
set -euo pipefail

workflow_name=""
workflow_path=""
expected_head=""
evidence_path=""
attempts=240
sleep_seconds=15
declare -a inputs=()

while (($#)); do
  case "$1" in
    --workflow-name) workflow_name="$2"; shift 2 ;;
    --workflow-path) workflow_path="$2"; shift 2 ;;
    --expected-head) expected_head="$2"; shift 2 ;;
    --evidence-path) evidence_path="$2"; shift 2 ;;
    --attempts) attempts="$2"; shift 2 ;;
    --sleep-seconds) sleep_seconds="$2"; shift 2 ;;
    --input) inputs+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
[[ "$workflow_name" != "" ]]
[[ "$workflow_path" =~ ^\.github/workflows/[a-zA-Z0-9._-]+\.ya?ml$ ]]
[[ "$expected_head" =~ ^[0-9a-f]{40}$ ]]
if [[ "$evidence_path" != "" ]]; then
  [[ "$evidence_path" =~ ^artifacts/[a-zA-Z0-9._/-]+\.json$ ]]
  [[ "$evidence_path" != *".."* ]]
  [[ "$evidence_path" != *"//"* ]]
fi
[[ "$attempts" =~ ^[1-9][0-9]*$ ]]
[[ "$sleep_seconds" =~ ^[1-9][0-9]*$ ]]

main_head="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq .object.sha)"
test "$main_head" = "$expected_head"

workflows="$(
  gh api --paginate \
    "repos/${GITHUB_REPOSITORY}/actions/workflows?per_page=100" |
    jq -s '[.[].workflows[]]'
)"
workflow="$(
  jq -ce \
    --arg name "$workflow_name" \
    --arg path "$workflow_path" '
      [.[] | select(
        .name == $name and .path == $path and .state == "active"
      )] |
      if length == 1 then .[0]
      else error("workflow identity mismatch")
      end
    ' <<<"$workflows"
)"
workflow_id="$(jq -er .id <<<"$workflow")"
dispatched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

declare -a dispatch_args=(
  --method POST
  "repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow_id}/dispatches"
  -f ref=main
)
for item in "${inputs[@]}"; do
  [[ "$item" == *=* ]]
  key="${item%%=*}"
  value="${item#*=}"
  [[ "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]
  dispatch_args+=(-f "inputs[${key}]=${value}")
done
gh api "${dispatch_args[@]}" >/dev/null

run_id=""
for attempt in $(seq 1 90); do
  runs="$(
    gh api \
      "repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow_id}/runs?branch=main&event=workflow_dispatch&per_page=50"
  )"
  matches="$(
    jq -ce \
      --arg since "$dispatched_at" \
      --arg head "$expected_head" '
        [.workflow_runs[] |
          select(.created_at >= $since and .head_sha == $head)
        ]
      ' <<<"$runs"
  )"
  count="$(jq length <<<"$matches")"
  test "$count" -le 1
  if [[ "$count" == 1 ]]; then
    run_id="$(jq -er '.[0].id' <<<"$matches")"
    break
  fi
  test "$attempt" -lt 90
  sleep 2
done
[[ "$run_id" =~ ^[1-9][0-9]*$ ]]

run=""
for attempt in $(seq 1 "$attempts"); do
  run="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}")"
  status="$(jq -er .status <<<"$run")"
  [[ "$status" == "completed" ]] && break
  test "$attempt" -lt "$attempts"
  sleep "$sleep_seconds"
done

identity_valid="$(
  jq -r \
    --arg repository "$GITHUB_REPOSITORY" \
    --arg head "$expected_head" \
    --arg name "$workflow_name" \
    --arg path "$workflow_path" '
      (
        .name == $name and
        .path == $path and
        .event == "workflow_dispatch" and
        .head_branch == "main" and
        .head_sha == $head and
        .repository.full_name == $repository and
        .head_repository.full_name == $repository
      )
    ' <<<"$run"
)"

if [[ "$evidence_path" != "" ]]; then
  evidence_directory="$(dirname "$evidence_path")"
  mkdir -p "$evidence_directory"
  evidence_tmp="${evidence_path}.tmp.$$"
  umask 077
  jq -n \
    --arg repository "$GITHUB_REPOSITORY" \
    --arg workflow_name "$workflow_name" \
    --arg workflow_path "$workflow_path" \
    --arg workflow_id "$workflow_id" \
    --arg expected_head "$expected_head" \
    --arg dispatched_at "$dispatched_at" \
    --arg run_id "$run_id" \
    --arg run_url "$(jq -er .html_url <<<"$run")" \
    --arg status "$(jq -er .status <<<"$run")" \
    --arg conclusion "$(jq -r '.conclusion // ""' <<<"$run")" \
    --argjson identity_valid "$identity_valid" '{
      schema_version: "junca-workflow-dispatch-evidence/v1",
      repository: $repository,
      workflow: {
        name: $workflow_name,
        path: $workflow_path,
        id: ($workflow_id | tonumber)
      },
      expected_head: $expected_head,
      dispatched_at: $dispatched_at,
      run: {
        id: ($run_id | tonumber),
        url: $run_url,
        status: $status,
        conclusion: $conclusion
      },
      identity_valid: $identity_valid,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false,
      mainnet_activation_authorized: false
    }' >"$evidence_tmp"
  chmod 0600 "$evidence_tmp"
  mv "$evidence_tmp" "$evidence_path"
fi

if ! jq -e \
  --arg repository "$GITHUB_REPOSITORY" \
  --arg head "$expected_head" \
  --arg name "$workflow_name" \
  --arg path "$workflow_path" '
    .status == "completed" and
    .conclusion == "success" and
    .name == $name and
    .path == $path and
    .event == "workflow_dispatch" and
    .head_branch == "main" and
    .head_sha == $head and
    .repository.full_name == $repository and
    .head_repository.full_name == $repository
  ' <<<"$run" >/dev/null; then
  printf 'workflow dispatch failed: run_id=%s url=%s status=%s conclusion=%s identity_valid=%s\n' \
    "$run_id" \
    "$(jq -er .html_url <<<"$run")" \
    "$(jq -er .status <<<"$run")" \
    "$(jq -r '.conclusion // ""' <<<"$run")" \
    "$identity_valid" >&2
  exit 1
fi

printf '%s\n' "$run_id"
