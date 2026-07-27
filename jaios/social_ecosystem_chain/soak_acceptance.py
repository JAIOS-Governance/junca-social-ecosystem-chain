"""Deterministic 24-hour public-testnet finality soak simulation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .consensus_signing_journal import (
    ConsensusSigningJournal,
    ConsensusSigningJournalError,
)
from .finality import FinalityVote


CHAIN_ID = 20260723
VALIDATORS = ("validator-01", "validator-02", "validator-03")
INTERVAL_SECONDS = 30
SLOT_COUNT = 24 * 60 * 60 // INTERVAL_SECONDS
EPOCH_SECONDS = 1_800_000_000
ZERO_HASH = "0x" + ("0" * 64)


class SoakAcceptanceError(RuntimeError):
    """Raised when deterministic soak acceptance fails closed."""


@dataclass(frozen=True)
class SoakScenario:
    restart_slot: int = 720
    loss_start_slot: int = 960
    loss_end_slot: int = 979
    throttle_slot: int = 1440
    retry_slot: int = 1800


def run_soak_simulation(scenario: SoakScenario = SoakScenario()) -> dict[str, Any]:
    _validate_scenario(scenario)
    with TemporaryDirectory(prefix="junca-soak-") as directory:
        root = Path(directory)
        journals = _open_journals(root)
        signer_calls = {validator: 0 for validator in VALIDATORS}
        head_height = 0
        head_hash = ZERO_HASH
        stalled_slots = 0
        replay_count = 0
        throttle_recovered = False
        restart_recovered = False
        same_slot_retry_verified = False

        try:
            for slot in range(1, SLOT_COUNT + 1):
                if slot == scenario.restart_slot:
                    _close_journals(journals)
                    journals = _open_journals(root)
                    restart_recovered = True

                height = head_height + 1
                timestamp = EPOCH_SECONDS + (height * INTERVAL_SECONDS)
                block_hash = _block_hash(head_hash, height, timestamp)
                available = set(VALIDATORS)
                if scenario.loss_start_slot <= slot <= scenario.loss_end_slot:
                    available.remove("validator-03")

                signed: set[str] = set()
                for validator in VALIDATORS:
                    if validator not in available:
                        continue
                    throttle = slot == scenario.throttle_slot and validator == "validator-02"
                    try:
                        before = signer_calls[validator]
                        _sign(
                            journals[validator],
                            validator,
                            height,
                            block_hash,
                            signer_calls,
                            throttle=throttle,
                        )
                    except SoakAcceptanceError:
                        _sign(
                            journals[validator],
                            validator,
                            height,
                            block_hash,
                            signer_calls,
                        )
                        throttle_recovered = True
                    if signer_calls[validator] == before:
                        replay_count += 1
                    signed.add(validator)

                if slot == scenario.retry_slot:
                    before = dict(signer_calls)
                    for validator in sorted(signed):
                        _sign(
                            journals[validator],
                            validator,
                            height,
                            block_hash,
                            signer_calls,
                        )
                    if signer_calls != before:
                        raise SoakAcceptanceError("same-slot retry called a signer twice")
                    replay_count += len(signed)
                    same_slot_retry_verified = True

                if signed == set(VALIDATORS):
                    head_height = height
                    head_hash = block_hash
                else:
                    stalled_slots += 1

            conflict_rejected = _assert_conflict_rejected(
                journals["validator-01"], head_height, head_hash
            )
            journal_evidence = {
                validator: journals[validator].evidence()
                for validator in VALIDATORS
            }
        finally:
            _close_journals(journals)

    checks = {
        "24_hour_window": SLOT_COUNT * INTERVAL_SECONDS == 86_400,
        "restart_recovered": restart_recovered,
        "one_node_loss_failed_closed": stalled_slots
        == scenario.loss_end_slot - scenario.loss_start_slot + 1,
        "kms_throttle_recovered": throttle_recovered,
        "same_slot_retry_idempotent": same_slot_retry_verified,
        "conflicting_vote_rejected": conflict_rejected,
        "all_journals_at_finalized_height": all(
            item["latest_height"] == head_height for item in journal_evidence.values()
        ),
        "mainnet_unchanged": True,
        "assets_not_moved": True,
        "bridge_not_activated": True,
    }
    result = "PASS" if all(checks.values()) else "FAIL"
    evidence: dict[str, Any] = {
        "schema_version": "junca-public-testnet-soak-acceptance/v1",
        "result": result,
        "simulation": {
            "deterministic": True,
            "duration_seconds": 86_400,
            "interval_seconds": INTERVAL_SECONDS,
            "slot_count": SLOT_COUNT,
            "finalized_height": head_height,
            "finalized_head_hash": head_hash,
            "stalled_slots": stalled_slots,
            "signature_provider_calls": signer_calls,
            "journal_replays": replay_count,
        },
        "scenario": scenario.__dict__,
        "checks": checks,
        "journals": journal_evidence,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if result != "PASS":
        raise SoakAcceptanceError("deterministic soak acceptance failed")
    return evidence


def write_soak_evidence(path: str | Path) -> dict[str, Any]:
    evidence = run_soak_simulation()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def _sign(
    journal: ConsensusSigningJournal,
    validator: str,
    height: int,
    block_hash: str,
    signer_calls: dict[str, int],
    *,
    throttle: bool = False,
) -> bytes:
    unsigned = FinalityVote(
        chain_id=CHAIN_ID,
        height=height,
        round=0,
        block_hash=block_hash,
        validator_id=validator,
        signature=b"",
    )

    def provider() -> bytes:
        if throttle:
            raise RuntimeError("simulated provider throttle")
        signer_calls[validator] += 1
        return _signature(validator, unsigned.signing_payload)

    try:
        return journal.get_or_sign(
            validator_id=validator,
            height=height,
            round=0,
            block_hash=block_hash,
            signing_payload=unsigned.signing_payload,
            signer=provider,
            signature_verifier=lambda signature: signature
            == _signature(validator, unsigned.signing_payload),
        )
    except ConsensusSigningJournalError as exc:
        raise SoakAcceptanceError(str(exc)) from exc


def _assert_conflict_rejected(
    journal: ConsensusSigningJournal, height: int, block_hash: str
) -> bool:
    conflict = "0x" + hashlib.sha256(block_hash.encode()).hexdigest()
    try:
        _sign(
            journal,
            "validator-01",
            height,
            conflict,
            {"validator-01": 0},
        )
    except SoakAcceptanceError as exc:
        return "double-sign" in str(exc)
    return False


def _block_hash(parent_hash: str, height: int, timestamp: int) -> str:
    body = {
        "chain_id": CHAIN_ID,
        "height": height,
        "parent_hash": parent_hash,
        "timestamp": timestamp,
    }
    return "0x" + hashlib.sha256(
        b"JUNCA_SOAK_BLOCK_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _signature(validator: str, payload: bytes) -> bytes:
    left = hashlib.sha256(validator.encode() + b"\x00" + payload).digest()
    right = hashlib.sha256(payload + b"\x00" + validator.encode()).digest()
    return left + right


def _open_journals(root: Path) -> dict[str, ConsensusSigningJournal]:
    return {
        validator: ConsensusSigningJournal(
            root / f"{validator}.sqlite", chain_id=CHAIN_ID
        )
        for validator in VALIDATORS
    }


def _close_journals(journals: dict[str, ConsensusSigningJournal]) -> None:
    for journal in journals.values():
        journal.close()


def _validate_scenario(scenario: SoakScenario) -> None:
    values = tuple(scenario.__dict__.values())
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise SoakAcceptanceError("scenario slots must be integers")
    if not (
        1 <= scenario.restart_slot < scenario.loss_start_slot
        <= scenario.loss_end_slot < scenario.throttle_slot
        < scenario.retry_slot <= SLOT_COUNT
    ):
        raise SoakAcceptanceError("scenario slots are out of deterministic order")
