from __future__ import annotations

import threading
import unittest

from jaios.social_ecosystem_chain.validator_liveness import (
    RecoveringBoundedFinalityLoop,
)
from jaios.social_ecosystem_chain.validator_node import ValidatorNodeError


class _Store:
    def __init__(self) -> None:
        self.head_height = 0
        self.head_timestamp: int | None = None

    def head(self):
        return type("Head", (), {"height": self.head_height})()

    def block_timestamp(self, height: int) -> int | None:
        self.last_read_height = height
        return self.head_timestamp


class _State:
    def __init__(self, pending_timestamp: int | None) -> None:
        self.store = _Store()
        self.consensus_lock = threading.RLock()
        self.automatic_finality_last_attempted_slot = None
        self.automatic_finality_last_successful_slot = None
        self.automatic_finality_last_attempted_height = None
        self.automatic_finality_last_successful_height = None
        self.timestamps: list[int | None] = []
        pending = (
            None
            if pending_timestamp is None
            else type(
                "Proposal",
                (),
                {"block_timestamp": pending_timestamp},
            )()
        )
        runtime = type("Runtime", (), {"pending_proposal": pending})()
        self.consensus = type("Consensus", (), {"runtime": runtime})()

    def broadcast_vote(self, *, block_timestamp=None):
        self.timestamps.append(block_timestamp)
        return {"status": "BROADCAST", "height": self.store.head_height + 1}


class RecoveringBoundedFinalityLoopTests(unittest.TestCase):
    def test_retries_exact_stale_proposal_once_per_later_slot(self) -> None:
        state = _State(1_800_000_030)
        loop = RecoveringBoundedFinalityLoop(
            state,
            interval_seconds=30,
            epoch_seconds=1_800_000_000,
        )

        self.assertTrue(loop.run_once(1_800_000_060))
        self.assertFalse(loop.run_once(1_800_000_089))
        self.assertTrue(loop.run_once(1_800_000_090))

        self.assertEqual(
            state.timestamps,
            [1_800_000_030, 1_800_000_030],
        )
        self.assertEqual(state.automatic_finality_last_attempted_slot, 3)
        self.assertEqual(state.automatic_finality_last_successful_slot, 3)
        self.assertEqual(state.automatic_finality_last_attempted_height, 1)
        self.assertEqual(state.automatic_finality_last_successful_height, 1)

    def test_new_proposal_uses_current_canonical_slot(self) -> None:
        state = _State(None)
        loop = RecoveringBoundedFinalityLoop(
            state,
            interval_seconds=30,
            epoch_seconds=1_800_000_000,
        )

        self.assertTrue(loop.run_once(1_800_000_060))
        self.assertEqual(state.timestamps, [1_800_000_060])

    def test_future_pending_timestamp_fails_closed(self) -> None:
        state = _State(1_800_000_090)
        loop = RecoveringBoundedFinalityLoop(
            state,
            interval_seconds=30,
            epoch_seconds=1_800_000_000,
        )

        with self.assertRaisesRegex(
            ValidatorNodeError,
            "ahead of the canonical slot",
        ):
            loop.run_once(1_800_000_060)
        self.assertEqual(state.timestamps, [])


if __name__ == "__main__":
    unittest.main()
