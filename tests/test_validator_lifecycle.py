from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.validator_lifecycle import (
    ValidatorIdentity,
    ValidatorLifecycleError,
    ValidatorSetTransition,
    build_validator_set_candidate,
)


CURRENT_HASH = "0x" + ("aa" * 32)
REASON_HASH = "0x" + ("bb" * 32)


def _validator(index: int, *, power: int = 1) -> ValidatorIdentity:
    return ValidatorIdentity(
        validator_id=f"validator-{index:02d}",
        voting_power=power,
        signer_resource_digest="0x" + f"{index:064x}",
        region=("ap-northeast-1", "eu-west-1", "us-east-1")[index % 3],
        failure_domain=f"domain-{index % 5}",
    )


class ValidatorLifecycleTests(unittest.TestCase):
    def _candidate(self):
        return build_validator_set_candidate(
            epoch=1,
            activation_height=10_000,
            validators=(_validator(index) for index in range(1, 10)),
        )

    def test_candidate_is_canonical_and_requires_seven_of_nine_power(self) -> None:
        candidate = self._candidate()

        self.assertEqual(len(candidate.validators), 9)
        self.assertEqual(candidate.quorum_power, 7)
        self.assertRegex(candidate.set_hash, r"^0x[0-9a-f]{64}$")
        self.assertEqual(
            tuple(item.validator_id for item in candidate.validators),
            tuple(sorted(item.validator_id for item in candidate.validators)),
        )

    def test_insufficient_geographic_distribution_fails_closed(self) -> None:
        validators = tuple(
            ValidatorIdentity(
                validator_id=f"validator-{index:02d}",
                voting_power=1,
                signer_resource_digest="0x" + f"{index:064x}",
                region="ap-northeast-1",
                failure_domain=f"domain-{index % 5}",
            )
            for index in range(1, 10)
        )

        with self.assertRaisesRegex(ValidatorLifecycleError, "regions"):
            build_validator_set_candidate(
                epoch=1,
                activation_height=10_000,
                validators=validators,
            )

    def test_concentrated_voting_power_fails_closed(self) -> None:
        validators = [_validator(index) for index in range(1, 10)]
        validators[0] = _validator(1, power=10)

        with self.assertRaisesRegex(ValidatorLifecycleError, "voting power"):
            build_validator_set_candidate(
                epoch=1,
                activation_height=10_000,
                validators=validators,
            )

    def test_transition_requires_independent_approvals(self) -> None:
        with self.assertRaisesRegex(ValidatorLifecycleError, "approvals"):
            ValidatorSetTransition(
                current_set_hash=CURRENT_HASH,
                next_set=self._candidate(),
                approvals=("protocol-maintainer", "security-reviewer"),
                reason_digest=REASON_HASH,
            )

        transition = ValidatorSetTransition(
            current_set_hash=CURRENT_HASH,
            next_set=self._candidate(),
            approvals=(
                "protocol-maintainer",
                "release-approver",
                "security-reviewer",
            ),
            reason_digest=REASON_HASH,
        )
        self.assertRegex(transition.transition_hash, r"^0x[0-9a-f]{64}$")

    def test_evidence_never_activates_mainnet(self) -> None:
        evidence = self._candidate().as_evidence()

        self.assertEqual(evidence["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
