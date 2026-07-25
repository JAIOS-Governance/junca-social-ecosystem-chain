import tempfile
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.event_indexer import BridgeEventIndexer, EventIndexerError


def h(character):
    return character * 64


class EventIndexerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.indexer = BridgeEventIndexer(Path(self.directory.name) / "events.db", "bsc-testnet", 2)

    def tearDown(self):
        self.indexer.close()
        self.directory.cleanup()

    def test_finality_and_events(self):
        self.indexer.ingest_block(number=0, block_hash=h("a"), parent_hash=h("0"), events=[], observed_head=0)
        self.indexer.ingest_block(
            number=1, block_hash=h("b"), parent_hash=h("a"),
            events=[{"transaction_hash": h("c"), "log_index": 0, "event_name": "Locked", "payload": {"value": 1}}],
            observed_head=3,
        )
        self.assertTrue(self.indexer.get_block(1).finalized)
        self.assertEqual(len(self.indexer.finalized_events()), 1)

    def test_unfinalized_reorg_rolls_back(self):
        self.indexer.ingest_block(number=0, block_hash=h("a"), parent_hash=h("0"), events=[], observed_head=0)
        self.indexer.ingest_block(number=1, block_hash=h("b"), parent_hash=h("a"), events=[], observed_head=1)
        replacement = self.indexer.ingest_block(number=1, block_hash=h("c"), parent_hash=h("a"), events=[], observed_head=1)
        self.assertEqual(replacement.block_hash, h("c"))

    def test_finalized_reorg_fails_closed(self):
        self.indexer.ingest_block(number=0, block_hash=h("a"), parent_hash=h("0"), events=[], observed_head=3)
        with self.assertRaises(EventIndexerError):
            self.indexer.ingest_block(number=0, block_hash=h("b"), parent_hash=h("0"), events=[], observed_head=3)

    def test_duplicate_event_is_rejected(self):
        event = {"transaction_hash": h("c"), "log_index": 0, "event_name": "Locked", "payload": {}}
        self.indexer.ingest_block(number=0, block_hash=h("a"), parent_hash=h("0"), events=[event], observed_head=0)
        with self.assertRaises(Exception):
            self.indexer.ingest_block(number=1, block_hash=h("b"), parent_hash=h("a"), events=[event], observed_head=1)

    def test_invalid_replacement_is_atomic_and_preserves_canonical_chain(self):
        self.indexer.ingest_block(
            number=0,
            block_hash=h("a"),
            parent_hash=h("0"),
            events=[],
            observed_head=0,
        )
        self.indexer.ingest_block(
            number=1,
            block_hash=h("b"),
            parent_hash=h("a"),
            events=[{
                "transaction_hash": h("c"),
                "log_index": 0,
                "event_name": "Locked",
                "payload": {"value": 1},
            }],
            observed_head=1,
        )
        with self.assertRaisesRegex(EventIndexerError, "invalid event identity"):
            self.indexer.ingest_block(
                number=1,
                block_hash=h("d"),
                parent_hash=h("a"),
                events=[{
                    "transaction_hash": h("e"),
                    "log_index": -1,
                    "event_name": "Locked",
                    "payload": {},
                }],
                observed_head=1,
            )
        self.assertEqual(self.indexer.get_block(1).block_hash, h("b"))

    def test_gap_and_parent_mismatch_are_rejected_without_orphans(self):
        with self.assertRaisesRegex(EventIndexerError, "contiguous"):
            self.indexer.ingest_block(
                number=2,
                block_hash=h("c"),
                parent_hash=h("b"),
                events=[],
                observed_head=2,
            )
        self.indexer.ingest_block(
            number=0,
            block_hash=h("a"),
            parent_hash=h("0"),
            events=[],
            observed_head=0,
        )
        self.indexer.ingest_block(
            number=1,
            block_hash=h("b"),
            parent_hash=h("a"),
            events=[],
            observed_head=1,
        )
        with self.assertRaisesRegex(EventIndexerError, "ancestor"):
            self.indexer.ingest_block(
                number=2,
                block_hash=h("d"),
                parent_hash=h("c"),
                events=[],
                observed_head=2,
            )
        with self.assertRaisesRegex(EventIndexerError, "unknown block"):
            self.indexer.get_block(2)

    def test_duplicate_observation_advances_finality(self):
        self.indexer.ingest_block(
            number=0,
            block_hash=h("a"),
            parent_hash=h("0"),
            events=[],
            observed_head=0,
        )
        self.indexer.ingest_block(
            number=1,
            block_hash=h("b"),
            parent_hash=h("a"),
            events=[],
            observed_head=1,
        )
        self.assertFalse(self.indexer.get_block(1).finalized)
        duplicate = self.indexer.ingest_block(
            number=1,
            block_hash=h("b"),
            parent_hash=h("a"),
            events=[],
            observed_head=3,
        )
        self.assertTrue(duplicate.finalized)

    def test_confirmation_policy_is_persisted(self):
        path = Path(self.directory.name) / "policy.db"
        first = BridgeEventIndexer(path, "bsc-testnet", 2)
        first.close()
        with self.assertRaisesRegex(EventIndexerError, "policy"):
            BridgeEventIndexer(path, "bsc-testnet", 3)

    def test_genesis_parent_and_payload_canonicality_are_enforced(self):
        with self.assertRaisesRegex(EventIndexerError, "genesis parent"):
            self.indexer.ingest_block(
                number=0,
                block_hash=h("a"),
                parent_hash=h("1"),
                events=[],
                observed_head=0,
            )
        with self.assertRaisesRegex(EventIndexerError, "canonical JSON"):
            self.indexer.ingest_block(
                number=0,
                block_hash=h("a"),
                parent_hash=h("0"),
                events=[{
                    "transaction_hash": h("b"),
                    "log_index": 0,
                    "event_name": "Locked",
                    "payload": {"value": float("nan")},
                }],
                observed_head=0,
            )


if __name__ == "__main__":
    unittest.main()
