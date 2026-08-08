"""SQLite WAL persistence for finalized Mainnet Candidate state snapshots.

The store persists only finalized state-machine snapshots and their exact
receipt/provenance binding. It is deliberately fail-closed and does not
activate Mainnet, issue or move assets, or enable a bridge.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

from .state_transition import (
    BlockReceipt,
    SCHEMA_VERSION as STATE_SCHEMA_VERSION,
    StateMachine,
    StateTransitionError,
)


STORE_SCHEMA_VERSION = "junca-finalized-state-store/v1"
_HASH = re.compile(r"^0x[0-9a-f]{64}$")


class FinalizedStateStoreError(ValueError):
    """Raised when persistent finalized-state evidence is not canonical."""


def _hash_bytes(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()


def _normalize_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value.lower()):
        raise FinalizedStateStoreError(f"{field} must be a 32-byte hash")
    return value.lower()


class FinalizedStateStore:
    """Transactional finalized snapshot ledger backed by SQLite WAL."""

    def __init__(
        self,
        path: str | Path,
        *,
        chain_id: int,
        genesis_hash: str,
        protocol_version: str,
    ) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise FinalizedStateStoreError("chain_id must be a positive integer")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise FinalizedStateStoreError("protocol_version is required")
        self.path = Path(path)
        self.chain_id = chain_id
        self.genesis_hash = _normalize_hash(genesis_hash, "genesis_hash")
        self.protocol_version = protocol_version
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finalized_snapshots (
                    height INTEGER PRIMARY KEY CHECK (height >= 0),
                    timestamp INTEGER NOT NULL CHECK (timestamp >= 0),
                    parent_state_root TEXT,
                    state_root TEXT NOT NULL,
                    block_receipt_hash TEXT,
                    block_receipt_json BLOB,
                    snapshot_digest TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    snapshot BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (
                        (
                            height = 0
                            AND parent_state_root IS NULL
                            AND block_receipt_hash IS NULL
                            AND block_receipt_json IS NULL
                        )
                        OR
                        (
                            height > 0
                            AND parent_state_root IS NOT NULL
                            AND block_receipt_hash IS NOT NULL
                            AND block_receipt_json IS NOT NULL
                        )
                    )
                );

                CREATE UNIQUE INDEX IF NOT EXISTS finalized_state_root_height
                ON finalized_snapshots(height, state_root);
                """
            )
            expected = {
                "store_schema_version": STORE_SCHEMA_VERSION,
                "state_schema_version": STATE_SCHEMA_VERSION,
                "chain_id": str(self.chain_id),
                "genesis_hash": self.genesis_hash,
                "protocol_version": self.protocol_version,
                "mainnet_changed": "false",
                "assets_moved": "false",
                "bridge_activated": "false",
            }
            existing = {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            if existing and existing != expected:
                raise FinalizedStateStoreError("state store metadata binding mismatch")
            if not existing:
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES(?, ?)",
                    sorted(expected.items()),
                )

    def initialize_genesis(self, machine: StateMachine) -> None:
        self._validate_machine_binding(machine)
        if machine.height != 0 or machine.timestamp != 0:
            raise FinalizedStateStoreError("genesis snapshot must be at height and timestamp zero")
        snapshot, snapshot_digest = self._snapshot_evidence(machine)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM finalized_snapshots WHERE height = 0"
            ).fetchone()
            if row is not None:
                self._assert_exact_snapshot(
                    row,
                    timestamp=0,
                    parent_state_root=None,
                    state_root=machine.state_root,
                    block_receipt_hash=None,
                    block_receipt_json=None,
                    snapshot_digest=snapshot_digest,
                    snapshot=snapshot,
                )
                return
            connection.execute(
                """
                INSERT INTO finalized_snapshots(
                    height, timestamp, parent_state_root, state_root,
                    block_receipt_hash, block_receipt_json,
                    snapshot_digest, snapshot_sha256, snapshot
                ) VALUES(0, 0, NULL, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    machine.state_root,
                    snapshot_digest,
                    _hash_bytes(snapshot),
                    snapshot,
                ),
            )

    def persist_finalized(
        self,
        machine: StateMachine,
        receipt: BlockReceipt,
    ) -> None:
        self._validate_machine_binding(machine)
        if not isinstance(receipt, BlockReceipt):
            raise FinalizedStateStoreError("BlockReceipt is required")
        if receipt.height != machine.height:
            raise FinalizedStateStoreError("receipt height does not match state machine")
        if receipt.timestamp != machine.timestamp:
            raise FinalizedStateStoreError("receipt timestamp does not match state machine")
        if receipt.state_root != machine.state_root:
            raise FinalizedStateStoreError("receipt state_root does not match state machine")
        if receipt.height <= 0:
            raise FinalizedStateStoreError("finalized block height must be positive")

        snapshot, snapshot_digest = self._snapshot_evidence(machine)
        receipt_hash = receipt.receipt_hash
        receipt_json = json.dumps(
            receipt.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with self._transaction() as connection:
            current = connection.execute(
                "SELECT * FROM finalized_snapshots WHERE height = ?",
                (receipt.height,),
            ).fetchone()
            if current is not None:
                self._assert_exact_snapshot(
                    current,
                    timestamp=receipt.timestamp,
                    parent_state_root=receipt.parent_state_root,
                    state_root=receipt.state_root,
                    block_receipt_hash=receipt_hash,
                    block_receipt_json=receipt_json,
                    snapshot_digest=snapshot_digest,
                    snapshot=snapshot,
                )
                return

            previous = connection.execute(
                "SELECT * FROM finalized_snapshots ORDER BY height DESC LIMIT 1"
            ).fetchone()
            if previous is None:
                raise FinalizedStateStoreError("genesis snapshot is not initialized")
            if receipt.height != previous["height"] + 1:
                raise FinalizedStateStoreError("finalized height must be contiguous")
            if receipt.parent_state_root != previous["state_root"]:
                raise FinalizedStateStoreError("parent state root does not match persisted head")
            if receipt.timestamp <= previous["timestamp"]:
                raise FinalizedStateStoreError("finalized timestamp must increase")

            connection.execute(
                """
                INSERT INTO finalized_snapshots(
                    height, timestamp, parent_state_root, state_root,
                    block_receipt_hash, block_receipt_json,
                    snapshot_digest, snapshot_sha256, snapshot
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.height,
                    receipt.timestamp,
                    receipt.parent_state_root,
                    receipt.state_root,
                    receipt_hash,
                    receipt_json,
                    snapshot_digest,
                    _hash_bytes(snapshot),
                    snapshot,
                ),
            )

    def load_latest(self) -> StateMachine:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM finalized_snapshots ORDER BY height DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise FinalizedStateStoreError("state store is empty")
        return self._restore_row(row)

    def load_height(self, height: int) -> StateMachine:
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise FinalizedStateStoreError("height is invalid")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM finalized_snapshots WHERE height = ?",
                (height,),
            ).fetchone()
        if row is None:
            raise FinalizedStateStoreError("finalized height is not persisted")
        return self._restore_row(row)

    def head_evidence(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM finalized_snapshots ORDER BY height DESC LIMIT 1"
            ).fetchone()
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM finalized_snapshots"
            ).fetchone()["count"]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "store_schema_version": STORE_SCHEMA_VERSION,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "protocol_version": self.protocol_version,
            "snapshot_count": count,
            "height": None if row is None else row["height"],
            "timestamp": None if row is None else row["timestamp"],
            "state_root": None if row is None else row["state_root"],
            "snapshot_digest": None if row is None else row["snapshot_digest"],
            "journal_mode": str(journal_mode).lower(),
            "integrity_check": integrity,
            "activation_status": "MAINNET_CANDIDATE_NOT_ACTIVATED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _snapshot_evidence(self, machine: StateMachine) -> tuple[bytes, str]:
        snapshot = machine.export_snapshot()
        try:
            envelope = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise FinalizedStateStoreError("state machine snapshot is invalid") from exc
        digest = _normalize_hash(envelope.get("snapshot_digest"), "snapshot_digest")
        return snapshot, digest

    def _restore_row(self, row: sqlite3.Row) -> StateMachine:
        snapshot = bytes(row["snapshot"])
        if _hash_bytes(snapshot) != row["snapshot_sha256"]:
            raise FinalizedStateStoreError("persisted snapshot byte hash mismatch")
        try:
            envelope = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise FinalizedStateStoreError("persisted snapshot envelope is invalid") from exc
        if envelope.get("snapshot_digest") != row["snapshot_digest"]:
            raise FinalizedStateStoreError("persisted snapshot digest binding mismatch")
        try:
            machine = StateMachine.restore_snapshot(snapshot)
        except StateTransitionError as exc:
            raise FinalizedStateStoreError("persisted snapshot validation failed") from exc
        self._verify_block_receipt_row(row)
        self._validate_machine_binding(machine)
        if machine.height != row["height"]:
            raise FinalizedStateStoreError("persisted snapshot height mismatch")
        if machine.timestamp != row["timestamp"]:
            raise FinalizedStateStoreError("persisted snapshot timestamp mismatch")
        if machine.state_root != row["state_root"]:
            raise FinalizedStateStoreError("persisted snapshot state root mismatch")
        return machine

    def _verify_block_receipt_row(self, row: sqlite3.Row) -> None:
        if row["height"] == 0:
            if row["block_receipt_hash"] is not None or row["block_receipt_json"] is not None:
                raise FinalizedStateStoreError("genesis receipt binding is invalid")
            return
        try:
            payload = json.loads(bytes(row["block_receipt_json"]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FinalizedStateStoreError("persisted block receipt is invalid") from exc
        expected_fields = {
            "height",
            "timestamp",
            "parent_state_root",
            "state_root",
            "transaction_hashes",
            "transaction_receipt_hashes",
            "resource_units_used",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise FinalizedStateStoreError("persisted block receipt payload is invalid")
        try:
            receipt = BlockReceipt(
                height=payload["height"],
                timestamp=payload["timestamp"],
                parent_state_root=payload["parent_state_root"],
                state_root=payload["state_root"],
                transaction_hashes=tuple(payload["transaction_hashes"]),
                transaction_receipt_hashes=tuple(payload["transaction_receipt_hashes"]),
                resource_units_used=payload["resource_units_used"],
            )
        except (TypeError, ValueError) as exc:
            raise FinalizedStateStoreError("persisted block receipt fields are invalid") from exc
        canonical = json.dumps(
            receipt.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if canonical != bytes(row["block_receipt_json"]):
            raise FinalizedStateStoreError("persisted block receipt encoding is not canonical")
        if receipt.receipt_hash != row["block_receipt_hash"]:
            raise FinalizedStateStoreError("persisted block receipt hash mismatch")
        if (
            receipt.height != row["height"]
            or receipt.timestamp != row["timestamp"]
            or receipt.parent_state_root != row["parent_state_root"]
            or receipt.state_root != row["state_root"]
        ):
            raise FinalizedStateStoreError("persisted block receipt row binding mismatch")

    def _validate_machine_binding(self, machine: StateMachine) -> None:
        if not isinstance(machine, StateMachine):
            raise FinalizedStateStoreError("StateMachine is required")
        if machine.chain_id != self.chain_id:
            raise FinalizedStateStoreError("state machine chain_id mismatch")
        if machine.genesis_hash != self.genesis_hash:
            raise FinalizedStateStoreError("state machine genesis_hash mismatch")
        if machine.protocol_version != self.protocol_version:
            raise FinalizedStateStoreError("state machine protocol_version mismatch")

    def _assert_exact_snapshot(
        self,
        row: sqlite3.Row,
        *,
        timestamp: int,
        parent_state_root: str | None,
        state_root: str,
        block_receipt_hash: str | None,
        block_receipt_json: bytes | None,
        snapshot_digest: str,
        snapshot: bytes,
    ) -> None:
        expected = {
            "timestamp": timestamp,
            "parent_state_root": parent_state_root,
            "state_root": state_root,
            "block_receipt_hash": block_receipt_hash,
            "block_receipt_json": block_receipt_json,
            "snapshot_digest": snapshot_digest,
            "snapshot_sha256": _hash_bytes(snapshot),
            "snapshot": snapshot,
        }
        actual = {key: row[key] for key in expected}
        if actual != expected:
            raise FinalizedStateStoreError("conflicting finalized snapshot already exists")
