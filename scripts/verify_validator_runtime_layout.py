#!/usr/bin/env python3
"""Fail-closed completeness gate for the immutable validator runtime."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


REQUIRED_FILES = {
    "usr/local/bin/junca-chain-node": 0o111,
    "usr/local/bin/junca-public-gateway": 0o111,
    "etc/systemd/system/junca-validator.service": 0,
    "etc/systemd/system/junca-public-rpc.service": 0,
    "etc/systemd/system/junca-public-explorer.service": 0,
}

ENTRYPOINTS = (
    "usr/local/bin/junca-chain-node",
    "usr/local/bin/junca-public-gateway",
)
RUNTIME_IMPORT_BINDING = "sys.path.insert(0, '/usr/local/lib/junca')"
PYTHON_PACKAGE_ROOT = "usr/local/lib/junca/jaios/social_ecosystem_chain"

COMMON_SERVICE_CONTRACTS = (
    "User=junca",
    "Group=junca",
    "Restart=on-failure",
    "NoNewPrivileges=true",
    "WantedBy=multi-user.target",
)

SERVICE_CONTRACTS = {
    "etc/systemd/system/junca-validator.service": COMMON_SERVICE_CONTRACTS
    + (
        "EnvironmentFile=/etc/junca/runtime.env",
        "--http.addr 127.0.0.1",
        "--http.port 8545",
        "ReadWritePaths=/var/lib/junca /var/log/junca",
    ),
    "etc/systemd/system/junca-public-rpc.service": COMMON_SERVICE_CONTRACTS
    + (
        "Requires=junca-validator.service",
        "--http.addr 0.0.0.0",
        "--http.port 8546",
    ),
    "etc/systemd/system/junca-public-explorer.service": COMMON_SERVICE_CONTRACTS
    + (
        "Requires=junca-validator.service",
        "--http.addr 0.0.0.0",
        "--http.port 3000",
    ),
}


def _compile_python(path: Path, relative: str) -> None:
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, relative, "exec")
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ValueError(f"runtime Python source is invalid: {relative}") from exc


def verify(root: Path) -> None:
    if not root.is_dir():
        raise ValueError(f"runtime root is not a directory: {root}")

    for relative, executable_mask in REQUIRED_FILES.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required regular file missing: {relative}")
        if executable_mask and not (path.stat().st_mode & executable_mask):
            raise ValueError(f"required executable bit missing: {relative}")

    for relative in ENTRYPOINTS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if not text.startswith("#!/usr/bin/env python3\n"):
            raise ValueError(f"runtime entrypoint shebang is invalid: {relative}")
        if text.count(RUNTIME_IMPORT_BINDING) != 1:
            raise ValueError(
                f"runtime entrypoint import binding is missing or duplicated: {relative}"
            )
        _compile_python(path, relative)

    package_root = root / PYTHON_PACKAGE_ROOT
    modules = sorted(package_root.glob("*.py"))
    if not modules:
        raise ValueError("runtime Python package is missing")
    for module in modules:
        _compile_python(module, str(module.relative_to(root)))

    required_liveness = package_root / "validator_liveness.py"
    if not required_liveness.is_file() or required_liveness.is_symlink():
        raise ValueError("validator liveness module is missing from runtime")

    for relative, required_terms in SERVICE_CONTRACTS.items():
        text = (root / relative).read_text(encoding="utf-8")
        for term in required_terms:
            if term not in text:
                raise ValueError(f"{relative} is missing contract: {term}")

    sums_path = root / "SHA256SUMS"
    if not sums_path.is_file() or sums_path.is_symlink():
        raise ValueError("SHA256SUMS is missing")
    entries: set[str] = set()
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*")
        if relative in entries:
            raise ValueError(f"duplicate runtime digest entry: {relative}")
        entries.add(relative)
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"runtime digest path is invalid: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"runtime digest mismatch: {relative}")

    required_digest_paths = set(REQUIRED_FILES) | {
        f"{PYTHON_PACKAGE_ROOT}/validator_liveness.py"
    }
    if not required_digest_paths <= entries:
        missing = sorted(required_digest_paths - entries)
        raise ValueError(f"required runtime digest entries missing: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    verify(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
