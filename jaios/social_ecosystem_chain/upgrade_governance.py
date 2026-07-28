"""Governed protocol-upgrade candidates for JUNCA Mainnet.

The state machine records proposal, independent review, rehearsal and scheduled
activation evidence. It never changes a live network and cannot bypass the CEO
Final Approval activation gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = "junca-mainnet-upgrade-governance/v1"
PROPOSAL_DOMAIN = b"JUNCA_MAINNET_UPGRADE_PROPOSAL_V1\x00"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_REQUIRED_REVIEWS = frozenset({"protocol", "security", "release", "recovery"})


class UpgradeGovernanceError(ValueError):
    """Raised when a governed upgrade transition is invalid."""


class UpgradeState(str, Enum):
    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    REHEARSED = "REHEARSED"
    SCHEDULED = "SCHEDULED"
    ACTIVATION_READY = "ACTIVATION_READY"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class UpgradeProposal:
    proposal_id: str
    source_sha: str
    artifact_digest: str
    genesis_or_config_digest: str
    protocol_version_from: str
    protocol_version_to: str
    activation_height: int
    migration_digest: str
    rollback_digest: str

    def __post_init__(self) -> None:
        for field in ("proposal_id", "protocol_version_from", "protocol_version_to"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise UpgradeGovernanceError(f"{field} is invalid")
        for field in (
            "source_sha",
            "artifact_digest",
            "genesis_or_config_digest",
            "migration_digest",
            "rollback_digest",
        ):
            _hash(getattr(self, field), field)
        if self.protocol_version_from == self.protocol_version_to:
            raise UpgradeGovernanceError("upgrade must change protocol version")
        if (
            isinstance(self.activation_height, bool)
            or not isinstance(self.activation_height, int)
            or self.activation_height <= 0
        ):
            raise UpgradeGovernanceError("activation_height must be positive")

    @property
    def proposal_hash(self) -> str:
        return "0x" + hashlib.sha256(
            PROPOSAL_DOMAIN
            + json.dumps(
                self.as_dict(), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "source_sha": self.source_sha.lower(),
            "artifact_digest": self.artifact_digest.lower(),
            "genesis_or_config_digest": self.genesis_or_config_digest.lower(),
            "protocol_version_from": self.protocol_version_from,
            "protocol_version_to": self.protocol_version_to,
            "activation_height": self.activation_height,
            "migration_digest": self.migration_digest.lower(),
            "rollback_digest": self.rollback_digest.lower(),
        }


@dataclass
class GovernedUpgrade:
    proposal: UpgradeProposal
    state: UpgradeState = UpgradeState.PROPOSED
    reviews: dict[str, str] = field(default_factory=dict)
    rehearsal_digest: str | None = None
    scheduled_height: int | None = None
    ceo_final_approval: bool = False
    rejection_reason: str | None = None

    def add_review(self, role: str, evidence_digest: str) -> None:
        self._terminal_guard()
        if role not in _REQUIRED_REVIEWS:
            raise UpgradeGovernanceError("review role is not recognized")
        if role in self.reviews:
            raise UpgradeGovernanceError("review role already submitted")
        self.reviews[role] = _hash(evidence_digest, "evidence_digest")
        if _REQUIRED_REVIEWS.issubset(self.reviews):
            self.state = UpgradeState.REVIEWED

    def record_rehearsal(self, evidence_digest: str) -> None:
        self._terminal_guard()
        if self.state is not UpgradeState.REVIEWED:
            raise UpgradeGovernanceError("all independent reviews are required")
        self.rehearsal_digest = _hash(evidence_digest, "rehearsal_digest")
        self.state = UpgradeState.REHEARSED

    def schedule(self, activation_height: int) -> None:
        self._terminal_guard()
        if self.state is not UpgradeState.REHEARSED:
            raise UpgradeGovernanceError("successful rehearsal is required")
        if activation_height != self.proposal.activation_height:
            raise UpgradeGovernanceError("activation height differs from proposal")
        self.scheduled_height = activation_height
        self.state = UpgradeState.SCHEDULED

    def record_ceo_final_approval(self, approved: bool) -> None:
        self._terminal_guard()
        if self.state is not UpgradeState.SCHEDULED:
            raise UpgradeGovernanceError("upgrade must be scheduled first")
        if approved is not True:
            raise UpgradeGovernanceError("CEO Final Approval must be explicit")
        self.ceo_final_approval = True
        self.state = UpgradeState.ACTIVATION_READY

    def reject(self, reason: str) -> None:
        self._terminal_guard()
        if not isinstance(reason, str) or not reason.strip():
            raise UpgradeGovernanceError("rejection reason is required")
        self.rejection_reason = reason.strip()
        self.state = UpgradeState.REJECTED

    @property
    def activation_authorized(self) -> bool:
        return self.state is UpgradeState.ACTIVATION_READY and self.ceo_final_approval

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "proposal_hash": self.proposal.proposal_hash,
            "state": self.state.value,
            "reviews": dict(sorted(self.reviews.items())),
            "rehearsal_digest": self.rehearsal_digest,
            "scheduled_height": self.scheduled_height,
            "ceo_final_approval": self.ceo_final_approval,
            "activation_authorized": self.activation_authorized,
            "rejection_reason": self.rejection_reason,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _terminal_guard(self) -> None:
        if self.state in {UpgradeState.ACTIVATION_READY, UpgradeState.REJECTED}:
            raise UpgradeGovernanceError("upgrade is in a terminal governance state")


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise UpgradeGovernanceError(f"{field} must be a 32-byte hash")
    return value.lower()
