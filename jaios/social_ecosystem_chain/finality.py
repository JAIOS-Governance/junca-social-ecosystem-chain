"""Round-based Byzantine finality state machine for block commitments."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Iterable


class FinalityError(ValueError):
    """Raised when a finality message violates a consensus invariant."""


@dataclass(frozen=True)
class Validator:
    validator_id: str
    voting_power: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.validator_id, str)
            or not self.validator_id
            or len(self.validator_id.encode("utf-8")) > 128
            or (
            isinstance(self.voting_power, bool)
            or not isinstance(self.voting_power, int)
            or self.voting_power <= 0
            )
        ):
            raise FinalityError("validator identity and voting power are required")


@dataclass(frozen=True)
class FinalityVote:
    chain_id: int
    height: int
    round: int
    block_hash: str
    validator_id: str
    signature: bytes

    @property
    def signing_payload(self) -> bytes:
        canonical = {
            "block_hash": self.block_hash.lower(),
            "chain_id": self.chain_id,
            "height": self.height,
            "round": self.round,
            "validator_id": self.validator_id,
            "vote_type": "PRECOMMIT",
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def vote_hash(self) -> str:
        return "0x" + hashlib.sha256(self.signing_payload + self.signature).hexdigest()


@dataclass(frozen=True)
class FinalityCertificate:
    chain_id: int
    height: int
    round: int
    block_hash: str
    signed_power: int
    total_power: int
    validator_ids: tuple[str, ...]
    vote_hashes: tuple[str, ...]
    certificate_hash: str

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-finality-certificate/v1",
            "chain_id": self.chain_id,
            "height": self.height,
            "round": self.round,
            "block_hash": self.block_hash,
            "signed_power": self.signed_power,
            "total_power": self.total_power,
            "validator_ids": list(self.validator_ids),
            "vote_hashes": list(self.vote_hashes),
            "certificate_hash": self.certificate_hash,
            "finality_status": "FINALIZED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


VoteVerifier = Callable[[FinalityVote], bool]


class FinalityStateMachine:
    def __init__(
        self,
        *,
        chain_id: int,
        validators: Iterable[Validator],
        initial_finalized_height: int = -1,
    ) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise FinalityError("chain_id must be a positive integer")
        if (
            isinstance(initial_finalized_height, bool)
            or not isinstance(initial_finalized_height, int)
            or initial_finalized_height < -1
        ):
            raise FinalityError("initial_finalized_height must be at least -1")
        items = tuple(validators)
        if len(items) < 3:
            raise FinalityError("at least three validators are required")
        by_id = {item.validator_id: item for item in items}
        if len(by_id) != len(items):
            raise FinalityError("validator identities must be distinct")
        self.chain_id = chain_id
        self.validators = dict(sorted(by_id.items()))
        self.total_power = sum(item.voting_power for item in items)
        self._checkpoint_height = initial_finalized_height
        self._votes: dict[tuple[int, int, str], FinalityVote] = {}
        self._finalized: dict[int, FinalityCertificate] = {}
        self._equivocations: set[tuple[int, int, str]] = set()

    @property
    def quorum_power(self) -> int:
        return (self.total_power * 2) // 3 + 1

    @property
    def latest_finalized_height(self) -> int:
        return max(self._finalized, default=self._checkpoint_height)

    @property
    def equivocations(self) -> tuple[tuple[int, int, str], ...]:
        return tuple(sorted(self._equivocations))

    def add_vote(
        self,
        vote: FinalityVote,
        *,
        verifier: VoteVerifier,
    ) -> FinalityCertificate | None:
        self._validate_vote(vote, verifier)
        finalized = self._finalized.get(vote.height)
        if finalized is not None:
            if finalized.block_hash == vote.block_hash.lower():
                return finalized
            raise FinalityError("conflicting vote for finalized height")
        identity = (vote.height, vote.round, vote.validator_id)
        previous = self._votes.get(identity)
        if previous is not None:
            if previous.block_hash.lower() == vote.block_hash.lower():
                return self._certificate_if_finalized(vote.height, vote.block_hash)
            self._equivocations.add(identity)
            raise FinalityError("validator equivocation detected")
        self._votes[identity] = vote

        matching = [
            item
            for item in self._votes.values()
            if item.height == vote.height
            and item.round == vote.round
            and item.block_hash.lower() == vote.block_hash.lower()
        ]
        signed_power = sum(self.validators[item.validator_id].voting_power for item in matching)
        if signed_power < self.quorum_power:
            return None

        certificate = self._build_certificate(vote, matching, signed_power)
        existing = self._finalized.get(vote.height)
        if existing is not None and existing.certificate_hash != certificate.certificate_hash:
            raise FinalityError("height already finalized with a different certificate")
        latest = self.latest_finalized_height
        if (latest == -1 and vote.height != 0) or (
            latest >= 0 and latest not in {vote.height - 1, vote.height}
        ):
            raise FinalityError("finality height is not contiguous")
        self._finalized[vote.height] = certificate
        return certificate

    def get_certificate(self, height: int) -> FinalityCertificate:
        try:
            return self._finalized[height]
        except KeyError as exc:
            raise FinalityError("height is not finalized") from exc

    def _validate_vote(self, vote: FinalityVote, verifier: VoteVerifier) -> None:
        if not isinstance(vote, FinalityVote):
            raise FinalityError("finality accepts only FinalityVote values")
        if vote.chain_id != self.chain_id:
            raise FinalityError("vote chain_id mismatch")
        if (
            isinstance(vote.height, bool)
            or not isinstance(vote.height, int)
            or vote.height < 0
            or isinstance(vote.round, bool)
            or not isinstance(vote.round, int)
            or vote.round < 0
        ):
            raise FinalityError("height and round must be non-negative integers")
        _validate_block_hash(vote.block_hash)
        if vote.validator_id not in self.validators:
            raise FinalityError("vote is from an unknown validator")
        if (
            not isinstance(vote.signature, bytes)
            or not vote.signature
            or len(vote.signature) > 4096
        ):
            raise FinalityError("vote signature must be 1 to 4096 bytes")
        if not callable(verifier):
            raise FinalityError("vote signature verification failed")
        try:
            verified = verifier(vote)
        except Exception as exc:
            raise FinalityError("vote signature verification failed") from exc
        if verified is not True:
            raise FinalityError("vote signature verification failed")
        if vote.height < self.latest_finalized_height:
            raise FinalityError("vote height is below finalized head")
        if vote.height > self.latest_finalized_height + 1:
            raise FinalityError("vote height is not the next contiguous height")

    def _build_certificate(
        self,
        vote: FinalityVote,
        matching: list[FinalityVote],
        signed_power: int,
    ) -> FinalityCertificate:
        ordered = sorted(matching, key=lambda item: item.validator_id)
        body = {
            "block_hash": vote.block_hash.lower(),
            "chain_id": self.chain_id,
            "height": vote.height,
            "round": vote.round,
            "signed_power": signed_power,
            "total_power": self.total_power,
            "validator_ids": [item.validator_id for item in ordered],
            "vote_hashes": [item.vote_hash for item in ordered],
        }
        certificate_hash = "0x" + hashlib.sha256(
            b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return FinalityCertificate(
            chain_id=self.chain_id,
            height=vote.height,
            round=vote.round,
            block_hash=vote.block_hash.lower(),
            signed_power=signed_power,
            total_power=self.total_power,
            validator_ids=tuple(body["validator_ids"]),
            vote_hashes=tuple(body["vote_hashes"]),
            certificate_hash=certificate_hash,
        )

    def _certificate_if_finalized(
        self, height: int, block_hash: str
    ) -> FinalityCertificate | None:
        certificate = self._finalized.get(height)
        if certificate is not None and certificate.block_hash == block_hash.lower():
            return certificate
        return None


def _validate_block_hash(value: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise FinalityError("block_hash must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise FinalityError("block_hash must be a 32-byte hex value") from exc
