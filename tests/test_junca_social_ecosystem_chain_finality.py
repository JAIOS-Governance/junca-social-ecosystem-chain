from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.finality import (
    FinalityError,
    FinalityStateMachine,
    FinalityVote,
    Validator,
)


CHAIN_ID = 20260723
BLOCK_A = "0x" + ("a" * 64)
BLOCK_B = "0x" + ("b" * 64)


def vote(validator: str, block_hash: str = BLOCK_A, height: int = 0, round: int = 0):
    return FinalityVote(
        chain_id=CHAIN_ID,
        height=height,
        round=round,
        block_hash=block_hash,
        validator_id=validator,
        signature=f"{validator}:{height}:{round}:{block_hash}".encode(),
    )


class FinalityStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validators = (
            Validator("validator-1", 1),
            Validator("validator-2", 1),
            Validator("validator-3", 1),
            Validator("validator-4", 1),
        )
        self.machine = FinalityStateMachine(chain_id=CHAIN_ID, validators=self.validators)
        self.verify = lambda item: bool(item.signature)

    def add(self, item: FinalityVote):
        return self.machine.add_vote(item, verifier=self.verify)

    def test_strict_two_thirds_plus_one_finalizes(self) -> None:
        self.assertEqual(self.machine.quorum_power, 3)
        self.assertIsNone(self.add(vote("validator-1")))
        self.assertIsNone(self.add(vote("validator-2")))
        certificate = self.add(vote("validator-3"))
        self.assertIsNotNone(certificate)
        assert certificate is not None
        self.assertEqual(certificate.signed_power, 3)
        self.assertEqual(certificate.as_evidence()["finality_status"], "FINALIZED")

    def test_certificate_is_deterministic_across_vote_arrival_order(self) -> None:
        first = FinalityStateMachine(chain_id=CHAIN_ID, validators=self.validators)
        second = FinalityStateMachine(chain_id=CHAIN_ID, validators=self.validators)
        for validator in ("validator-1", "validator-2", "validator-3"):
            left = first.add_vote(vote(validator), verifier=self.verify)
        for validator in ("validator-3", "validator-1", "validator-2"):
            right = second.add_vote(vote(validator), verifier=self.verify)
        assert left is not None and right is not None
        self.assertEqual(left.certificate_hash, right.certificate_hash)

    def test_duplicate_vote_is_idempotent(self) -> None:
        item = vote("validator-1")
        self.assertIsNone(self.add(item))
        self.assertIsNone(self.add(item))

    def test_equivocation_is_detected_and_recorded(self) -> None:
        self.add(vote("validator-1", BLOCK_A))
        with self.assertRaisesRegex(FinalityError, "equivocation"):
            self.add(vote("validator-1", BLOCK_B))
        self.assertEqual(self.machine.equivocations, ((0, 0, "validator-1"),))

    def test_unknown_validator_chain_replay_and_bad_signature_are_rejected(self) -> None:
        with self.assertRaisesRegex(FinalityError, "unknown validator"):
            self.add(vote("validator-9"))
        replay = vote("validator-1")
        replay = FinalityVote(**{**replay.__dict__, "chain_id": 1})
        with self.assertRaisesRegex(FinalityError, "chain_id"):
            self.add(replay)
        with self.assertRaisesRegex(FinalityError, "signature verification"):
            self.machine.add_vote(vote("validator-1"), verifier=lambda item: False)

    def test_conflicting_vote_after_finality_is_rejected(self) -> None:
        for validator in ("validator-1", "validator-2", "validator-3"):
            self.add(vote(validator))
        with self.assertRaisesRegex(FinalityError, "finalized"):
            self.add(vote("validator-4", BLOCK_B))

    def test_finality_height_must_be_contiguous(self) -> None:
        with self.assertRaisesRegex(FinalityError, "contiguous"):
            self.add(vote("validator-1", height=2))

    def test_future_height_rejection_does_not_poison_later_finality(self) -> None:
        with self.assertRaisesRegex(FinalityError, "contiguous"):
            self.add(vote("validator-1", height=1))
        for validator in ("validator-1", "validator-2", "validator-3"):
            certificate = self.add(vote(validator, height=0))
        self.assertIsNotNone(certificate)
        for validator in ("validator-1", "validator-2", "validator-3"):
            certificate = self.add(vote(validator, height=1))
        self.assertIsNotNone(certificate)
        self.assertEqual(self.machine.latest_finalized_height, 1)

    def test_same_block_vote_after_finality_returns_canonical_certificate(self) -> None:
        certificate = None
        for validator in ("validator-1", "validator-2", "validator-3"):
            certificate = self.add(vote(validator))
        assert certificate is not None
        replay = self.add(vote("validator-4", round=99))
        self.assertEqual(replay, certificate)

    def test_signature_boundary_is_strict_and_verifier_exceptions_fail_closed(self) -> None:
        invalid_type = FinalityVote(
            chain_id=CHAIN_ID,
            height=0,
            round=0,
            block_hash=BLOCK_A,
            validator_id="validator-1",
            signature="not-bytes",  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(FinalityError, "1 to 4096 bytes"):
            self.add(invalid_type)
        with self.assertRaisesRegex(FinalityError, "verification failed"):
            self.machine.add_vote(
                vote("validator-1"),
                verifier=lambda _: (_ for _ in ()).throw(RuntimeError("signer unavailable")),
            )
        with self.assertRaisesRegex(FinalityError, "verification failed"):
            self.machine.add_vote(vote("validator-1"), verifier=lambda _: 1)

    def test_weighted_power_requires_actual_quorum(self) -> None:
        validators = (
            Validator("large", 7),
            Validator("small-1", 1),
            Validator("small-2", 1),
        )
        machine = FinalityStateMachine(chain_id=CHAIN_ID, validators=validators)
        self.assertEqual(machine.quorum_power, 7)
        certificate = machine.add_vote(vote("large"), verifier=self.verify)
        self.assertIsNotNone(certificate)
        assert certificate is not None
        self.assertEqual(certificate.signed_power, 7)

    def test_checkpoint_height_allows_restart_at_next_finalized_block(self) -> None:
        machine = FinalityStateMachine(
            chain_id=CHAIN_ID,
            validators=self.validators,
            initial_finalized_height=7,
        )
        certificate = None
        for validator in ("validator-1", "validator-2", "validator-3"):
            certificate = machine.add_vote(
                vote(validator, height=8),
                verifier=self.verify,
            )
        self.assertIsNotNone(certificate)
        self.assertEqual(machine.latest_finalized_height, 8)

    def test_checkpoint_height_validation_fails_closed(self) -> None:
        with self.assertRaisesRegex(FinalityError, "initial_finalized_height"):
            FinalityStateMachine(
                chain_id=CHAIN_ID,
                validators=self.validators,
                initial_finalized_height=True,
            )


if __name__ == "__main__":
    unittest.main()
