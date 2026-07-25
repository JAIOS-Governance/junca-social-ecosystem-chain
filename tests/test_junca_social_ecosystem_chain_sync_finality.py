from __future__ import annotations

import hashlib
import unittest

from jaios.social_ecosystem_chain.finality import FinalityVote, Validator
from jaios.social_ecosystem_chain.sync_finality import (
    CertifiedFinalityVerifier,
    FinalityProof,
    SyncFinalityError,
    ValidatorSet,
    ValidatorSetSchedule,
    proof_from_payload,
    proof_to_payload,
)


CHAIN_ID = 22012024


def hx(value: str) -> str:
    return "0x" + hashlib.sha256(value.encode()).hexdigest()


def vote(validator: str, height: int, block_hash: str) -> FinalityVote:
    return FinalityVote(
        chain_id=CHAIN_ID,
        height=height,
        round=0,
        block_hash=block_hash,
        validator_id=validator,
        signature=f"{validator}:{height}:{block_hash}".encode(),
    )


def certificate_hash(votes, validator_set, height, block_hash):
    import json

    ordered = sorted(votes, key=lambda item: item.validator_id)
    by_id = {item.validator_id: item for item in validator_set.validators}
    signed_power = sum(by_id[item.validator_id].voting_power for item in ordered)
    body = {
        "block_hash": block_hash.lower(),
        "chain_id": CHAIN_ID,
        "height": height,
        "round": 0,
        "signed_power": signed_power,
        "total_power": validator_set.total_power,
        "validator_ids": [item.validator_id for item in ordered],
        "vote_hashes": [item.vote_hash for item in ordered],
    }
    return "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SyncFinalityTests(unittest.TestCase):
    def setUp(self):
        self.initial = ValidatorSet(
            0,
            0,
            tuple(Validator(f"v{i}", 1) for i in range(1, 5)),
        )
        self.schedule = ValidatorSetSchedule(self.initial)
        self.verifier = CertifiedFinalityVerifier(
            chain_id=CHAIN_ID,
            schedule=self.schedule,
            vote_verifier=lambda item: bool(item.signature),
        )

    def proof(self, height=7, block_hash=None, validators=("v1", "v2", "v3")):
        block_hash = block_hash or hx(f"block-{height}")
        votes = tuple(vote(item, height, block_hash) for item in validators)
        return FinalityProof(
            chain_id=CHAIN_ID,
            height=height,
            round=0,
            block_hash=block_hash,
            validator_set_hash=self.schedule.at_height(height).set_hash,
            votes=votes,
            certificate_hash=certificate_hash(
                votes, self.schedule.at_height(height), height, block_hash
            ),
        )

    def test_valid_proof_reconstructs_certificate(self):
        proof = self.proof()
        result = self.verifier.verify(proof)
        self.assertEqual(result.certificate_hash, proof.certificate_hash)
        self.assertEqual(result.signed_power, 3)

    def test_below_quorum_and_duplicate_validator_are_rejected(self):
        with self.assertRaisesRegex(SyncFinalityError, "quorum"):
            self.verifier.verify(self.proof(validators=("v1", "v2")))
        proof = self.proof(validators=("v1", "v1", "v2"))
        with self.assertRaisesRegex(SyncFinalityError, "duplicate"):
            self.verifier.verify(proof)

    def test_unknown_validator_and_bad_signature_are_rejected(self):
        proof = self.proof()
        unknown = vote("unknown", proof.height, proof.block_hash)
        proof = FinalityProof(
            **{**proof.__dict__, "votes": proof.votes[:2] + (unknown,)}
        )
        with self.assertRaisesRegex(SyncFinalityError, "unknown"):
            self.verifier.verify(proof)
        rejecting = CertifiedFinalityVerifier(
            chain_id=CHAIN_ID,
            schedule=self.schedule,
            vote_verifier=lambda item: False,
        )
        with self.assertRaisesRegex(SyncFinalityError, "signature"):
            rejecting.verify(self.proof())

    def test_verifier_exceptions_and_non_boolean_success_fail_closed(self):
        raising = CertifiedFinalityVerifier(
            chain_id=CHAIN_ID,
            schedule=self.schedule,
            vote_verifier=lambda _: (_ for _ in ()).throw(
                RuntimeError("kms unavailable")
            ),
        )
        with self.assertRaisesRegex(SyncFinalityError, "signature verification"):
            raising.verify(self.proof())
        non_boolean = CertifiedFinalityVerifier(
            chain_id=CHAIN_ID,
            schedule=self.schedule,
            vote_verifier=lambda _: 1,
        )
        with self.assertRaisesRegex(SyncFinalityError, "signature verification"):
            non_boolean.verify(self.proof())

    def test_vote_boundary_rejects_wrong_type_and_oversized_signature(self):
        proof = self.proof()
        wrong_type = FinalityProof(
            **{**proof.__dict__, "votes": ("not-a-vote",) + proof.votes[1:]}
        )
        with self.assertRaisesRegex(SyncFinalityError, "boundary"):
            self.verifier.verify(wrong_type)
        oversized = FinalityVote(
            **{**proof.votes[0].__dict__, "signature": b"x" * 4097}
        )
        malformed = FinalityProof(
            **{**proof.__dict__, "votes": (oversized,) + proof.votes[1:]}
        )
        with self.assertRaisesRegex(SyncFinalityError, "boundary"):
            self.verifier.verify(malformed)

    def test_proof_vote_count_is_bounded_by_active_validator_set(self):
        proof = self.proof()
        oversized = FinalityProof(
            **{**proof.__dict__, "votes": proof.votes + (proof.votes[0],) * 2}
        )
        with self.assertRaisesRegex(SyncFinalityError, "too many"):
            self.verifier.verify(oversized)

    def test_vote_must_bind_height_round_chain_and_block(self):
        proof = self.proof()
        bad = FinalityVote(
            chain_id=CHAIN_ID,
            height=proof.height + 1,
            round=0,
            block_hash=proof.block_hash,
            validator_id="v1",
            signature=b"x",
        )
        proof = FinalityProof(**{**proof.__dict__, "votes": (bad,) + proof.votes[1:]})
        with self.assertRaisesRegex(SyncFinalityError, "bind"):
            self.verifier.verify(proof)

    def test_certificate_hash_tamper_is_rejected(self):
        proof = self.proof()
        proof = FinalityProof(**{**proof.__dict__, "certificate_hash": hx("wrong")})
        with self.assertRaisesRegex(SyncFinalityError, "certificate hash"):
            self.verifier.verify(proof)

    def test_validator_set_epoch_activation_boundary(self):
        old_proof = self.proof(height=10, validators=("v1", "v2", "v3"))
        next_set = ValidatorSet(
            1,
            10,
            tuple(Validator(f"n{i}", 2) for i in range(1, 4)),
        )
        self.schedule.register(next_set)
        self.assertEqual(self.schedule.at_height(9).epoch, 0)
        self.assertEqual(self.schedule.at_height(10).epoch, 1)
        with self.assertRaisesRegex(SyncFinalityError, "wrong validator set"):
            self.verifier.verify(old_proof)

    def test_schedule_rejects_epoch_gap_and_activation_regression(self):
        with self.assertRaisesRegex(SyncFinalityError, "epoch"):
            self.schedule.register(
                ValidatorSet(2, 10, tuple(Validator(f"x{i}", 1) for i in range(3)))
            )
        with self.assertRaisesRegex(SyncFinalityError, "activation"):
            self.schedule.register(
                ValidatorSet(1, 0, tuple(Validator(f"x{i}", 1) for i in range(3)))
            )

    def test_payload_round_trip_and_exact_schema(self):
        proof = self.proof()
        self.assertEqual(proof_from_payload(proof_to_payload(proof)), proof)
        payload = proof_to_payload(proof)
        payload["extra"] = True
        with self.assertRaisesRegex(SyncFinalityError, "fields"):
            proof_from_payload(payload)

    def test_non_integer_identity_and_invalid_signature_encoding_fail_closed(self):
        proof = self.proof()
        malformed = FinalityProof(**{**proof.__dict__, "height": "7"})
        with self.assertRaisesRegex(SyncFinalityError, "identity"):
            self.verifier.verify(malformed)
        payload = proof_to_payload(proof)
        payload["votes"][0]["signature"] = "not-hex"
        with self.assertRaisesRegex(SyncFinalityError, "encoding"):
            proof_from_payload(payload)
        for invalid in ("AA", "00 11", "0" * 8194, ""):
            payload = proof_to_payload(proof)
            payload["votes"][0]["signature"] = invalid
            with self.assertRaisesRegex(SyncFinalityError, "encoding"):
                proof_from_payload(payload)

    def test_schedule_height_and_registration_types_fail_closed(self):
        with self.assertRaisesRegex(SyncFinalityError, "non-negative"):
            self.schedule.at_height(True)
        with self.assertRaisesRegex(SyncFinalityError, "type"):
            self.schedule.register("not-a-validator-set")  # type: ignore[arg-type]

    def test_evidence_preserves_release_boundaries(self):
        evidence = self.schedule.evidence()
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
