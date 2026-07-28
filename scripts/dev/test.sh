#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

printf 'Running complete Python unit suite...\n'
python3 -m unittest discover -s tests -p 'test_*.py' -v

printf '\nBuilding deterministic validator runtime...\n'
bash scripts/build_validator_runtime.sh "$work_dir/validator-runtime"
python3 scripts/verify_validator_runtime_layout.py "$work_dir/validator-runtime"

printf '\nGenerating canonical zero-allocation genesis...\n'
python3 scripts/generate_junca_public_testnet_genesis.py \
  --validator validator-01 \
  --validator validator-02 \
  --validator validator-03 \
  --output "$work_dir/genesis.json"

python3 - "$work_dir/genesis.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
document = json.loads(path.read_text())
encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
if not document:
    raise SystemExit("genesis document is empty")
print(f"Genesis bytes: {len(encoded)}")
PY

sha256sum "$work_dir/validator-runtime.tar.gz" "$work_dir/genesis.json"
printf '\nDeterministic protocol development test: PASS\n'
