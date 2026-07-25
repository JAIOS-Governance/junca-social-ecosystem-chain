from __future__ import annotations

from dataclasses import replace
import unittest

from jaios.social_ecosystem_chain.consensus_sync import (
    ConsensusSyncError,
    FinalizedClaim,
    FinalizedForkChoice,
    SnapshotCatchup,
    build_snapshot_descriptor,
    evaluate_sync_acceptance,
)


CHAIN_ID = 20260723
GENESIS = "0x" + ("1" * 64)


def claim(peer: str, height: int, digit: str = "2") -> FinalizedClaim:
    return FinalizedClaim(
        peer_id=peer,
        chain_id=CHAIN_ID,
        genesis_hash=GENESIS,
        height=height,
        block_hash="0x" + (digit * 64),
        parent_hash=GENESIS,
        state_root="0x" + ("3" * 64),
        signed_power=3,
        total_power=3,
    )


class ConsensusSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.choice = FinalizedForkChoice(
            chain_id=CHAIN_ID,
            genesis_hash=GENESIS,
            expected_total_power=3,
        )

    def test_highest_certified_finalized_tip_wins(self) -> None:
        self.choice.observe(claim("peer-a", 10))
        head = self.choice.observe(
            replace(claim("peer-b", 11, "4"), parent_hash="0x" + ("2" * 64))
        )
        self.assertEqual(head.height, 11)
        self.assertEqual(head.peer_id, "peer-b")

    def test_conflicting_valid_finality_halts(self) -> None:
        self.choice.observe(claim("peer-a", 10, "2"))
        with self.assertRaisesRegex(ConsensusSyncError, "conflicting"):
            self.choice.observe(claim("peer-b", 10, "9"))
        self.assertTrue(self.choice.safety_halted)
        with self.assertRaisesRegex(ConsensusSyncError, "halted"):
            self.choice.observe(claim("peer-c", 11, "4"))

    def test_chain_genesis_and_power_mismatches_fault_peer(self) -> None:
        cases = [
            replace(claim("bad-chain", 1), chain_id=1),
            replace(claim("bad-genesis", 1), genesis_hash="0x" + ("9" * 64)),
            replace(claim("bad-power", 1), total_power=4, signed_power=3),
        ]
        for item in cases:
            with self.assertRaises(ConsensusSyncError):
                self.choice.observe(item)
            self.assertEqual(self.choice.discipline(item.peer_id).faults, 1)

    def test_peer_finalized_regression_is_rejected(self) -> None:
        self.choice.observe(claim("peer-a", 5))
        with self.assertRaisesRegex(ConsensusSyncError, "regressed"):
            self.choice.observe(claim("peer-a", 4, "4"))

    def test_adjacent_finalized_parent_mismatch_faults_peer(self) -> None:
        self.choice.observe(claim("peer-a", 10, "2"))
        invalid = claim("peer-b", 11, "4")
        with self.assertRaisesRegex(ConsensusSyncError, "parent linkage"):
            self.choice.observe(invalid)
        self.assertEqual(self.choice.discipline("peer-b").faults, 1)

    def test_three_faults_quarantine_peer(self) -> None:
        for _ in range(3):
            state = self.choice.record_protocol_fault("peer-a")
        self.assertTrue(state.quarantined)
        with self.assertRaisesRegex(ConsensusSyncError, "quarantined"):
            self.choice.observe(claim("peer-a", 1))

    def test_below_strict_quorum_claim_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConsensusSyncError, "quorum"):
            FinalizedClaim(
                "peer-a",
                CHAIN_ID,
                GENESIS,
                1,
                "0x" + ("2" * 64),
                GENESIS,
                "0x" + ("3" * 64),
                2,
                3,
            )

    def test_snapshot_mode_threshold(self) -> None:
        catchup = SnapshotCatchup(chain_id=CHAIN_ID, threshold=100)
        self.assertEqual(catchup.choose_mode(local_height=0, remote_height=99), "BLOCK_RANGE")
        self.assertEqual(catchup.choose_mode(local_height=0, remote_height=100), "SNAPSHOT")

    def test_snapshot_is_bound_to_finalized_claim(self) -> None:
        chunks = [b"accounts-1", b"accounts-2"]
        descriptor = build_snapshot_descriptor(
            chain_id=CHAIN_ID,
            height=100,
            block_hash="0x" + ("2" * 64),
            state_root="0x" + ("3" * 64),
            chunks=chunks,
        )
        finalized = claim("peer-a", 100)
        result = SnapshotCatchup(chain_id=CHAIN_ID).verify(
            descriptor=descriptor,
            chunks=chunks,
            finalized=finalized,
        )
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.verified_bytes, sum(map(len, chunks)))

    def test_snapshot_chunk_tamper_is_rejected(self) -> None:
        chunks = [b"accounts-1"]
        descriptor = build_snapshot_descriptor(
            chain_id=CHAIN_ID,
            height=100,
            block_hash="0x" + ("2" * 64),
            state_root="0x" + ("3" * 64),
            chunks=chunks,
        )
        with self.assertRaisesRegex(ConsensusSyncError, "chunk digest"):
            SnapshotCatchup(chain_id=CHAIN_ID).verify(
                descriptor=descriptor,
                chunks=[b"tampered"],
                finalized=claim("peer-a", 100),
            )

    def test_snapshot_checkpoint_tamper_is_rejected(self) -> None:
        chunks = [b"accounts-1"]
        descriptor = build_snapshot_descriptor(
            chain_id=CHAIN_ID,
            height=100,
            block_hash="0x" + ("2" * 64),
            state_root="0x" + ("3" * 64),
            chunks=chunks,
        )
        with self.assertRaisesRegex(ConsensusSyncError, "checkpoint"):
            SnapshotCatchup(chain_id=CHAIN_ID).verify(
                descriptor=replace(descriptor, checkpoint_digest="0x" + ("9" * 64)),
                chunks=chunks,
                finalized=claim("peer-a", 100),
            )

    def test_snapshot_finality_mismatch_is_rejected(self) -> None:
        chunks = [b"accounts-1"]
        descriptor = build_snapshot_descriptor(
            chain_id=CHAIN_ID,
            height=100,
            block_hash="0x" + ("2" * 64),
            state_root="0x" + ("3" * 64),
            chunks=chunks,
        )
        with self.assertRaisesRegex(ConsensusSyncError, "finalized"):
            SnapshotCatchup(chain_id=CHAIN_ID).verify(
                descriptor=descriptor,
                chunks=chunks,
                finalized=claim("peer-a", 99),
            )

    def test_sync_acceptance_all_gates(self) -> None:
        self.choice.observe(claim("peer-a", 100))
        self.choice.observe(claim("peer-b", 100))
        result = evaluate_sync_acceptance(
            fork_choice=self.choice,
            local_height=99,
            minimum_peers=2,
            maximum_lag=2,
            restart_recovered=True,
            snapshot_verified=True,
        )
        self.assertEqual(result["state"], "ACCEPTED")

    def test_sync_acceptance_fails_closed(self) -> None:
        self.choice.observe(claim("peer-a", 100))
        result = evaluate_sync_acceptance(
            fork_choice=self.choice,
            local_height=90,
            minimum_peers=2,
            maximum_lag=2,
            restart_recovered=False,
            snapshot_verified=False,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("peer_quorum", result["failed_gates"])
        self.assertIn("within_finalized_lag", result["failed_gates"])

    def test_evidence_preserves_release_boundaries(self) -> None:
        self.choice.observe(claim("peer-a", 1))
        evidence = self.choice.evidence()
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
