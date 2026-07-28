#!/usr/bin/env bash
set -euo pipefail

workflow_name=""
workflow_path=""
expected_head=""
attempts=240
sleep_seconds=15
declare -a inputs=()

while (($#)); do
  case "$1" in
    --workflow-name) workflow_name="$2"; shift 2 ;;
    --workflow-path) workflow_path="$2"; shift 2 ;;
    --expected-head) expected_head="$2"; shift 2 ;;
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

jq -e \
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
  ' <<<"$run" >/dev/null

printf '%s\n' "$run_id"
