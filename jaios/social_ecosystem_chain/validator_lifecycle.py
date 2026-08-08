"""Governed validator-set candidate and transition contracts for Mainnet.

This module models admission, removal, rotation and voting-power changes as
reviewable candidates.  It does not mutate a live validator schedule or activate
Mainnet.  Activation belongs to a separately reviewed governance and runtime
integration path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable


SCHEMA_VERSION = "junca-mainnet-validator-lifecycle/v1"
SET_DOMAIN = b"JUNCA_MAINNET_VALIDATOR_SET_V1\x00"
TRANSITION_DOMAIN = b"JUNCA_MAINNET_VALIDATOR_TRANSITION_V1\x00"
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_REQUIRED_APPROVALS = frozenset(
    {"protocol-maintainer", "security-reviewer", "release-approver"}
)


class ValidatorLifecycleError(ValueError):
    """Raised when a validator candidate violates Mainnet governance policy."""


@dataclass(frozen=True)
class MainnetValidatorPolicy:
    minimum_validators: int = 9
    minimum_regions: int = 3
    minimum_failure_domains: int = 5
    minimum_quorum_percent: int = 75
    maximum_single_validator_power_percent: int = 20

    def __post_init__(self) -> None:
        fields = (
            self.minimum_validators,
            self.minimum_regions,
            self.minimum_failure_domains,
            self.minimum_quorum_percent,
            self.maximum_single_validator_power_percent,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in fields):
            raise ValidatorLifecycleError("validator policy values must be positive integers")
        if self.minimum_validators < 4:
            raise ValidatorLifecycleError("minimum_validators is below BFT production policy")
        if not 67 <= self.minimum_quorum_percent < 100:
            raise ValidatorLifecycleError("minimum_quorum_percent is invalid")
        if not 1 <= self.maximum_single_validator_power_percent < 34:
            raise ValidatorLifecycleError(
                "maximum_single_validator_power_percent is invalid"
            )


@dataclass(frozen=True)
class ValidatorIdentity:
    validator_id: str
    voting_power: int
    signer_resource_digest: str
    region: str
    failure_domain: str

    def __post_init__(self) -> None:
        for field in ("validator_id", "region", "failure_domain"):
            if not _IDENTIFIER.fullmatch(getattr(self, field)):
                raise ValidatorLifecycleError(f"{field} is invalid")
        if isinstance(self.voting_power, bool) or not isinstance(self.voting_power, int) or self.voting_power <= 0:
            raise ValidatorLifecycleError("voting_power must be a positive integer")
        _hash(self.signer_resource_digest, "signer_resource_digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "validator_id": self.validator_id,
            "voting_power": self.voting_power,
            "signer_resource_digest": self.signer_resource_digest.lower(),
            "region": self.region,
            "failure_domain": self.failure_domain,
        }


@dataclass(frozen=True)
class ValidatorSetCandidate:
    epoch: int
    activation_height: int
    validators: tuple[ValidatorIdentity, ...]
    policy: MainnetValidatorPolicy = MainnetValidatorPolicy()

    def __post_init__(self) -> None:
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch < 0:
            raise ValidatorLifecycleError("epoch must be a non-negative integer")
        if (
            isinstance(self.activation_height, bool)
            or not isinstance(self.activation_height, int)
            or self.activation_height < 0
        ):
            raise ValidatorLifecycleError(
                "activation_height must be a non-negative integer"
            )
        if not isinstance(self.validators, tuple):
            raise ValidatorLifecycleError("validators must be a tuple")
        if len(self.validators) < self.policy.minimum_validators:
            raise ValidatorLifecycleError("validator count is below Mainnet policy")
        if any(not isinstance(item, ValidatorIdentity) for item in self.validators):
            raise ValidatorLifecycleError("validator identity type is invalid")

        identities = tuple(item.validator_id for item in self.validators)
        if identities != tuple(sorted(identities)):
            raise ValidatorLifecycleError("validators must be canonically ordered")
        if len(set(identities)) != len(identities):
            raise ValidatorLifecycleError("validator identities must be distinct")
        signer_digests = [item.signer_resource_digest.lower() for item in self.validators]
        if len(set(signer_digests)) != len(signer_digests):
            raise ValidatorLifecycleError("validator signer resources must be distinct")
        if len({item.region for item in self.validators}) < self.policy.minimum_regions:
            raise ValidatorLifecycleError("validator regions are below Mainnet policy")
        if (
            len({item.failure_domain for item in self.validators})
            < self.policy.minimum_failure_domains
        ):
            raise ValidatorLifecycleError(
                "validator failure domains are below Mainnet policy"
            )

        total_power = self.total_power
        largest = max(item.voting_power for item in self.validators)
        if largest * 100 > total_power * self.policy.maximum_single_validator_power_percent:
            raise ValidatorLifecycleError("single validator voting power exceeds policy")

    @property
    def total_power(self) -> int:
        return sum(item.voting_power for item in self.validators)

    @property
    def quorum_power(self) -> int:
        percent = self.policy.minimum_quorum_percent
        return (self.total_power * percent) // 100 + 1

    @property
    def set_hash(self) -> str:
        return _digest(
            SET_DOMAIN
            + json.dumps(
                self.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "epoch": self.epoch,
            "activation_height": self.activation_height,
            "validators": [item.as_dict() for item in self.validators],
            "total_power": self.total_power,
            "quorum_power": self.quorum_power,
        }

    def as_evidence(self) -> dict[str, Any]:
        return {
            **self.as_dict(),
            "validator_set_hash": self.set_hash,
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


@dataclass(frozen=True)
class ValidatorSetTransition:
    current_set_hash: str
    next_set: ValidatorSetCandidate
    approvals: tuple[str, ...]
    reason_digest: str

    def __post_init__(self) -> None:
        _hash(self.current_set_hash, "current_set_hash")
        _hash(self.reason_digest, "reason_digest")
        if not isinstance(self.next_set, ValidatorSetCandidate):
            raise ValidatorLifecycleError("next_set is required")
        if not isinstance(self.approvals, tuple):
            raise ValidatorLifecycleError("approvals must be a tuple")
        if tuple(sorted(set(self.approvals))) != self.approvals:
            raise ValidatorLifecycleError("approvals must be unique and sorted")
        if not _REQUIRED_APPROVALS.issubset(self.approvals):
            raise ValidatorLifecycleError("required independent approvals are missing")

    @property
    def transition_hash(self) -> str:
        body = {
            "schema_version": SCHEMA_VERSION,
            "current_set_hash": self.current_set_hash.lower(),
            "next_set_hash": self.next_set.set_hash,
            "next_epoch": self.next_set.epoch,
            "activation_height": self.next_set.activation_height,
            "approvals": list(self.approvals),
            "reason_digest": self.reason_digest.lower(),
        }
        return _digest(
            TRANSITION_DOMAIN
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "current_set_hash": self.current_set_hash.lower(),
            "next_set_hash": self.next_set.set_hash,
            "transition_hash": self.transition_hash,
            "approvals": list(self.approvals),
            "activation_status": "GOVERNED_CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def build_validator_set_candidate(
    *,
    epoch: int,
    activation_height: int,
    validators: Iterable[ValidatorIdentity],
    policy: MainnetValidatorPolicy | None = None,
) -> ValidatorSetCandidate:
    return ValidatorSetCandidate(
        epoch=epoch,
        activation_height=activation_height,
        validators=tuple(sorted(validators, key=lambda item: item.validator_id)),
        policy=MainnetValidatorPolicy() if policy is None else policy,
    )


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise ValidatorLifecycleError(f"{field} must be a 32-byte hash")
    return value.lower()


def _digest(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()
