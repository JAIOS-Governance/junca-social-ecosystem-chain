#!/usr/bin/env python3
"""Static release-boundary verification for the self-contained bridge contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_SNIPPETS = (
    'GOVERNANCE_DISPLAY = "JAIOS Institutional Governance"',
    'TESTNET_NOTICE = "Public Testnet / No Monetary Value"',
    "bool public paused = true",
    "processedMessage[digest]",
    "processedSourceTransaction[message.sourceTransaction]",
    "processedSourceNonce[nonceKey]",
    "signatureThreshold",
    "SECP256K1N_HALF",
    "nonReentrant",
    "assetAdapter.releaseOrMint",
)

PROHIBITED_SNIPPETS = (
    "CEO-controlled",
    "CEO-sovereign",
    "sole personal authority",
    "tx.origin",
    "delegatecall",
    "selfdestruct",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        default="contracts/junca-social-ecosystem-chain/JuncaTestnetBridge.sol",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.contract)
    content = path.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED_SNIPPETS if item not in content]
    prohibited = [item for item in PROHIBITED_SNIPPETS if item in content]
    evidence = {
        "contract": str(path),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "required_controls": {"missing": missing, "passed": not missing},
        "prohibited_constructs": {"found": prohibited, "passed": not prohibited},
        "deployment_performed": False,
        "assets_moved": False,
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "state": "STATIC_VERIFIED" if not missing and not prohibited else "REJECTED",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["state"] == "STATIC_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
