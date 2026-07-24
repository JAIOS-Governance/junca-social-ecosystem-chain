"""Persistent finality-aware bridge event index with fail-closed reorg handling."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class EventIndexerError(ValueError):
    pass


@dataclass(frozen=True)
class IndexedBlock:
    network: str
    number: int
    block_hash: str
    parent_hash: str
    finalized: bool


class BridgeEventIndexer:
    def __init__(self, path: str | Path, network: str, confirmations: int) -> None:
        if not network or confirmations < 1:
            raise EventIndexerError("invalid indexer configuration")
        self.network = network
        self.confirmations = confirmations
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS blocks(
              network TEXT NOT NULL, number INTEGER NOT NULL, block_hash TEXT NOT NULL,
              parent_hash TEXT NOT NULL, finalized INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(network, number), UNIQUE(network, block_hash)
            );
            CREATE TABLE IF NOT EXISTS events(
              network TEXT NOT NULL, transaction_hash TEXT NOT NULL,
              log_index INTEGER NOT NULL, block_number INTEGER NOT NULL,
              event_name TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY(network, transaction_hash, log_index),
              FOREIGN KEY(network, block_number) REFERENCES blocks(network, number)
                ON DELETE CASCADE
            );
            """
        )
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def ingest_block(
        self,
        *,
        number: int,
        block_hash: str,
        parent_hash: str,
        events: Sequence[Mapping[str, Any]],
        observed_head: int,
    ) -> IndexedBlock:
        self._validate_hash(block_hash)
        self._validate_hash(parent_hash)
        if number < 0 or observed_head < number:
            raise EventIndexerError("invalid block height")
        previous = self.connection.execute(
            "SELECT * FROM blocks WHERE network=? AND number=?",
            (self.network, number - 1),
        ).fetchone()
        if number > 0 and previous is not None and previous["block_hash"] != parent_hash:
            if previous["finalized"]:
                raise EventIndexerError("reorg crosses finalized checkpoint")
            self._rollback_from(number - 1)
        existing = self.connection.execute(
            "SELECT block_hash FROM blocks WHERE network=? AND number=?",
            (self.network, number),
        ).fetchone()
        if existing is not None:
            if existing["block_hash"] == block_hash:
                return self.get_block(number)
            current = self.get_block(number)
            if current.finalized:
                raise EventIndexerError("cannot replace finalized block")
            self._rollback_from(number)

        finalized_through = observed_head - self.confirmations
        with self.connection:
            self.connection.execute(
                "INSERT INTO blocks(network,number,block_hash,parent_hash,finalized) VALUES(?,?,?,?,?)",
                (self.network, number, block_hash, parent_hash, int(number <= finalized_through)),
            )
            for event in events:
                transaction_hash = str(event.get("transaction_hash", ""))
                self._validate_hash(transaction_hash)
                log_index = event.get("log_index")
                event_name = str(event.get("event_name", ""))
                if not isinstance(log_index, int) or log_index < 0 or not event_name:
                    raise EventIndexerError("invalid event identity")
                payload = json.dumps(event.get("payload", {}), sort_keys=True, separators=(",", ":"))
                self.connection.execute(
                    """
                    INSERT INTO events(network,transaction_hash,log_index,block_number,event_name,payload)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (self.network, transaction_hash, log_index, number, event_name, payload),
                )
            self.connection.execute(
                "UPDATE blocks SET finalized=1 WHERE network=? AND number<=?",
                (self.network, finalized_through),
            )
        return self.get_block(number)

    def get_block(self, number: int) -> IndexedBlock:
        row = self.connection.execute(
            "SELECT * FROM blocks WHERE network=? AND number=?", (self.network, number)
        ).fetchone()
        if row is None:
            raise EventIndexerError("unknown block")
        return IndexedBlock(
            network=row["network"],
            number=row["number"],
            block_hash=row["block_hash"],
            parent_hash=row["parent_hash"],
            finalized=bool(row["finalized"]),
        )

    def finalized_events(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT e.* FROM events e JOIN blocks b
              ON b.network=e.network AND b.number=e.block_number
            WHERE e.network=? AND b.finalized=1
            ORDER BY e.block_number,e.log_index
            """,
            (self.network,),
        ).fetchall()
        return [
            {
                "transaction_hash": row["transaction_hash"],
                "log_index": row["log_index"],
                "block_number": row["block_number"],
                "event_name": row["event_name"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    def _rollback_from(self, number: int) -> None:
        finalized = self.connection.execute(
            "SELECT 1 FROM blocks WHERE network=? AND number>=? AND finalized=1 LIMIT 1",
            (self.network, number),
        ).fetchone()
        if finalized:
            raise EventIndexerError("reorg crosses finalized checkpoint")
        with self.connection:
            self.connection.execute(
                "DELETE FROM blocks WHERE network=? AND number>=?", (self.network, number)
            )

    @staticmethod
    def _validate_hash(value: str) -> None:
        stripped = value[2:] if value.startswith("0x") else value
        if len(stripped) != 64:
            raise EventIndexerError("invalid hash length")
        try:
            int(stripped, 16)
        except ValueError as exc:
            raise EventIndexerError("invalid hash encoding") from exc
