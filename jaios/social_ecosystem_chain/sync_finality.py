"""Epoch-bound finality-proof verification for synchronized block ranges."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable, Mapping

from .finality import FinalityCertificate, FinalityVote, Validator


class SyncFinalityError(ValueError):
    """Raised when remote finality evidence is incomplete or invalid."""


@dataclass(frozen=True)
class ValidatorSet:
    epoch: int
    activation_height: int
    validators: tuple[Validator, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.epoch, bool)
            or not isinstance(self.epoch, int)
            or self.epoch < 0
            or isinstance(self.activation_height, bool)
            or not isinstance(self.activation_height, int)
            or self.activation_height < 0
            or not isinstance(self.validators, tuple)
            or len(self.validators) < 3
            or len(self.validators) > 10_000
            or any(not isinstance(item, Validator) for item in self.validators)
        ):
            raise SyncFinalityError("validator set identity is invalid")
        identities = [item.validator_id for item in self.validators]
        if len(set(identities)) != len(identities):
            raise SyncFinalityError("validator set identities must be distinct")
        if tuple(sorted(identities)) != tuple(identities):
            raise SyncFinalityError("validator set must be canonically ordered")

    @property
    def total_power(self) -> int:
        return sum(item.voting_power for item in self.validators)

    @property
    def quorum_power(self) -> int:
        return (self.total_power * 2) // 3 + 1

    @property
    def set_hash(self) -> str:
        body = {
            "activation_height": self.activation_height,
            "epoch": self.epoch,
            "validators": [
                {"validator_id": item.validator_id, "voting_power": item.voting_power}
                for item in self.validators
            ],
        }
        return "0x" + hashlib.sha256(
            b"JUNCA_VALIDATOR_SET_V1\x00"
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ValidatorSetSchedule:
    """Deterministic, append-only validator-set activation schedule."""

    def __init__(self, initial: ValidatorSet) -> None:
        if initial.epoch != 0 or initial.activation_height != 0:
            raise SyncFinalityError("initial validator set must activate at genesis")
        self._sets = [initial]

    def register(self, item: ValidatorSet) -> None:
        if not isinstance(item, ValidatorSet):
            raise SyncFinalityError("validator set type is invalid")
        previous = self._sets[-1]
        if item.epoch != previous.epoch + 1:
            raise SyncFinalityError("validator set epoch must be contiguous")
        if item.activation_height <= previous.activation_height:
            raise SyncFinalityError("validator set activation must advance")
        self._sets.append(item)

    def at_height(self, height: int) -> ValidatorSet:
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise SyncFinalityError("finality height must be non-negative")
        active = self._sets[0]
        for item in self._sets[1:]:
            if item.activation_height > height:
                break
            active = item
        return active

    def evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-validator-set-schedule/v1",
            "epochs": len(self._sets),
            "latest_epoch": self._sets[-1].epoch,
            "latest_set_hash": self._sets[-1].set_hash,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


@dataclass(frozen=True)
class FinalityProof:
    chain_id: int
    height: int
    round: int
    block_hash: str
    validator_set_hash: str
    votes: tuple[FinalityVote, ...]
    certificate_hash: str


VoteVerifier = Callable[[FinalityVote], bool]


class CertifiedFinalityVerifier:
    """Reconstructs certificates from signed votes under the active set."""

    def __init__(
        self,
        *,
        chain_id: int,
        schedule: ValidatorSetSchedule,
        vote_verifier: VoteVerifier,
    ) -> None:
        if (
            isinstance(chain_id, bool)
            or not isinstance(chain_id, int)
            or chain_id <= 0
            or not isinstance(schedule, ValidatorSetSchedule)
            or not callable(vote_verifier)
        ):
            raise SyncFinalityError("finality verifier policy is invalid")
        self.chain_id = chain_id
        self.schedule = schedule
        self.vote_verifier = vote_verifier

    def verify(self, proof: FinalityProof) -> FinalityCertificate:
        if not isinstance(proof, FinalityProof):
            raise SyncFinalityError("finality proof type is invalid")
        if (
            proof.chain_id != self.chain_id
            or isinstance(proof.height, bool)
            or not isinstance(proof.height, int)
            or proof.height < 0
            or isinstance(proof.round, bool)
            or not isinstance(proof.round, int)
            or proof.round < 0
            or not isinstance(proof.votes, tuple)
            or not proof.votes
        ):
            raise SyncFinalityError("finality proof identity mismatch")
        _hash(proof.block_hash, "block_hash")
        _hash(proof.validator_set_hash, "validator_set_hash")
        _hash(proof.certificate_hash, "certificate_hash")
        active = self.schedule.at_height(proof.height)
        if proof.validator_set_hash.lower() != active.set_hash:
            raise SyncFinalityError("finality proof uses the wrong validator set")
        if len(proof.votes) > len(active.validators):
            raise SyncFinalityError("finality proof contains too many votes")
        by_id = {item.validator_id: item for item in active.validators}
        seen: set[str] = set()
        accepted: list[FinalityVote] = []
        for vote in proof.votes:
            if (
                not isinstance(vote, FinalityVote)
                or not isinstance(vote.validator_id, str)
                or not isinstance(vote.signature, bytes)
                or not vote.signature
                or len(vote.signature) > 4096
            ):
                raise SyncFinalityError("finality vote boundary is invalid")
            _hash(vote.block_hash, "vote block_hash")
            if vote.validator_id in seen:
                raise SyncFinalityError("finality proof contains a duplicate validator")
            seen.add(vote.validator_id)
            if vote.validator_id not in by_id:
                raise SyncFinalityError("finality proof contains an unknown validator")
            if (
                vote.chain_id != proof.chain_id
                or vote.height != proof.height
                or vote.round != proof.round
                or vote.block_hash.lower() != proof.block_hash.lower()
            ):
                raise SyncFinalityError("finality vote does not bind the proof")
            try:
                verified = self.vote_verifier(vote)
            except Exception as exc:
                raise SyncFinalityError(
                    "finality vote signature verification failed"
                ) from exc
            if verified is not True:
                raise SyncFinalityError("finality vote signature verification failed")
            accepted.append(vote)
        signed_power = sum(by_id[item.validator_id].voting_power for item in accepted)
        if signed_power < active.quorum_power:
            raise SyncFinalityError("finality proof lacks strict two-thirds quorum")
        ordered = sorted(accepted, key=lambda item: item.validator_id)
        body = {
            "block_hash": proof.block_hash.lower(),
            "chain_id": self.chain_id,
            "height": proof.height,
            "round": proof.round,
            "signed_power": signed_power,
            "total_power": active.total_power,
            "validator_ids": [item.validator_id for item in ordered],
            "vote_hashes": [item.vote_hash for item in ordered],
        }
        certificate_hash = "0x" + hashlib.sha256(
            b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
            + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if certificate_hash != proof.certificate_hash.lower():
            raise SyncFinalityError("finality certificate hash mismatch")
        return FinalityCertificate(
            chain_id=self.chain_id,
            height=proof.height,
            round=proof.round,
            block_hash=proof.block_hash.lower(),
            signed_power=signed_power,
            total_power=active.total_power,
            validator_ids=tuple(body["validator_ids"]),
            vote_hashes=tuple(body["vote_hashes"]),
            certificate_hash=certificate_hash,
        )


def proof_from_payload(payload: Mapping[str, object]) -> FinalityProof:
    required = {
        "chain_id",
        "height",
        "round",
        "block_hash",
        "validator_set_hash",
        "votes",
        "certificate_hash",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise SyncFinalityError("finality proof fields are invalid")
    raw_votes = payload["votes"]
    if not isinstance(raw_votes, list) or not raw_votes:
        raise SyncFinalityError("finality proof votes are invalid")
    votes = []
    vote_fields = {
        "chain_id",
        "height",
        "round",
        "block_hash",
        "validator_id",
        "signature",
    }
    for raw in raw_votes:
        if not isinstance(raw, Mapping) or set(raw) != vote_fields:
            raise SyncFinalityError("finality vote fields are invalid")
        encoded_signature = raw["signature"]
        if (
            not isinstance(encoded_signature, str)
            or len(encoded_signature) < 2
            or len(encoded_signature) > 8192
            or len(encoded_signature) % 2
            or re.fullmatch(r"[0-9a-f]+", encoded_signature) is None
        ):
            raise SyncFinalityError("finality vote signature encoding is invalid")
        try:
            signature = bytes.fromhex(encoded_signature)
        except (TypeError, ValueError) as exc:
            raise SyncFinalityError("finality vote signature encoding is invalid") from exc
        values = dict(raw)
        values["signature"] = signature
        votes.append(FinalityVote(**values))
    values = dict(payload)
    values["votes"] = tuple(votes)
    return FinalityProof(**values)


def proof_to_payload(proof: FinalityProof) -> dict[str, object]:
    return {
        "chain_id": proof.chain_id,
        "height": proof.height,
        "round": proof.round,
        "block_hash": proof.block_hash,
        "validator_set_hash": proof.validator_set_hash,
        "votes": [
            {
                "chain_id": vote.chain_id,
                "height": vote.height,
                "round": vote.round,
                "block_hash": vote.block_hash,
                "validator_id": vote.validator_id,
                "signature": vote.signature.hex(),
            }
            for vote in proof.votes
        ],
        "certificate_hash": proof.certificate_hash,
    }


def _hash(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise SyncFinalityError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise SyncFinalityError(f"{field} must be a 32-byte hex value") from exc
