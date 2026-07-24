"""Build reproducible source/compiler evidence for a non-deploying bridge bundle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_SOURCES = (
    "JuncaTestnetBridge.sol",
    "JuncaBridgeAssetAdapter.sol",
    "JuncaTestnetMintableERC20.sol",
    "JuncaTestnetMintableERC721.sol",
)


class DeploymentBundleError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentBundle:
    digest: str
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"bundle_digest": self.digest, **self.evidence}


def build_deployment_bundle(
    source_directory: str | Path,
    compiler_output_directory: str | Path,
) -> DeploymentBundle:
    source_root = Path(source_directory)
    output_root = Path(compiler_output_directory)
    sources: dict[str, str] = {}
    for name in CONTRACT_SOURCES:
        path = source_root / name
        if not path.is_file():
            raise DeploymentBundleError(f"missing contract source: {name}")
        sources[name] = _sha256(path)
    artifacts: dict[str, str] = {}
    for path in sorted(output_root.glob("*")):
        if path.is_file() and path.suffix in {".abi", ".bin"}:
            artifacts[path.name] = _sha256(path)
    for name in CONTRACT_SOURCES:
        contract = name.removesuffix(".sol")
        if not any(contract in artifact and artifact.endswith(".abi") for artifact in artifacts):
            raise DeploymentBundleError(f"missing ABI for {contract}")
        if not any(contract in artifact and artifact.endswith(".bin") for artifact in artifacts):
            raise DeploymentBundleError(f"missing bytecode for {contract}")
    evidence = {
        "schema_version": 1,
        "compiler": "solc-0.8.24",
        "optimizer": True,
        "sources": sources,
        "artifacts": artifacts,
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "deployment_performed": False,
        "assets_moved": False,
        "state": "BUILD_EVIDENCE_READY",
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return DeploymentBundle(hashlib.sha256(canonical).hexdigest(), evidence)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
