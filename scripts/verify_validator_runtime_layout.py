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

SERVICE_CONTRACTS = {
    "etc/systemd/system/junca-validator.service": (
        "User=junca",
        "Group=junca",
        "EnvironmentFile=/etc/junca/runtime.env",
        "--http.addr 127.0.0.1",
        "--http.port 8545",
        "ReadWritePaths=/var/lib/junca /var/log/junca",
    ),
    "etc/systemd/system/junca-public-rpc.service": (
        "User=junca",
        "Group=junca",
        "Requires=junca-validator.service",
        "--http.port 8546",
    ),
    "etc/systemd/system/junca-public-explorer.service": (
        "User=junca",
        "Group=junca",
        "Requires=junca-validator.service",
        "--http.port 3000",
    ),
}


def verify(root: Path) -> None:
    if not root.is_dir():
        raise ValueError(f"runtime root is not a directory: {root}")

    for relative, executable_mask in REQUIRED_FILES.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required regular file missing: {relative}")
        if executable_mask and not (path.stat().st_mode & executable_mask):
            raise ValueError(f"required executable bit missing: {relative}")

    for relative, required_terms in SERVICE_CONTRACTS.items():
        text = (root / relative).read_text(encoding="utf-8")
        for term in required_terms:
            if term not in text:
                raise ValueError(f"{relative} is missing contract: {term}")

    sums_path = root / "SHA256SUMS"
    if not sums_path.is_file() or sums_path.is_symlink():
        raise ValueError("SHA256SUMS is missing")
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*")
        path = root / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"runtime digest mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    verify(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
