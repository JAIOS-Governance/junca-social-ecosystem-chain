"""Fail-closed Mainnet Release Candidate acceptance gate.

The gate binds immutable evidence and requires every acceptance domain plus
explicit CEO Final Approval. It records readiness only and never activates a
network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "junca-mainnet-release-gate/v1"
RELEASE_DOMAIN = b"JUNCA_MAINNET_RELEASE_CANDIDATE_V1\x00"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
REQUIRED_GATES = (
    "protocol",
    "consensus",
    "execution-state",
    "transaction-mempool",
    "validator-network",
    "p2p-rpc",
    "security-cryptography",
    "governance-upgrade",
    "performance-scalability",
    "infrastructure",
    "backup-recovery",
    "explorer-indexer",
    "sdk-application",
    "interoperability",
    "production-acceptance",
)


class MainnetReleaseGateError(ValueError):
    """Raised when release evidence or a gate transition is invalid."""


class GateStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ReleaseArtifactBinding:
    source_sha: str
    artifact_digest: str
    genesis_digest: str
    configuration_digest: str
    sbom_digest: str
    infrastructure_plan_digest: str

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _hash(getattr(self, field), field)

    def as_dict(self) -> dict[str, str]:
        return {
            field: getattr(self, field).lower()
            for field in self.__dataclass_fields__
        }

    @property
    def binding_hash(self) -> str:
        return "0x" + hashlib.sha256(
            RELEASE_DOMAIN
            + json.dumps(
                self.as_dict(), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()


@dataclass
class MainnetReleaseCandidateGate:
    binding: ReleaseArtifactBinding
    gates: dict[str, GateStatus] = field(
        default_factory=lambda: {
            name: GateStatus.PENDING for name in REQUIRED_GATES
        }
    )
    evidence_digests: dict[str, str] = field(default_factory=dict)
    ceo_final_approval: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ReleaseArtifactBinding):
            raise MainnetReleaseGateError("release binding is required")
        if set(self.gates) != set(REQUIRED_GATES):
            raise MainnetReleaseGateError("release gate set is incomplete")
        for name, status in self.gates.items():
            if not isinstance(status, GateStatus):
                raise MainnetReleaseGateError(f"gate {name} status is invalid")

    def record(self, gate: str, status: GateStatus, evidence_digest: str) -> None:
        if gate not in self.gates:
            raise MainnetReleaseGateError("unknown release gate")
        if not isinstance(status, GateStatus) or status is GateStatus.PENDING:
            raise MainnetReleaseGateError("gate result must be PASS or FAIL")
        digest = _hash(evidence_digest, "evidence_digest")
        existing = self.gates[gate]
        if existing is GateStatus.PASS and status is GateStatus.FAIL:
            raise MainnetReleaseGateError(
                "a passed gate cannot be downgraded without a new candidate binding"
            )
        if existing is GateStatus.FAIL and status is GateStatus.PASS:
            raise MainnetReleaseGateError(
                "a failed gate requires a new candidate or explicit supersession"
            )
        self.gates[gate] = status
        self.evidence_digests[gate] = digest

    def record_ceo_final_approval(self, approved: bool) -> None:
        if approved is not True:
            raise MainnetReleaseGateError("CEO Final Approval must be explicit")
        if any(status is not GateStatus.PASS for status in self.gates.values()):
            raise MainnetReleaseGateError(
                "all Mainnet acceptance gates must pass before CEO approval"
            )
        if set(self.evidence_digests) != set(REQUIRED_GATES):
            raise MainnetReleaseGateError("every passed gate requires evidence")
        self.ceo_final_approval = True

    @property
    def release_candidate_ready(self) -> bool:
        return (
            self.ceo_final_approval
            and all(status is GateStatus.PASS for status in self.gates.values())
            and set(self.evidence_digests) == set(REQUIRED_GATES)
        )

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(
            name for name in REQUIRED_GATES if self.gates[name] is GateStatus.FAIL
        )

    @property
    def pending_gates(self) -> tuple[str, ...]:
        return tuple(
            name for name in REQUIRED_GATES if self.gates[name] is GateStatus.PENDING
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "binding": self.binding.as_dict(),
            "binding_hash": self.binding.binding_hash,
            "gates": {
                name: self.gates[name].value for name in REQUIRED_GATES
            },
            "evidence_digests": dict(sorted(self.evidence_digests.items())),
            "failed_gates": list(self.failed_gates),
            "pending_gates": list(self.pending_gates),
            "ceo_final_approval": self.ceo_final_approval,
            "release_candidate_ready": self.release_candidate_ready,
            "activation_authorized": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def gate_from_mapping(
    binding: ReleaseArtifactBinding,
    values: Mapping[str, str],
) -> MainnetReleaseCandidateGate:
    if not isinstance(values, Mapping) or set(values) != set(REQUIRED_GATES):
        raise MainnetReleaseGateError("gate mapping is incomplete")
    try:
        statuses = {name: GateStatus(values[name]) for name in REQUIRED_GATES}
    except (TypeError, ValueError) as exc:
        raise MainnetReleaseGateError("gate mapping contains invalid status") from exc
    return MainnetReleaseCandidateGate(binding=binding, gates=statuses)


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise MainnetReleaseGateError(f"{field} must be a 32-byte hash")
    return value.lower()
