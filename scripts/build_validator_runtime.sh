#!/usr/bin/env bash
set -euo pipefail
umask 022

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-${repo_root}/dist/validator-runtime}"

install -d -m 0755 "${output_dir}/usr/local/bin"
install -d -m 0755 "${output_dir}/usr/local/lib/junca/jaios"
install -d -m 0755 "${output_dir}/etc/systemd/system"
install -d -m 0755 "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain"
find "${repo_root}/jaios/social_ecosystem_chain" -maxdepth 1 -type f -name '*.py' \
  -exec install -m 0644 {} \
  "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain/" \;
install -m 0755 "${repo_root}/scripts/junca-chain-node" \
  "${output_dir}/usr/local/bin/junca-chain-node"
install -m 0644 "${repo_root}/packaging/systemd/junca-validator.service" \
  "${output_dir}/etc/systemd/system/junca-validator.service"

python3 - "${output_dir}/usr/local/bin/junca-chain-node" <<'PY'
from pathlib import Path
path = Path(__import__("sys").argv[1])
text = path.read_text()
path.write_text(text.replace(
    "from jaios.social_ecosystem_chain.validator_node import main",
    "import sys\nsys.path.insert(0, '/usr/local/lib/junca')\n"
    "from jaios.social_ecosystem_chain.validator_node import main",
))
PY

(cd "${output_dir}" && find usr etc -type f -print0 | sort -z | xargs -0 sha256sum \
  >SHA256SUMS)

archive="${output_dir}.tar.gz"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "${output_dir}" -czf "${archive}" .
sha256sum "${archive}" >"${archive}.sha256"
