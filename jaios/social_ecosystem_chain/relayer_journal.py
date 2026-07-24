"""Crash-recoverable SQLite bridge relayer queue with chained audit evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class RelayerJournalError(ValueError):
    pass


@dataclass(frozen=True)
class QueueItem:
    message_digest: str
    state: str
    attempts: int
    lease_owner: str | None
    lease_expires_at: int | None
    payload: Mapping[str, Any]


class RelayerJournal:
    STATES = {"PENDING", "LEASED", "EXECUTED", "DEAD_LETTER"}

    def __init__(self, path: str | Path, *, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            raise RelayerJournalError("max_attempts must be positive")
        self.path = str(path)
        self.max_attempts = max_attempts
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bridge_queue (
                message_digest TEXT PRIMARY KEY,
                source_network TEXT NOT NULL,
                source_transaction TEXT NOT NULL UNIQUE,
                source_nonce INTEGER NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('PENDING','LEASED','EXECUTED','DEAD_LETTER')),
                attempts INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                lease_expires_at INTEGER,
                execution_transaction TEXT,
                last_error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(source_network, source_nonce)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message_digest TEXT NOT NULL,
                details TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL
            );
            """
        )
        self.connection.commit()

    def enqueue(self, payload: Mapping[str, Any], *, now: int | None = None) -> QueueItem:
        timestamp = int(time.time()) if now is None else now
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = str(payload.get("message_digest", ""))
        source_network = str(payload.get("source_network", ""))
        source_transaction = str(payload.get("source_transaction", ""))
        source_nonce = payload.get("source_nonce")
        if len(digest) != 64 or not source_network or len(source_transaction) != 64:
            raise RelayerJournalError("invalid queue identity")
        if not isinstance(source_nonce, int) or source_nonce < 0:
            raise RelayerJournalError("invalid source nonce")
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO bridge_queue(
                        message_digest, source_network, source_transaction,
                        source_nonce, payload, state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                    """,
                    (digest, source_network, source_transaction, source_nonce, canonical, timestamp, timestamp),
                )
                self._audit("ENQUEUED", digest, {"source_network": source_network}, timestamp)
        except sqlite3.IntegrityError as exc:
            raise RelayerJournalError("replay or duplicate queue identity") from exc
        return self.get(digest)

    def lease(self, owner: str, *, now: int | None = None, lease_seconds: int = 60) -> QueueItem | None:
        if not owner or lease_seconds < 1:
            raise RelayerJournalError("invalid lease")
        timestamp = int(time.time()) if now is None else now
        with self.connection:
            row = self.connection.execute(
                """
                SELECT message_digest FROM bridge_queue
                WHERE state = 'PENDING'
                   OR (state = 'LEASED' AND lease_expires_at <= ?)
                ORDER BY created_at, message_digest LIMIT 1
                """,
                (timestamp,),
            ).fetchone()
            if row is None:
                return None
            digest = row["message_digest"]
            updated = self.connection.execute(
                """
                UPDATE bridge_queue
                SET state='LEASED', attempts=attempts+1, lease_owner=?,
                    lease_expires_at=?, updated_at=?
                WHERE message_digest=?
                  AND (state='PENDING' OR (state='LEASED' AND lease_expires_at <= ?))
                """,
                (owner, timestamp + lease_seconds, timestamp, digest, timestamp),
            )
            if updated.rowcount != 1:
                return None
            self._audit("LEASED", digest, {"owner": owner}, timestamp)
        return self.get(digest)

    def acknowledge(
        self,
        digest: str,
        owner: str,
        execution_transaction: str,
        *,
        now: int | None = None,
    ) -> QueueItem:
        timestamp = int(time.time()) if now is None else now
        if len(execution_transaction) != 64:
            raise RelayerJournalError("invalid execution transaction")
        with self.connection:
            updated = self.connection.execute(
                """
                UPDATE bridge_queue SET state='EXECUTED',
                    execution_transaction=?, lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE message_digest=? AND state='LEASED' AND lease_owner=?
                """,
                (execution_transaction, timestamp, digest, owner),
            )
            if updated.rowcount != 1:
                raise RelayerJournalError("lease ownership mismatch")
            self._audit("EXECUTED", digest, {"execution_transaction": execution_transaction}, timestamp)
        return self.get(digest)

    def fail(self, digest: str, owner: str, error: str, *, now: int | None = None) -> QueueItem:
        timestamp = int(time.time()) if now is None else now
        if not error.strip():
            raise RelayerJournalError("failure reason is required")
        with self.connection:
            row = self.connection.execute(
                "SELECT attempts FROM bridge_queue WHERE message_digest=? AND state='LEASED' AND lease_owner=?",
                (digest, owner),
            ).fetchone()
            if row is None:
                raise RelayerJournalError("lease ownership mismatch")
            next_state = "DEAD_LETTER" if row["attempts"] >= self.max_attempts else "PENDING"
            self.connection.execute(
                """
                UPDATE bridge_queue SET state=?, last_error=?,
                    lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE message_digest=?
                """,
                (next_state, error.strip()[:1000], timestamp, digest),
            )
            self._audit(next_state, digest, {"error": error.strip()[:1000]}, timestamp)
        return self.get(digest)

    def get(self, digest: str) -> QueueItem:
        row = self.connection.execute(
            "SELECT * FROM bridge_queue WHERE message_digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise RelayerJournalError("unknown message")
        return QueueItem(
            message_digest=row["message_digest"],
            state=row["state"],
            attempts=row["attempts"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            payload=json.loads(row["payload"]),
        )

    def verify_audit_chain(self) -> bool:
        previous = "0" * 64
        rows = self.connection.execute("SELECT * FROM audit_log ORDER BY sequence").fetchall()
        for row in rows:
            expected = self._entry_hash(
                previous,
                row["event_type"],
                row["message_digest"],
                row["details"],
                row["created_at"],
            )
            if row["previous_hash"] != previous or row["entry_hash"] != expected:
                return False
            previous = row["entry_hash"]
        return True

    def _audit(self, event: str, digest: str, details: Mapping[str, Any], timestamp: int) -> None:
        previous_row = self.connection.execute(
            "SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = previous_row["entry_hash"] if previous_row else "0" * 64
        canonical = json.dumps(details, sort_keys=True, separators=(",", ":"))
        entry_hash = self._entry_hash(previous, event, digest, canonical, timestamp)
        self.connection.execute(
            """
            INSERT INTO audit_log(event_type,message_digest,details,previous_hash,entry_hash,created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (event, digest, canonical, previous, entry_hash, timestamp),
        )

    @staticmethod
    def _entry_hash(previous: str, event: str, digest: str, details: str, timestamp: int) -> str:
        payload = f"{previous}\0{event}\0{digest}\0{details}\0{timestamp}".encode()
        return hashlib.sha256(payload).hexdigest()
