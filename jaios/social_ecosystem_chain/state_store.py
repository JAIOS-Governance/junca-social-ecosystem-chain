"""Transactional persistent state and finalized checkpoint storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from .finality import FinalityCertificate
from .protocol_kernel import AccountState, BlockTransition, compute_state_root


class StateStoreError(ValueError):
    """Raised when persistent chain state violates a protocol invariant."""


@dataclass(frozen=True)
class StoredBlock:
    height: int
    block_hash: str
    parent_hash: str
    state_root: str
    base_fee_per_gas: int
    gas_used: int
    finalized: bool
    certificate_hash: str | None


class PersistentStateStore:
    """SQLite-backed full-snapshot store with atomic block commits."""

    def __init__(self, path: str | Path, *, chain_id: int) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise StateStoreError("chain_id must be a positive integer")
        self.chain_id = chain_id
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS blocks(
              height INTEGER PRIMARY KEY,
              block_hash TEXT NOT NULL UNIQUE,
              parent_hash TEXT NOT NULL,
              state_root TEXT NOT NULL,
              base_fee_per_gas INTEGER NOT NULL,
              gas_used INTEGER NOT NULL,
              finalized INTEGER NOT NULL,
              certificate_hash TEXT,
              accounts_json TEXT NOT NULL,
              receipts_json TEXT NOT NULL
            );
            """
        )
        self._bind_chain_id()

    def close(self) -> None:
        self.connection.close()

    def initialize_genesis(
        self,
        *,
        block_hash: str,
        accounts: Mapping[str, AccountState],
        base_fee_per_gas: int,
    ) -> StoredBlock:
        _hash(block_hash, "genesis block_hash")
        if isinstance(base_fee_per_gas, bool) or not isinstance(base_fee_per_gas, int) or base_fee_per_gas <= 0:
            raise StateStoreError("genesis base fee must be a positive integer")
        normalized = _normalize_accounts(accounts)
        root = compute_state_root(normalized)
        existing = self.connection.execute("SELECT * FROM blocks WHERE height=0").fetchone()
        if existing is not None:
            if existing["block_hash"] != block_hash.lower() or existing["state_root"] != root:
                raise StateStoreError("genesis already initialized with different identity")
            return self._stored_block(existing)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                INSERT INTO blocks(
                  height,block_hash,parent_hash,state_root,base_fee_per_gas,
                  gas_used,finalized,certificate_hash,accounts_json,receipts_json
                ) VALUES(0,?,?,?,?,0,1,NULL,?,?)
                """,
                (
                    block_hash.lower(),
                    "0x" + ("0" * 64),
                    root,
                    base_fee_per_gas,
                    _accounts_json(normalized),
                    "[]",
                ),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return self.head()

    def commit_finalized_block(
        self,
        *,
        height: int,
        block_hash: str,
        parent_hash: str,
        transition: BlockTransition,
        certificate: FinalityCertificate,
    ) -> StoredBlock:
        if self.head_height < 0:
            raise StateStoreError("genesis must be initialized before block commit")
        if height != self.head_height + 1:
            raise StateStoreError("block height must extend the current head")
        _hash(block_hash, "block_hash")
        _hash(parent_hash, "parent_hash")
        current = self.head()
        if parent_hash.lower() != current.block_hash:
            raise StateStoreError("parent_hash does not match current head")
        if transition.chain_id != self.chain_id or certificate.chain_id != self.chain_id:
            raise StateStoreError("chain_id mismatch")
        if certificate.height != height or certificate.block_hash != block_hash.lower():
            raise StateStoreError("finality certificate does not bind the committed block")
        if certificate.signed_power * 3 <= certificate.total_power * 2:
            raise StateStoreError("finality certificate is below strict two-thirds quorum")
        normalized = _normalize_accounts(transition.accounts)
        if transition.state_root != compute_state_root(normalized):
            raise StateStoreError("transition state_root does not match account state")
        receipts = [asdict(receipt) for receipt in transition.receipts]
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            locked_head = self.connection.execute(
                "SELECT height,block_hash FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
            if (
                locked_head is None
                or locked_head["height"] != height - 1
                or locked_head["block_hash"] != parent_hash.lower()
            ):
                raise StateStoreError("block no longer extends the locked head")
            self.connection.execute(
                """
                INSERT INTO blocks(
                  height,block_hash,parent_hash,state_root,base_fee_per_gas,
                  gas_used,finalized,certificate_hash,accounts_json,receipts_json
                ) VALUES(?,?,?,?,?,?,1,?,?,?)
                """,
                (
                    height,
                    block_hash.lower(),
                    parent_hash.lower(),
                    transition.state_root,
                    transition.base_fee_per_gas,
                    transition.gas_used,
                    certificate.certificate_hash,
                    _accounts_json(normalized),
                    json.dumps(receipts, sort_keys=True, separators=(",", ":")),
                ),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return self.head()

    @property
    def head_height(self) -> int:
        row = self.connection.execute("SELECT MAX(height) AS height FROM blocks").fetchone()
        return -1 if row is None or row["height"] is None else int(row["height"])

    def head(self) -> StoredBlock:
        row = self.connection.execute(
            "SELECT * FROM blocks ORDER BY height DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise StateStoreError("state store is not initialized")
        return self._stored_block(row)

    def get_block(self, height: int) -> StoredBlock:
        row = self.connection.execute(
            "SELECT * FROM blocks WHERE height=?", (height,)
        ).fetchone()
        if row is None:
            raise StateStoreError("unknown block height")
        return self._stored_block(row)

    def accounts_at(self, height: int | None = None) -> dict[str, AccountState]:
        target = self.head_height if height is None else height
        row = self.connection.execute(
            "SELECT accounts_json FROM blocks WHERE height=?", (target,)
        ).fetchone()
        if row is None:
            raise StateStoreError("unknown block height")
        raw = json.loads(row["accounts_json"])
        return {
            address: AccountState(balance=value["balance"], nonce=value["nonce"])
            for address, value in raw.items()
        }

    def rollback_to(self, height: int) -> None:
        if height != self.head_height:
            raise StateStoreError("finalized block rollback is prohibited")

    def export_checkpoint(self, height: int | None = None) -> dict[str, object]:
        target = self.head_height if height is None else height
        row = self.connection.execute(
            "SELECT * FROM blocks WHERE height=?", (target,)
        ).fetchone()
        if row is None:
            raise StateStoreError("unknown checkpoint height")
        body: dict[str, object] = {
            "schema_version": "junca-state-checkpoint/v1",
            "chain_id": self.chain_id,
            "height": row["height"],
            "block_hash": row["block_hash"],
            "parent_hash": row["parent_hash"],
            "state_root": row["state_root"],
            "base_fee_per_gas": row["base_fee_per_gas"],
            "gas_used": row["gas_used"],
            "finalized": bool(row["finalized"]),
            "certificate_hash": row["certificate_hash"],
            "accounts": json.loads(row["accounts_json"]),
        }
        body["checkpoint_digest"] = _checkpoint_digest(body)
        return body

    @staticmethod
    def verify_checkpoint(checkpoint: Mapping[str, object]) -> dict[str, object]:
        required = {
            "schema_version",
            "chain_id",
            "height",
            "block_hash",
            "parent_hash",
            "state_root",
            "base_fee_per_gas",
            "gas_used",
            "finalized",
            "certificate_hash",
            "accounts",
            "checkpoint_digest",
        }
        if set(checkpoint) != required:
            raise StateStoreError("checkpoint fields are invalid")
        if checkpoint["schema_version"] != "junca-state-checkpoint/v1":
            raise StateStoreError("checkpoint schema is unsupported")
        supplied_digest = checkpoint["checkpoint_digest"]
        body = {key: value for key, value in checkpoint.items() if key != "checkpoint_digest"}
        if supplied_digest != _checkpoint_digest(body):
            raise StateStoreError("checkpoint digest mismatch")
        raw_accounts = checkpoint["accounts"]
        if not isinstance(raw_accounts, dict):
            raise StateStoreError("checkpoint accounts are invalid")
        try:
            accounts = {
                address: AccountState(balance=value["balance"], nonce=value["nonce"])
                for address, value in raw_accounts.items()
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise StateStoreError("checkpoint accounts are invalid") from exc
        normalized = _normalize_accounts(accounts)
        if checkpoint["state_root"] != compute_state_root(normalized):
            raise StateStoreError("checkpoint state_root integrity failure")
        _hash(checkpoint["block_hash"], "checkpoint block_hash")
        _hash(checkpoint["parent_hash"], "checkpoint parent_hash")
        if checkpoint["height"] > 0 and (
            checkpoint["finalized"] is not True or not checkpoint["certificate_hash"]
        ):
            raise StateStoreError("checkpoint lacks finality evidence")
        return {
            "schema_version": "junca-state-checkpoint-verification/v1",
            "chain_id": checkpoint["chain_id"],
            "height": checkpoint["height"],
            "checkpoint_digest": supplied_digest,
            "verification_status": "VERIFIED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def integrity_check(self) -> dict[str, object]:
        rows = self.connection.execute("SELECT * FROM blocks ORDER BY height").fetchall()
        if not rows:
            raise StateStoreError("state store is not initialized")
        previous_hash = "0x" + ("0" * 64)
        for expected_height, row in enumerate(rows):
            if row["height"] != expected_height:
                raise StateStoreError("block heights are not contiguous")
            if row["parent_hash"] != previous_hash:
                raise StateStoreError("stored parent_hash chain is invalid")
            accounts = {
                address: AccountState(balance=value["balance"], nonce=value["nonce"])
                for address, value in json.loads(row["accounts_json"]).items()
            }
            if compute_state_root(accounts) != row["state_root"]:
                raise StateStoreError("stored state_root integrity failure")
            if row["height"] > 0 and (
                not row["finalized"] or not row["certificate_hash"]
            ):
                raise StateStoreError("non-genesis block lacks finality evidence")
            previous_hash = row["block_hash"]
        return {
            "schema_version": "junca-persistent-state-integrity/v1",
            "chain_id": self.chain_id,
            "head_height": rows[-1]["height"],
            "head_hash": rows[-1]["block_hash"],
            "state_root": rows[-1]["state_root"],
            "block_count": len(rows),
            "integrity_status": "VERIFIED",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _bind_chain_id(self) -> None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='chain_id'"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata(key,value) VALUES('chain_id',?)",
                (str(self.chain_id),),
            )
        elif row["value"] != str(self.chain_id):
            raise StateStoreError("database is bound to a different chain_id")

    @staticmethod
    def _stored_block(row: sqlite3.Row) -> StoredBlock:
        return StoredBlock(
            height=row["height"],
            block_hash=row["block_hash"],
            parent_hash=row["parent_hash"],
            state_root=row["state_root"],
            base_fee_per_gas=row["base_fee_per_gas"],
            gas_used=row["gas_used"],
            finalized=bool(row["finalized"]),
            certificate_hash=row["certificate_hash"],
        )


def _normalize_accounts(accounts: Mapping[str, AccountState]) -> dict[str, AccountState]:
    normalized: dict[str, AccountState] = {}
    for address, account in accounts.items():
        key = address.lower()
        if len(key) != 42 or not key.startswith("0x"):
            raise StateStoreError("account address must be a 20-byte hex value")
        try:
            int(key[2:], 16)
        except ValueError as exc:
            raise StateStoreError("account address must be a 20-byte hex value") from exc
        if key in normalized or not isinstance(account, AccountState):
            raise StateStoreError("account snapshot is invalid")
        normalized[key] = account
    return dict(sorted(normalized.items()))


def _accounts_json(accounts: Mapping[str, AccountState]) -> str:
    return json.dumps(
        {
            address: {"balance": account.balance, "nonce": account.nonce}
            for address, account in sorted(accounts.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _checkpoint_digest(body: Mapping[str, object]) -> str:
    return "0x" + hashlib.sha256(
        b"JUNCA_STATE_CHECKPOINT_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise StateStoreError(f"{field} must be a 32-byte hex value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise StateStoreError(f"{field} must be a 32-byte hex value") from exc
