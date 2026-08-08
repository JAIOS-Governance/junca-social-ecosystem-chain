from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.consensus_rounds import (
    ConsensusRoundError,
    ConsensusRoundPolicy,
    ConsensusValidator,
    DeterministicLeaderSchedule,
    advance_round,
    start_round,
)


SET_HASH = "0x" + ("11" * 32)
LOCK_HASH = "0x" + ("22" * 32)


def _validators() -> tuple[ConsensusValidator, ...]:
    return tuple(
        ConsensusValidator(
            validator_id=f"validator-{index:02d}",
            voting_power=1,
        )
        for index in range(1, 10)
    )


class ConsensusRoundTests(unittest.TestCase):
    def _schedule(self) -> DeterministicLeaderSchedule:
        return DeterministicLeaderSchedule(
            chain_id=20260723,
            validator_set_hash=SET_HASH,
            validators=_validators(),
        )

    def test_leader_selection_is_deterministic(self) -> None:
        schedule = self._schedule()

        first = schedule.leader(height=100, round=0)
        second = schedule.leader(height=100, round=0)

        self.assertEqual(first, second)
        self.assertIn(first, _validators())

    def test_height_and_round_change_leader_seed(self) -> None:
        schedule = self._schedule()
        selections = {
            schedule.leader(height=height, round=round).validator_id
            for height in range(100, 110)
            for round in range(3)
        }

        self.assertGreater(len(selections), 1)

    def test_timeout_increases_and_is_bounded(self) -> None:
        policy = ConsensusRoundPolicy(
            base_timeout_ms=2_000,
            timeout_step_ms=1_000,
            maximum_timeout_ms=5_000,
            maximum_round=32,
        )

        self.assertEqual(policy.timeout_ms(0), 2_000)
        self.assertEqual(policy.timeout_ms(2), 4_000)
        self.assertEqual(policy.timeout_ms(10), 5_000)

    def test_round_advances_only_after_deadline_and_preserves_lock(self) -> None:
        schedule = self._schedule()
        policy = ConsensusRoundPolicy()
        state = start_round(
            schedule=schedule,
            policy=policy,
            height=100,
            round=0,
            started_at_ms=10_000,
            locked_block_hash=LOCK_HASH,
        )

        with self.assertRaisesRegex(ConsensusRoundError, "before timeout"):
            advance_round(
                state,
                schedule=schedule,
                policy=policy,
                started_at_ms=state.deadline_ms - 1,
            )

        advanced = advance_round(
            state,
            schedule=schedule,
            policy=policy,
            started_at_ms=state.deadline_ms,
        )
        self.assertEqual(advanced.height, state.height)
        self.assertEqual(advanced.round, 1)
        self.assertEqual(advanced.locked_block_hash, LOCK_HASH)
        self.assertNotEqual(advanced.round_hash, state.round_hash)

    def test_round_transition_rejects_validator_set_change(self) -> None:
        schedule = self._schedule()
        policy = ConsensusRoundPolicy()
        state = start_round(
            schedule=schedule,
            policy=policy,
            height=100,
            round=0,
            started_at_ms=10_000,
        )
        changed = DeterministicLeaderSchedule(
            chain_id=20260723,
            validator_set_hash="0x" + ("33" * 32),
            validators=_validators(),
        )

        with self.assertRaisesRegex(ConsensusRoundError, "identity"):
            advance_round(
                state,
                schedule=changed,
                policy=policy,
                started_at_ms=state.deadline_ms,
            )

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = self._schedule().as_evidence()

        self.assertEqual(evidence["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
