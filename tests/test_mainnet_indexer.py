from __future__ import annotations

import tempfile
import unittest

from jaios.social_ecosystem_chain.mainnet_indexer import (
    FinalizedHistoryIndex,
    FinalizedTransactionRecord,
    MainnetIndexerError,
)


ZERO = "0x" + ("00" * 32)
BLOCK_A = "0x" + ("11" * 32)
BLOCK_B = "0x" + ("22" * 32)
STATE_A = "0x" + ("33" * 32)
STATE_B = "0x" + ("44" * 32)
CERT_A = "0x" + ("55" * 32)
CERT_B = "0x" + ("66" * 32)
TX_A = "0x" + ("77" * 32)
TX_B = "0x" + ("88" * 32)
ALICE = "0x" + ("aa" * 20)
BOB = "0x" + ("bb" * 20)


class MainnetIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.index = FinalizedHistoryIndex(
            f"{self.temp.name}/index.sqlite",
            chain_id=20260723,
        )

    def tearDown(self) -> None:
        self.index.close()
        self.temp.cleanup()

    def test_ingests_contiguous_finalized_history(self) -> None:
        self.index.ingest_finalized_block(
            height=0,
            block_hash=BLOCK_A,
            parent_hash=ZERO,
            timestamp=1_800_000_000,
            state_root=STATE_A,
            certificate_hash=CERT_A,
            transactions=(),
        )
        self.index.ingest_finalized_block(
            height=1,
            block_hash=BLOCK_B,
            parent_hash=BLOCK_A,
            timestamp=1_800_000_030,
            state_root=STATE_B,
            certificate_hash=CERT_B,
            transactions=(
                FinalizedTransactionRecord(
                    transaction_hash=TX_A,
                    sender=ALICE,
                    recipient=BOB,
                    nonce=0,
                    status="SUCCESS",
                ),
            ),
        )

        self.assertEqual(self.index.block(1)["block_hash"], BLOCK_B)
        self.assertEqual(self.index.transaction(TX_A)["block_height"], 1)
        self.assertEqual(self.index.address_history(ALICE)[0]["transaction_hash"], TX_A)

    def test_finalized_block_replacement_is_rejected(self) -> None:
        self.index.ingest_finalized_block(
            height=0,
            block_hash=BLOCK_A,
            parent_hash=ZERO,
            timestamp=1_800_000_000,
            state_root=STATE_A,
            certificate_hash=CERT_A,
            transactions=(),
        )

        with self.assertRaisesRegex(MainnetIndexerError, "replace finalized"):
            self.index.ingest_finalized_block(
                height=0,
                block_hash=BLOCK_B,
                parent_hash=ZERO,
                timestamp=1_800_000_001,
                state_root=STATE_B,
                certificate_hash=CERT_B,
                transactions=(),
            )

    def test_gap_and_parent_divergence_fail_closed(self) -> None:
        with self.assertRaisesRegex(MainnetIndexerError, "contiguous"):
            self.index.ingest_finalized_block(
                height=1,
                block_hash=BLOCK_B,
                parent_hash=BLOCK_A,
                timestamp=1_800_000_030,
                state_root=STATE_B,
                certificate_hash=CERT_B,
                transactions=(),
            )

    def test_duplicate_transaction_in_block_is_rejected(self) -> None:
        record = FinalizedTransactionRecord(
            transaction_hash=TX_B,
            sender=ALICE,
            recipient=BOB,
            nonce=0,
            status="SUCCESS",
        )
        with self.assertRaisesRegex(MainnetIndexerError, "duplicate"):
            self.index.ingest_finalized_block(
                height=0,
                block_hash=BLOCK_A,
                parent_hash=ZERO,
                timestamp=1_800_000_000,
                state_root=STATE_A,
                certificate_hash=CERT_A,
                transactions=(record, record),
            )

    def test_checkpoint_never_fabricates_history(self) -> None:
        checkpoint = self.index.checkpoint()

        self.assertIsNone(checkpoint["head"])
        self.assertTrue(checkpoint["finalized_only"])
        self.assertFalse(checkpoint["synthetic_history"])
        self.assertFalse(checkpoint["mainnet_changed"])


if __name__ == "__main__":
    unittest.main()
