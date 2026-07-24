#!/usr/bin/env python3
"""Generate deterministic, non-asset-moving bridge protocol evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jaios.social_ecosystem_chain.bridge_protocol import (
    BridgeProtocol,
    RelayerAttestation,
    bridge_message_from_mapping,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-state", default="EXECUTED")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    protocol = BridgeProtocol(**scenario["policy"])
    message = bridge_message_from_mapping(scenario["message"])
    record = protocol.observe(message)
    protocol.apply_confirmations(message.digest, scenario["confirmations"])
    for item in scenario["attestations"]:
        protocol.attest(RelayerAttestation(**item, message_digest=message.digest))
    if scenario.get("unpause_for_simulation") is True:
        protocol.set_paused(False)
    protocol.prepare_execution(message.digest)
    protocol.mark_executed(message.digest, scenario["execution_transaction"])
    evidence = {
        "simulation_only": True,
        "assets_moved": False,
        "governance": message.governance,
        "notice": message.notice,
        "record": record.evidence(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if record.state.value == args.expect_state else 2


if __name__ == "__main__":
    raise SystemExit(main())
