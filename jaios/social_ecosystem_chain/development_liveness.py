"""Development-only stale proposal recovery adapter.

This module mirrors the liveness interface implemented canonically by PR #217 so
the isolated three-validator environment can verify restart recovery before that
Mainnet Candidate change is integrated. It is activated only by the local Docker
entrypoint and must not replace `validator_liveness.py` or the production-installed
validator entrypoint.

The adapter retries the exact pending proposal, block timestamp and persistent
signing-journal choice at most once per later canonical slot. It never creates a
replacement proposal, changes the round, lowers quorum or activates Mainnet.
"""

from __future__ import annotations

from .validator_node import BoundedFinalityLoop, ValidatorNodeError


class DevelopmentRecoveringBoundedFinalityLoop(BoundedFinalityLoop):
    """Retry one exact stale development proposal without equivocation risk."""

    def run_once(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        if current < self.epoch_seconds:
            return False
        current_slot = int(
            (current - self.epoch_seconds) // self.interval_seconds
        )
        if current_slot <= 0:
            return False
        current_timestamp = self.canonical_timestamp(current_slot)

        with self.state.consensus_lock:
            head = self.state.store.head()
            head_timestamp = self.state.store.block_timestamp(head.height)
            if head_timestamp is not None and head_timestamp >= current_timestamp:
                return False

            pending = (
                self.state.consensus.runtime.pending_proposal
                if self.state.consensus is not None
                else None
            )
            if pending is None or pending.block_timestamp == current_timestamp:
                return super().run_once(current)

            pending_timestamp = pending.block_timestamp
            if (
                isinstance(pending_timestamp, bool)
                or not isinstance(pending_timestamp, int)
                or pending_timestamp <= 0
            ):
                raise ValidatorNodeError("pending proposal timestamp is invalid")
            if pending_timestamp > current_timestamp:
                raise ValidatorNodeError(
                    "pending proposal timestamp is ahead of the canonical slot"
                )

            # A partial transport delivery may raise after some peers receive the
            # vote. The attempted-slot marker therefore suppresses any same-slot
            # replay, while a later slot retries the identical signed choice.
            if self.state.automatic_finality_last_attempted_slot == current_slot:
                return False

            next_height = head.height + 1
            self.state.automatic_finality_last_attempted_slot = current_slot
            self.state.automatic_finality_last_attempted_height = next_height
            self.state.broadcast_vote(block_timestamp=pending_timestamp)
            self.state.automatic_finality_last_successful_slot = current_slot
            self.state.automatic_finality_last_successful_height = next_height
            return True
