#!/usr/bin/env bash
set -euo pipefail
umask 022

# The immutable image contains both the private validator and fail-closed public gateway.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-${repo_root}/dist/validator-runtime}"

install -d -m 0755 "${output_dir}/usr/local/bin"
install -d -m 0755 "${output_dir}/usr/local/lib/junca/jaios"
install -d -m 0755 "${output_dir}/etc/systemd/system"
install -d -m 0755 "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain"
install -d -m 0755 "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain/assets"
find "${repo_root}/jaios/social_ecosystem_chain" -maxdepth 1 -type f -name '*.py' \
  -exec install -m 0644 {} \
  "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain/" \;
find "${repo_root}/jaios/social_ecosystem_chain/assets" -maxdepth 1 -type f -name '*.png' \
  -exec install -m 0644 {} \
  "${output_dir}/usr/local/lib/junca/jaios/social_ecosystem_chain/assets/" \;
install -m 0755 "${repo_root}/scripts/junca-chain-node" \
  "${output_dir}/usr/local/bin/junca-chain-node"
install -m 0755 "${repo_root}/scripts/junca-public-gateway" \
  "${output_dir}/usr/local/bin/junca-public-gateway"
install -m 0644 "${repo_root}/packaging/systemd/junca-validator.service" \
  "${output_dir}/etc/systemd/system/junca-validator.service"
install -m 0644 "${repo_root}/packaging/systemd/junca-public-rpc.service" \
  "${output_dir}/etc/systemd/system/junca-public-rpc.service"
install -m 0644 "${repo_root}/packaging/systemd/junca-public-explorer.service" \
  "${output_dir}/etc/systemd/system/junca-public-explorer.service"

# Installed entrypoints execute from /usr/local/bin while the immutable Python
# package lives under /usr/local/lib/junca. Inject one exact import root after
# the shebang independent of the entrypoint's internal import style.
python3 - \
  "${output_dir}/usr/local/bin/junca-chain-node" \
  "${output_dir}/usr/local/bin/junca-public-gateway" <<'PY'
from pathlib import Path
import sys

binding = "sys.path.insert(0, '/usr/local/lib/junca')"
for name in sys.argv[1:]:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("#!"):
        raise SystemExit(f"runtime entrypoint has no shebang: {path}")
    if binding not in text:
        lines[1:1] = ["import sys\n", binding + "\n"]
    rendered = "".join(lines)
    if rendered.count(binding) != 1:
        raise SystemExit(f"runtime entrypoint import binding is not unique: {path}")
    path.write_text(rendered, encoding="utf-8")
PY

(cd "${output_dir}" && find usr etc -type f -print0 | sort -z | xargs -0 sha256sum \
  >SHA256SUMS)
python3 "${repo_root}/scripts/verify_validator_runtime_layout.py" "${output_dir}"

archive="${output_dir}.tar.gz"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "${output_dir}" -czf "${archive}" .
sha256sum "${archive}" >"${archive}.sha256"
