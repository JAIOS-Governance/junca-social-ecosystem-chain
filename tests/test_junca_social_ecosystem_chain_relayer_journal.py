import tempfile
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.relayer_journal import RelayerJournal, RelayerJournalError


def payload(nonce=1, transaction="b" * 64, digest="a" * 64):
    return {
        "message_digest": digest,
        "source_network": "junca-public-testnet",
        "source_transaction": transaction,
        "source_nonce": nonce,
    }


class RelayerJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.journal = RelayerJournal(Path(self.directory.name) / "journal.sqlite3", max_attempts=2)

    def tearDown(self):
        self.journal.close()
        self.directory.cleanup()

    def test_enqueue_lease_acknowledge_and_audit(self):
        item = self.journal.enqueue(payload(), now=10)
        self.assertEqual(item.state, "PENDING")
        leased = self.journal.lease("worker-a", now=11)
        self.assertEqual(leased.state, "LEASED")
        executed = self.journal.acknowledge("a" * 64, "worker-a", "c" * 64, now=12)
        self.assertEqual(executed.state, "EXECUTED")
        self.assertTrue(self.journal.verify_audit_chain())

    def test_replay_identities_are_rejected(self):
        self.journal.enqueue(payload(), now=10)
        for duplicate in (
            payload(digest="d" * 64),
            payload(nonce=2, digest="e" * 64),
        ):
            with self.assertRaises(RelayerJournalError):
                self.journal.enqueue(duplicate, now=11)

    def test_expired_lease_is_recovered(self):
        self.journal.enqueue(payload(), now=10)
        self.journal.lease("worker-a", now=11, lease_seconds=5)
        recovered = self.journal.lease("worker-b", now=16)
        self.assertEqual(recovered.lease_owner, "worker-b")
        self.assertEqual(recovered.attempts, 2)

    def test_failure_retries_then_dead_letters(self):
        self.journal.enqueue(payload(), now=10)
        first = self.journal.lease("worker-a", now=11)
        self.assertEqual(self.journal.fail(first.message_digest, "worker-a", "rpc timeout", now=12).state, "PENDING")
        second = self.journal.lease("worker-b", now=13)
        self.assertEqual(self.journal.fail(second.message_digest, "worker-b", "reverted", now=14).state, "DEAD_LETTER")
        self.assertTrue(self.journal.verify_audit_chain())

    def test_wrong_owner_cannot_acknowledge(self):
        self.journal.enqueue(payload(), now=10)
        self.journal.lease("worker-a", now=11)
        with self.assertRaises(RelayerJournalError):
            self.journal.acknowledge("a" * 64, "worker-b", "c" * 64, now=12)


if __name__ == "__main__":
    unittest.main()
