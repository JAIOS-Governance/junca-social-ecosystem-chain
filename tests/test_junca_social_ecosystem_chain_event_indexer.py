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


if __name__ == "__main__":
    unittest.main()
