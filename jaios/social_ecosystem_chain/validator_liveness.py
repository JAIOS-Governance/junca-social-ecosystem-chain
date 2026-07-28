"""Liveness-preserving automatic finality loop for Mainnet candidates.

A validator may retain a deterministic proposal when quorum delivery fails in
its original wall-clock slot. Dropping that proposal would permit the same
validator to sign a different block at the same height and round. Refusing to
retry it, however, permanently stalls the node. This loop retries the exact
pending proposal, timestamp and signing-journal entry at most once per later
wall-clock slot until quorum finalizes it.

The current Public Testnet is the verification environment for this Mainnet
Candidate consensus-liveness primitive. This module does not activate Mainnet.
"""

from __future__ import annotations

from .validator_node import BoundedFinalityLoop, ValidatorNodeError


class RecoveringBoundedFinalityLoop(BoundedFinalityLoop):
    """Retry an exact stale proposal without creating an equivocation risk."""

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
                raise ValidatorNodeError(
                    "pending proposal timestamp is invalid"
                )
            if pending_timestamp > current_timestamp:
                raise ValidatorNodeError(
                    "pending proposal timestamp is ahead of the canonical slot"
                )

            # The attempted-slot marker is the replay boundary. A transport may
            # partially deliver before raising, so success cannot be required to
            # suppress a second broadcast in the same canonical slot.
            if self.state.automatic_finality_last_attempted_slot == current_slot:
                return False

            next_height = head.height + 1
            self.state.automatic_finality_last_attempted_slot = current_slot
            self.state.automatic_finality_last_attempted_height = next_height
            self.state.broadcast_vote(block_timestamp=pending_timestamp)
            self.state.automatic_finality_last_successful_slot = current_slot
            self.state.automatic_finality_last_successful_height = next_height
            return True
