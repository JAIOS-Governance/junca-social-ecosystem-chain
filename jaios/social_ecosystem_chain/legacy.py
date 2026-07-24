"""Deterministic audit fingerprints for the legacy JUNCA Chain source."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


class LegacyFingerprintError(RuntimeError):
    """Raised when legacy source evidence is incomplete or unsafe."""


LEGACY_FILES = (
    "Dockerfile",
    "Makefile",
    "genesis/mainnet.json",
    "genesis/testnet.json",
    "go.mod",
    "go.sum",
    "params/bootnodes.go",
    "params/config.go",
)

EXPECTED_CHAIN_IDS = {
    "mainnet": 668,
    "testnet": 669,
}


@dataclass(frozen=True)
class LegacyGenesisFingerprint:
    network: str
    path: str
    sha256_raw: str
    sha256_canonical_json: str
    chain_id: int
    alloc_accounts: int
    extra_data_bytes: int
    timestamp: int
    gas_limit: int
    difficulty: int
    posv_period_seconds: int
    posv_epoch_blocks: int
    min_staked: str
    reward: str
    total_reward: str
    foundation: str
    juncaswap_admin: str

    def as_evidence(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "path": self.path,
            "sha256_raw": self.sha256_raw,
            "sha256_canonical_json": self.sha256_canonical_json,
            "chain_id": self.chain_id,
            "alloc_accounts": self.alloc_accounts,
            "extra_data_bytes": self.extra_data_bytes,
            "timestamp": self.timestamp,
            "gas_limit": self.gas_limit,
            "difficulty": self.difficulty,
            "consensus": {
                "engine": "posv",
                "period_seconds": self.posv_period_seconds,
                "epoch_blocks": self.posv_epoch_blocks,
                "min_staked": self.min_staked,
                "reward": self.reward,
                "total_reward": self.total_reward,
                "foundation": self.foundation,
                "juncaswap_admin": self.juncaswap_admin,
            },
        }


@dataclass(frozen=True)
class LegacySourceFingerprint:
    source_repository: str
    source_commit: str
    source_tag: str
    files: tuple[tuple[str, str], ...]
    genesis: tuple[LegacyGenesisFingerprint, ...]

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-legacy-source-fingerprint/v1",
            "classification": "audit-reference-only",
            "source": {
                "repository": self.source_repository,
                "commit": self.source_commit,
                "tag": self.source_tag,
            },
            "files": [
                {"path": path, "sha256": digest}
                for path, digest in self.files
            ],
            "genesis": [item.as_evidence() for item in self.genesis],
            "custody": {
                "legacy_keys_accepted": False,
                "legacy_credentials_accepted": False,
                "secrets_collected": False,
            },
            "status": "verified-source-fingerprint",
        }


def fingerprint_legacy_source(
    source_root: str | Path,
    *,
    source_repository: str,
    source_commit: str,
    source_tag: str,
) -> LegacySourceFingerprint:
    """Fingerprint a pinned legacy checkout without reading secret material."""

    root = Path(source_root).resolve()
    if not root.is_dir():
        raise LegacyFingerprintError(f"source root is not a directory: {root}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise LegacyFingerprintError("source_commit must be a lowercase 40-character SHA")
    repository = _text(source_repository, "source_repository")
    tag = _text(source_tag, "source_tag")

    files: list[tuple[str, str]] = []
    for relative in LEGACY_FILES:
        path = _safe_source_file(root, relative)
        files.append((relative, sha256(path.read_bytes()).hexdigest()))

    genesis = tuple(
        _fingerprint_genesis(
            root,
            network,
            f"genesis/{network}.json",
            expected_chain_id,
        )
        for network, expected_chain_id in EXPECTED_CHAIN_IDS.items()
    )
    return LegacySourceFingerprint(
        source_repository=repository,
        source_commit=source_commit,
        source_tag=tag,
        files=tuple(files),
        genesis=genesis,
    )


def _fingerprint_genesis(
    root: Path,
    network: str,
    relative: str,
    expected_chain_id: int,
) -> LegacyGenesisFingerprint:
    path = _safe_source_file(root, relative)
    raw_bytes = path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise LegacyFingerprintError(f"invalid JSON: {relative}") from exc
    if not isinstance(raw, Mapping):
        raise LegacyFingerprintError(f"{relative} must be a JSON object")
    config = _mapping(raw.get("config"), f"{relative}.config")
    chain_id = _integer(config.get("chainId"), f"{relative}.config.chainId")
    if chain_id != expected_chain_id:
        raise LegacyFingerprintError(
            f"{network} chain ID must be {expected_chain_id}, received {chain_id}"
        )
    posv = _mapping(config.get("posv"), f"{relative}.config.posv")
    alloc = _mapping(raw.get("alloc"), f"{relative}.alloc")
    extra_data = _hex_bytes(raw.get("extraData"), f"{relative}.extraData")
    canonical = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return LegacyGenesisFingerprint(
        network=network,
        path=relative,
        sha256_raw=sha256(raw_bytes).hexdigest(),
        sha256_canonical_json=sha256(canonical).hexdigest(),
        chain_id=chain_id,
        alloc_accounts=len(alloc),
        extra_data_bytes=(len(extra_data) - 2) // 2,
        timestamp=_hex_integer(raw.get("timestamp"), f"{relative}.timestamp"),
        gas_limit=_hex_integer(raw.get("gasLimit"), f"{relative}.gasLimit"),
        difficulty=_hex_integer(raw.get("difficulty"), f"{relative}.difficulty"),
        posv_period_seconds=_integer(posv.get("period"), f"{relative}.posv.period"),
        posv_epoch_blocks=_integer(posv.get("epoch"), f"{relative}.posv.epoch"),
        min_staked=_hex_quantity_text(
            posv.get("minStaked"),
            f"{relative}.posv.minStaked",
        ),
        reward=_hex_quantity_text(posv.get("reward"), f"{relative}.posv.reward"),
        total_reward=_hex_quantity_text(
            posv.get("totalReward"),
            f"{relative}.posv.totalReward",
        ),
        foundation=_address(posv.get("foundation"), f"{relative}.posv.foundation"),
        juncaswap_admin=_address(
            posv.get("juncaswapAdmin"),
            f"{relative}.posv.juncaswapAdmin",
        ),
    )


def _safe_source_file(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise LegacyFingerprintError(f"unsafe source path: {relative}")
    candidate = root / relative
    if candidate.is_symlink():
        raise LegacyFingerprintError(f"source file must not be a symlink: {relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise LegacyFingerprintError(f"required source file is missing: {relative}")
    return resolved


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegacyFingerprintError(f"{field} must be an object")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LegacyFingerprintError(f"{field} must be a non-negative integer")
    return value


def _hex_bytes(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"0x[0-9a-fA-F]+", value)
        or len(value[2:]) % 2
    ):
        raise LegacyFingerprintError(f"{field} must be an even-length hex value")
    return value.lower()


def _hex_quantity_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise LegacyFingerprintError(f"{field} must be a hex quantity")
    return value.lower()


def _hex_integer(value: Any, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise LegacyFingerprintError(f"{field} must be a hex integer")
    return int(value, 16)


def _address(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise LegacyFingerprintError(f"{field} must be a 20-byte address")
    return value.lower()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise LegacyFingerprintError(f"{field} must contain 1-300 characters")
    return value.strip()
