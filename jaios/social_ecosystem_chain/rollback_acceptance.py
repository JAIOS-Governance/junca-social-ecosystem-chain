"""Non-production rollback rehearsal acceptance for the public testnet."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


class RollbackAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class RollbackAcceptance:
    state: str
    gates: Mapping[str, bool]
    failed_gates: tuple[str, ...]
    evidence_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-public-testnet-rollback/v1",
            "state": self.state,
            "gates": dict(self.gates),
            "failed_gates": list(self.failed_gates),
            "evidence_digest": self.evidence_digest,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def evaluate_rollback_acceptance(evidence: Mapping[str, Any]) -> RollbackAcceptance:
    for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
        if evidence.get(boundary) is not False:
            raise RollbackAcceptanceError(f"{boundary} must be false")
    gates = {
        "public_endpoint_withdrawal": evidence.get("public_endpoint_withdrawal") is True,
        "bridge_pause_maintained": evidence.get("bridge_pause_maintained") is True,
        "logs_and_audit_preserved": evidence.get("logs_and_audit_preserved") is True,
        "last_finalized_checkpoint_saved": evidence.get("last_finalized_checkpoint_saved")
        is True,
        "binary_and_genesis_restored": evidence.get("binary_and_genesis_restored") is True,
        "validator_quorum_reverified": evidence.get("validator_quorum_reverified") is True,
        "readonly_endpoint_restored": evidence.get("readonly_endpoint_restored") is True,
        "explorer_parity_reverified": evidence.get("explorer_parity_reverified") is True,
        "non_production_rehearsal": evidence.get("non_production_rehearsal") is True,
    }
    failed = tuple(name for name, passed in gates.items() if not passed)
    digest = hashlib.sha256(
        json.dumps(
            {"evidence": evidence, "gates": gates},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return RollbackAcceptance(
        state="ACCEPTED" if not failed else "BLOCKED",
        gates=gates,
        failed_gates=failed,
        evidence_digest=digest,
    )

