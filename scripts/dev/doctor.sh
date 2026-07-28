#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

required=(python3 bash git jq tar sha256sum make)
optional=(docker gh aws terraform shellcheck)

failures=0
printf 'JUNCA Chain development environment\n'
printf 'Repository: %s\n\n' "$repo_root"

for command_name in "${required[@]}"; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '[PASS] required %-12s %s\n' "$command_name" "$(command -v "$command_name")"
  else
    printf '[FAIL] required %-12s missing\n' "$command_name"
    failures=$((failures + 1))
  fi
done

for command_name in "${optional[@]}"; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '[PASS] optional %-12s %s\n' "$command_name" "$(command -v "$command_name")"
  else
    printf '[INFO] optional %-12s not installed\n' "$command_name"
  fi
done

python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(f"Python 3.12+ required; found {sys.version.split()[0]}")
print(f"[PASS] Python version {sys.version.split()[0]}")
PY

if [[ -n "${AWS_ACCESS_KEY_ID:-}" || -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  printf '[WARN] static AWS credentials are present in the shell; prefer OIDC or short-lived credentials\n'
else
  printf '[PASS] no static AWS credential variables detected\n'
fi

for forbidden in .env .env.local validator.key private.key seed.txt; do
  if [[ -e "$forbidden" ]]; then
    printf '[FAIL] prohibited local secret file detected: %s\n' "$forbidden"
    failures=$((failures + 1))
  fi
done

if (( failures > 0 )); then
  printf '\nEnvironment doctor failed with %d critical finding(s).\n' "$failures"
  exit 1
fi

printf '\nEnvironment doctor: PASS\n'
