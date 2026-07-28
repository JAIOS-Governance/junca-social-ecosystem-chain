"""Persistent finalized-only block, transaction and address index candidate.

The indexer accepts only finalized block records with contiguous parent hashes.
It is independent from the live runtime and does not fabricate history.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "junca-mainnet-indexer/v1"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


class MainnetIndexerError(ValueError):
    """Raised when finalized history violates index integrity."""


@dataclass(frozen=True)
class FinalizedTransactionRecord:
    transaction_hash: str
    sender: str
    recipient: str
    nonce: int
    status: str
    event_count: int = 0

    def __post_init__(self) -> None:
        _hash(self.transaction_hash, "transaction_hash")
        _address(self.sender, "sender")
        _address(self.recipient, "recipient")
        if isinstance(self.nonce, bool) or not isinstance(self.nonce, int) or self.nonce < 0:
            raise MainnetIndexerError("nonce must be non-negative")
        if self.status not in {"SUCCESS", "FAILED"}:
            raise MainnetIndexerError("transaction status is invalid")
        if isinstance(self.event_count, bool) or not isinstance(self.event_count, int) or self.event_count < 0:
            raise MainnetIndexerError("event_count must be non-negative")


class FinalizedHistoryIndex:
    def __init__(self, path: str | Path, *, chain_id: int) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise MainnetIndexerError("chain_id must be positive")
        self.chain_id = chain_id
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS blocks(
              height INTEGER PRIMARY KEY,
              block_hash TEXT NOT NULL UNIQUE,
              parent_hash TEXT NOT NULL,
              timestamp INTEGER NOT NULL,
              state_root TEXT NOT NULL,
              certificate_hash TEXT NOT NULL,
              transaction_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions(
              transaction_hash TEXT PRIMARY KEY,
              block_height INTEGER NOT NULL,
              transaction_index INTEGER NOT NULL,
              sender TEXT NOT NULL,
              recipient TEXT NOT NULL,
              nonce INTEGER NOT NULL,
              status TEXT NOT NULL,
              event_count INTEGER NOT NULL,
              UNIQUE(block_height, transaction_index),
              FOREIGN KEY(block_height) REFERENCES blocks(height)
            );
            CREATE INDEX IF NOT EXISTS transactions_sender
              ON transactions(sender, block_height DESC, transaction_index DESC);
            CREATE INDEX IF NOT EXISTS transactions_recipient
              ON transactions(recipient, block_height DESC, transaction_index DESC);
            """
        )
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='chain_id'"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata(key,value) VALUES('chain_id',?)",
                (str(chain_id),),
            )
            self.connection.commit()
        elif row["value"] != str(chain_id):
            self.connection.close()
            raise MainnetIndexerError("index is bound to a different chain_id")

    def close(self) -> None:
        self.connection.close()

    def ingest_finalized_block(
        self,
        *,
        height: int,
        block_hash: str,
        parent_hash: str,
        timestamp: int,
        state_root: str,
        certificate_hash: str,
        transactions: Iterable[FinalizedTransactionRecord],
    ) -> None:
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise MainnetIndexerError("height must be non-negative")
        for field, value in (
            ("block_hash", block_hash),
            ("parent_hash", parent_hash),
            ("state_root", state_root),
            ("certificate_hash", certificate_hash),
        ):
            _hash(value, field)
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise MainnetIndexerError("timestamp must be positive")
        records = tuple(transactions)
        if any(not isinstance(item, FinalizedTransactionRecord) for item in records):
            raise MainnetIndexerError("transactions contain an invalid record")
        hashes = [item.transaction_hash.lower() for item in records]
        if len(hashes) != len(set(hashes)):
            raise MainnetIndexerError("block contains duplicate transactions")

        with self.connection:
            existing = self.connection.execute(
                "SELECT block_hash FROM blocks WHERE height=?", (height,)
            ).fetchone()
            if existing is not None:
                if existing["block_hash"] == block_hash.lower():
                    return
                raise MainnetIndexerError("cannot replace finalized block")
            if height == 0:
                if parent_hash.lower() != "0x" + ("0" * 64):
                    raise MainnetIndexerError("genesis parent hash is invalid")
            else:
                parent = self.connection.execute(
                    "SELECT block_hash FROM blocks WHERE height=?", (height - 1,)
                ).fetchone()
                if parent is None or parent["block_hash"] != parent_hash.lower():
                    raise MainnetIndexerError("finalized block history is not contiguous")
            self.connection.execute(
                """
                INSERT INTO blocks(
                  height,block_hash,parent_hash,timestamp,state_root,
                  certificate_hash,transaction_count
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    height,
                    block_hash.lower(),
                    parent_hash.lower(),
                    timestamp,
                    state_root.lower(),
                    certificate_hash.lower(),
                    len(records),
                ),
            )
            for index, record in enumerate(records):
                self.connection.execute(
                    """
                    INSERT INTO transactions(
                      transaction_hash,block_height,transaction_index,sender,
                      recipient,nonce,status,event_count
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        record.transaction_hash.lower(),
                        height,
                        index,
                        record.sender.lower(),
                        record.recipient.lower(),
                        record.nonce,
                        record.status,
                        record.event_count,
                    ),
                )

    def block(self, height: int) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM blocks WHERE height=?", (height,)
        ).fetchone()
        if row is None:
            raise MainnetIndexerError("unknown finalized block")
        return dict(row)

    def transaction(self, transaction_hash: str) -> dict[str, Any]:
        normalized = _hash(transaction_hash, "transaction_hash")
        row = self.connection.execute(
            "SELECT * FROM transactions WHERE transaction_hash=?", (normalized,)
        ).fetchone()
        if row is None:
            raise MainnetIndexerError("unknown finalized transaction")
        return dict(row)

    def address_history(
        self,
        address: str,
        *,
        limit: int = 50,
        before_height: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = _address(address, "address")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise MainnetIndexerError("limit must be between 1 and 200")
        upper = (1 << 63) - 1 if before_height is None else before_height
        if isinstance(upper, bool) or not isinstance(upper, int) or upper < 0:
            raise MainnetIndexerError("before_height must be non-negative")
        rows = self.connection.execute(
            """
            SELECT * FROM transactions
            WHERE (sender=? OR recipient=?) AND block_height < ?
            ORDER BY block_height DESC, transaction_index DESC
            LIMIT ?
            """,
            (normalized, normalized, upper, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def checkpoint(self) -> dict[str, Any]:
        head = self.connection.execute(
            "SELECT * FROM blocks ORDER BY height DESC LIMIT 1"
        ).fetchone()
        return {
            "schema_version": SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "head": None if head is None else dict(head),
            "finalized_only": True,
            "synthetic_history": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise MainnetIndexerError(f"{field} must be a 32-byte hash")
    return value.lower()


def _address(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value.lower()):
        raise MainnetIndexerError(f"{field} must be a 20-byte address")
    return value.lower()
