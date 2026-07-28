"""Deterministic leader and timeout policy for Mainnet consensus candidates.

The policy is a consensus primitive only.  It does not start a network, replace
the current Public Testnet loop or activate Mainnet.  Runtime integration and
Byzantine acceptance require separate protected changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable


SCHEMA_VERSION = "junca-mainnet-consensus-rounds/v1"
LEADER_DOMAIN = b"JUNCA_MAINNET_LEADER_SELECTION_V1\x00"
ROUND_DOMAIN = b"JUNCA_MAINNET_ROUND_STATE_V1\x00"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class ConsensusRoundError(ValueError):
    """Raised when leader or round policy violates a consensus invariant."""


@dataclass(frozen=True)
class ConsensusValidator:
    validator_id: str
    voting_power: int

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.validator_id):
            raise ConsensusRoundError("validator_id is invalid")
        if isinstance(self.voting_power, bool) or not isinstance(self.voting_power, int) or self.voting_power <= 0:
            raise ConsensusRoundError("voting_power must be a positive integer")


@dataclass(frozen=True)
class ConsensusRoundPolicy:
    base_timeout_ms: int = 2_000
    timeout_step_ms: int = 1_000
    maximum_timeout_ms: int = 15_000
    maximum_round: int = 32

    def __post_init__(self) -> None:
        values = (
            self.base_timeout_ms,
            self.timeout_step_ms,
            self.maximum_timeout_ms,
            self.maximum_round,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ConsensusRoundError("round policy values must be positive integers")
        if self.maximum_timeout_ms < self.base_timeout_ms:
            raise ConsensusRoundError("maximum timeout is below base timeout")

    def timeout_ms(self, round: int) -> int:
        _round(round, maximum=self.maximum_round)
        return min(
            self.base_timeout_ms + round * self.timeout_step_ms,
            self.maximum_timeout_ms,
        )


class DeterministicLeaderSchedule:
    """Select a voting-power-weighted leader from immutable round inputs."""

    def __init__(
        self,
        *,
        chain_id: int,
        validator_set_hash: str,
        validators: Iterable[ConsensusValidator],
    ) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise ConsensusRoundError("chain_id must be a positive integer")
        self.chain_id = chain_id
        self.validator_set_hash = _hash(validator_set_hash, "validator_set_hash")
        items = tuple(validators)
        if len(items) < 4:
            raise ConsensusRoundError("Mainnet leader schedule requires at least 4 validators")
        if any(not isinstance(item, ConsensusValidator) for item in items):
            raise ConsensusRoundError("validator type is invalid")
        identities = tuple(item.validator_id for item in items)
        if identities != tuple(sorted(identities)):
            raise ConsensusRoundError("validators must be canonically ordered")
        if len(set(identities)) != len(identities):
            raise ConsensusRoundError("validator identities must be distinct")
        self.validators = items
        self.total_power = sum(item.voting_power for item in items)

    def leader(self, *, height: int, round: int) -> ConsensusValidator:
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ConsensusRoundError("height must be a positive integer")
        _round(round)
        seed = {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "validator_set_hash": self.validator_set_hash,
            "height": height,
            "round": round,
        }
        value = int.from_bytes(
            hashlib.sha256(
                LEADER_DOMAIN
                + json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()
            ).digest(),
            "big",
        ) % self.total_power
        cumulative = 0
        for validator in self.validators:
            cumulative += validator.voting_power
            if value < cumulative:
                return validator
        raise AssertionError("weighted leader selection exceeded total voting power")

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "validator_set_hash": self.validator_set_hash,
            "validators": [
                {
                    "validator_id": item.validator_id,
                    "voting_power": item.voting_power,
                }
                for item in self.validators
            ],
            "total_power": self.total_power,
            "leader_selection": "deterministic-weighted-domain-separated",
            "activation_status": "CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


@dataclass(frozen=True)
class ConsensusRoundState:
    chain_id: int
    validator_set_hash: str
    height: int
    round: int
    leader_id: str
    started_at_ms: int
    deadline_ms: int
    locked_block_hash: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.chain_id, bool) or not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise ConsensusRoundError("chain_id must be a positive integer")
        _hash(self.validator_set_hash, "validator_set_hash")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise ConsensusRoundError("height must be a positive integer")
        _round(self.round)
        if not _IDENTIFIER.fullmatch(self.leader_id):
            raise ConsensusRoundError("leader_id is invalid")
        for field in ("started_at_ms", "deadline_ms"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConsensusRoundError(f"{field} must be non-negative")
        if self.deadline_ms <= self.started_at_ms:
            raise ConsensusRoundError("round deadline must be after start")
        if self.locked_block_hash is not None:
            _hash(self.locked_block_hash, "locked_block_hash")

    @property
    def round_hash(self) -> str:
        return "0x" + hashlib.sha256(
            ROUND_DOMAIN
            + json.dumps(
                self.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "validator_set_hash": self.validator_set_hash.lower(),
            "height": self.height,
            "round": self.round,
            "leader_id": self.leader_id,
            "started_at_ms": self.started_at_ms,
            "deadline_ms": self.deadline_ms,
            "locked_block_hash": (
                None if self.locked_block_hash is None else self.locked_block_hash.lower()
            ),
        }


def start_round(
    *,
    schedule: DeterministicLeaderSchedule,
    policy: ConsensusRoundPolicy,
    height: int,
    round: int,
    started_at_ms: int,
    locked_block_hash: str | None = None,
) -> ConsensusRoundState:
    if not isinstance(schedule, DeterministicLeaderSchedule):
        raise ConsensusRoundError("leader schedule is required")
    if not isinstance(policy, ConsensusRoundPolicy):
        raise ConsensusRoundError("round policy is required")
    leader = schedule.leader(height=height, round=round)
    return ConsensusRoundState(
        chain_id=schedule.chain_id,
        validator_set_hash=schedule.validator_set_hash,
        height=height,
        round=round,
        leader_id=leader.validator_id,
        started_at_ms=started_at_ms,
        deadline_ms=started_at_ms + policy.timeout_ms(round),
        locked_block_hash=locked_block_hash,
    )


def advance_round(
    state: ConsensusRoundState,
    *,
    schedule: DeterministicLeaderSchedule,
    policy: ConsensusRoundPolicy,
    started_at_ms: int,
) -> ConsensusRoundState:
    if not isinstance(state, ConsensusRoundState):
        raise ConsensusRoundError("current round state is required")
    if state.chain_id != schedule.chain_id or state.validator_set_hash != schedule.validator_set_hash:
        raise ConsensusRoundError("round transition changed consensus identity")
    if started_at_ms < state.deadline_ms:
        raise ConsensusRoundError("round cannot advance before timeout")
    return start_round(
        schedule=schedule,
        policy=policy,
        height=state.height,
        round=state.round + 1,
        started_at_ms=started_at_ms,
        locked_block_hash=state.locked_block_hash,
    )


def _round(value: object, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ConsensusRoundError("round is outside policy")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise ConsensusRoundError(f"{field} must be a 32-byte hash")
    return value.lower()
