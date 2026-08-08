"""Transactional persistent state and finalized checkpoint storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from .finality import FinalityCertificate
from .protocol_kernel import (
    AccountState,
    BlockTransition,
    ProtocolTransitionError,
    TransactionReceipt,
    compute_finalized_block_hash,
    compute_state_root,
    validate_block_transition,
    validate_receipt_sequence,
)


BLOCK_HEADER_V2_START_KEY = "block_header_v2_start_height"
BLOCK_HEADER_V2_LOCK_KEY = "block_header_v2_schedule_locked"
_ASCII_HEX = frozenset("0123456789abcdefABCDEF")


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
    header_version: int


class PersistentStateStore:
    """SQLite-backed full-snapshot store with atomic block commits."""

    def __init__(self, path: str | Path, *, chain_id: int) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise StateStoreError("chain_id must be a positive integer")
        self.chain_id = chain_id
        self.connection = sqlite3.connect(
            str(path), isolation_level=None, check_same_thread=False
        )
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
              receipts_json TEXT NOT NULL,
              header_version INTEGER NOT NULL DEFAULT 1
                CHECK(header_version IN (1,2))
            );
            CREATE TABLE IF NOT EXISTS finality_certificates(
              height INTEGER PRIMARY KEY,
              certificate_json TEXT NOT NULL,
              FOREIGN KEY(height) REFERENCES blocks(height)
            );
            CREATE TABLE IF NOT EXISTS block_timestamps(
              height INTEGER PRIMARY KEY,
              timestamp INTEGER NOT NULL CHECK(timestamp > 0),
              FOREIGN KEY(height) REFERENCES blocks(height)
            );
            """
        )
        self._migrate_block_header_versions()
        self._bind_chain_id()

    def close(self) -> None:
        self.connection.close()

    def bind_block_header_v2_activation(
        self, requested_height: int | None
    ) -> int | None:
        """Persist one no-downtime V2 activation boundary before proposal work."""
        if requested_height is not None and (
            isinstance(requested_height, bool)
            or not isinstance(requested_height, int)
            or requested_height <= 0
        ):
            raise StateStoreError("block header V2 activation height is invalid")
        existing = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?",
            (BLOCK_HEADER_V2_START_KEY,),
        ).fetchone()
        if existing is not None:
            stored = existing["value"]
            if not stored.isdigit() or int(stored) <= 0:
                raise StateStoreError("block header V2 activation metadata is invalid")
            stored_height = int(stored)
            if requested_height is None or requested_height == stored_height:
                return stored_height
            base_row = self.connection.execute(
                "SELECT value FROM metadata WHERE key='base_height'"
            ).fetchone()
            base_height = (
                -1
                if base_row is None or not base_row["value"].isdigit()
                else int(base_row["value"])
            )
            if (
                base_height > 0
                and self.head_height == base_height
                and stored_height == base_height + 1
                and requested_height <= stored_height
            ):
                return stored_height
            raise StateStoreError("block header V2 activation schedule mismatch")
        inferred_height = self._inferred_v2_start_height()
        if inferred_height is not None:
            base_height = self._base_height()
            if requested_height not in (None, inferred_height) and not (
                base_height > 0
                and self.head_height == base_height
                and requested_height <= inferred_height
            ):
                raise StateStoreError("block header V2 activation schedule mismatch")
            self._persist_block_header_v2_activation(inferred_height)
            return inferred_height
        locked = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?",
            (BLOCK_HEADER_V2_LOCK_KEY,),
        ).fetchone()
        if locked is not None:
            raise StateStoreError("block header V2 activation metadata is missing")
        if requested_height is None:
            return None

        local_start_height = requested_height
        base_height = self._base_height()
        if requested_height <= self.head_height:
            if base_height > 0 and self.head_height == base_height:
                local_start_height = base_height + 1
            else:
                raise StateStoreError(
                    "block header V2 activation cannot be applied retrospectively"
                )
        self._persist_block_header_v2_activation(local_start_height)
        return local_start_height

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
                  gas_used,finalized,certificate_hash,accounts_json,receipts_json,
                  header_version
                ) VALUES(0,?,?,?,?,0,1,NULL,?,?,1)
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
            self.connection.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES('base_height','0')"
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
        block_timestamp: int | None = None,
        header_version: int | None = None,
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
        if (
            block_timestamp is not None
            and (
                isinstance(block_timestamp, bool)
                or not isinstance(block_timestamp, int)
                or block_timestamp <= 0
            )
        ):
            raise StateStoreError("block timestamp must be a positive integer")
        if certificate.signed_power * 3 <= certificate.total_power * 2:
            raise StateStoreError("finality certificate is below strict two-thirds quorum")
        activation_height = self._block_header_v2_start_height()
        uses_v2_header = (
            activation_height is not None and height >= activation_height
        )
        expected_header_version = 2 if uses_v2_header else 1
        if header_version is not None and (
            isinstance(header_version, bool)
            or not isinstance(header_version, int)
            or header_version != expected_header_version
        ):
            raise StateStoreError("block header version does not match activation schedule")
        try:
            validate_block_transition(transition)
            expected_block_hash = (
                compute_finalized_block_hash(
                    chain_id=self.chain_id,
                    height=height,
                    parent_hash=parent_hash.lower(),
                    transition=transition,
                    block_timestamp=block_timestamp,
                )
                if uses_v2_header
                else block_hash.lower()
            )
        except ProtocolTransitionError as exc:
            raise StateStoreError(f"transition integrity failure: {exc}") from exc
        if uses_v2_header and block_hash.lower() != expected_block_hash:
            raise StateStoreError("block_hash does not match transition commitment")
        if certificate.height != height or certificate.block_hash != block_hash.lower():
            raise StateStoreError("finality certificate does not bind the committed block")
        normalized = _normalize_accounts(transition.accounts)
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
            locked_activation_height = self._block_header_v2_start_height()
            if locked_activation_height != activation_height:
                raise StateStoreError("block header V2 activation metadata is invalid")
            self.connection.execute(
                """
                INSERT INTO blocks(
                  height,block_hash,parent_hash,state_root,base_fee_per_gas,
                  gas_used,finalized,certificate_hash,accounts_json,receipts_json,
                  header_version
                ) VALUES(?,?,?,?,?,?,1,?,?,?,?)
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
                    expected_header_version,
                ),
            )
            if block_timestamp is not None:
                self.connection.execute(
                    "INSERT INTO block_timestamps(height,timestamp) VALUES(?,?)",
                    (height, block_timestamp),
                )
            self.connection.execute(
                """
                INSERT INTO finality_certificates(height,certificate_json)
                VALUES(?,?)
                """,
                (
                    height,
                    json.dumps(
                        certificate.as_evidence(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
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

    def latest_finality_certificate(self) -> FinalityCertificate | None:
        """Return the certificate atomically stored with the finalized head.

        Genesis has no certificate. Stores created by an older runtime can
        contain a certificate hash without the full certificate; those stores
        return ``None`` instead of fabricating recovery evidence.
        """
        row = self.connection.execute(
            """
            SELECT b.height,b.block_hash,b.certificate_hash,c.certificate_json
            FROM blocks AS b
            LEFT JOIN finality_certificates AS c ON c.height=b.height
            ORDER BY b.height DESC LIMIT 1
            """
        ).fetchone()
        if row is None or row["height"] == 0 or row["certificate_json"] is None:
            return None
        certificate = _decode_finality_certificate(row["certificate_json"])
        if (
            certificate.chain_id != self.chain_id
            or certificate.height != row["height"]
            or certificate.block_hash != row["block_hash"]
            or certificate.certificate_hash != row["certificate_hash"]
        ):
            raise StateStoreError("stored finality certificate does not bind head")
        return certificate

    def block_timestamp(self, height: int) -> int | None:
        row = self.connection.execute(
            "SELECT timestamp FROM block_timestamps WHERE height=?", (height,)
        ).fetchone()
        return None if row is None else int(row["timestamp"])

    def accounts_at(self, height: int | None = None) -> dict[str, AccountState]:
        target = self.head_height if height is None else height
        row = self.connection.execute(
            "SELECT accounts_json FROM blocks WHERE height=?", (target,)
        ).fetchone()
        if row is None:
            raise StateStoreError("unknown block height")
        return _decode_accounts_json(row["accounts_json"])

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
        accounts = _decode_accounts_json(row["accounts_json"])
        if compute_state_root(accounts) != row["state_root"]:
            raise StateStoreError("stored state_root integrity failure")
        _validate_stored_block_identity(row)
        body: dict[str, object] = {
            "schema_version": "junca-state-checkpoint/v2",
            "chain_id": self.chain_id,
            "height": row["height"],
            "block_hash": row["block_hash"],
            "parent_hash": row["parent_hash"],
            "state_root": row["state_root"],
            "base_fee_per_gas": row["base_fee_per_gas"],
            "gas_used": row["gas_used"],
            "finalized": bool(row["finalized"]),
            "certificate_hash": row["certificate_hash"],
            "header_version": row["header_version"],
            "block_header_v2_activation_height": (
                self._block_header_v2_start_height()
            ),
            "accounts": json.loads(_accounts_json(accounts)),
        }
        body["checkpoint_digest"] = _checkpoint_digest(body)
        return body

    def restore_checkpoint(
        self,
        checkpoint: Mapping[str, object],
        *,
        trusted_checkpoint_digest: str,
        trusted_block_hash: str,
    ) -> StoredBlock:
        """Restore an empty store from one verified finalized checkpoint.

        Historical blocks are intentionally not reconstructed.  The restored
        checkpoint becomes the local base height and new finalized blocks may
        extend it normally.  A locally recomputable digest is only an integrity
        check, not proof of canonical finality, so restore also requires two
        independently obtained trusted anchors.
        """
        if self.head_height >= 0:
            raise StateStoreError("checkpoint restore requires an empty state store")
        evidence = self.verify_checkpoint(checkpoint)
        if evidence["chain_id"] != self.chain_id:
            raise StateStoreError("checkpoint chain_id mismatch")
        _hash(trusted_checkpoint_digest, "trusted checkpoint_digest")
        _hash(trusted_block_hash, "trusted block_hash")
        if checkpoint["checkpoint_digest"] != trusted_checkpoint_digest.lower():
            raise StateStoreError("checkpoint does not match trusted digest")
        if checkpoint["block_hash"] != trusted_block_hash.lower():
            raise StateStoreError("checkpoint does not match trusted block hash")
        height = int(checkpoint["height"])
        header_version = int(checkpoint.get("header_version", 1))
        activation_height = checkpoint.get("block_header_v2_activation_height")
        if height == 0:
            expected_parent = "0x" + ("0" * 64)
            if checkpoint["parent_hash"] != expected_parent:
                raise StateStoreError("genesis checkpoint parent_hash is invalid")
        accounts = {
            address: AccountState(balance=value["balance"], nonce=value["nonce"])
            for address, value in checkpoint["accounts"].items()
        }
        normalized = _normalize_accounts(accounts)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            locked = self.connection.execute(
                "SELECT COUNT(*) AS count FROM blocks"
            ).fetchone()
            if locked is None or locked["count"] != 0:
                raise StateStoreError("state store changed during checkpoint restore")
            self.connection.execute(
                """
                INSERT INTO blocks(
                  height,block_hash,parent_hash,state_root,base_fee_per_gas,
                  gas_used,finalized,certificate_hash,accounts_json,receipts_json,
                  header_version
                ) VALUES(?,?,?,?,?,?,1,?,?,?,?)
                """,
                (
                    height,
                    checkpoint["block_hash"],
                    checkpoint["parent_hash"],
                    checkpoint["state_root"],
                    checkpoint["base_fee_per_gas"],
                    checkpoint["gas_used"],
                    checkpoint["certificate_hash"],
                    _accounts_json(normalized),
                    "[]",
                    header_version,
                ),
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES('base_height',?)",
                (str(height),),
            )
            if activation_height is not None:
                self.connection.execute(
                    "INSERT INTO metadata(key,value) VALUES(?,?)",
                    (BLOCK_HEADER_V2_START_KEY, str(activation_height)),
                )
                self.connection.execute(
                    "INSERT INTO metadata(key,value) VALUES(?, '1')",
                    (BLOCK_HEADER_V2_LOCK_KEY,),
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return self.head()

    @staticmethod
    def verify_checkpoint(checkpoint: Mapping[str, object]) -> dict[str, object]:
        base_required = {
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
        schema_version = checkpoint.get("schema_version")
        if schema_version == "junca-state-checkpoint/v1":
            required = base_required
        elif schema_version == "junca-state-checkpoint/v2":
            required = base_required | {
                "header_version",
                "block_header_v2_activation_height",
            }
        else:
            raise StateStoreError("checkpoint schema is unsupported")
        if set(checkpoint) != required:
            raise StateStoreError("checkpoint fields are invalid")
        supplied_digest = checkpoint["checkpoint_digest"]
        _hash(supplied_digest, "checkpoint_digest")
        if supplied_digest != supplied_digest.lower():
            raise StateStoreError("checkpoint_digest is not canonical")
        body = {key: value for key, value in checkpoint.items() if key != "checkpoint_digest"}
        if supplied_digest != _checkpoint_digest(body):
            raise StateStoreError("checkpoint digest mismatch")
        chain_id = checkpoint["chain_id"]
        height = checkpoint["height"]
        base_fee = checkpoint["base_fee_per_gas"]
        gas_used = checkpoint["gas_used"]
        header_version = checkpoint.get("header_version", 1)
        activation_height = checkpoint.get("block_header_v2_activation_height")
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise StateStoreError("checkpoint chain_id is invalid")
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise StateStoreError("checkpoint height is invalid")
        if (
            isinstance(base_fee, bool)
            or not isinstance(base_fee, int)
            or base_fee <= 0
        ):
            raise StateStoreError("checkpoint base_fee_per_gas is invalid")
        if isinstance(gas_used, bool) or not isinstance(gas_used, int) or gas_used < 0:
            raise StateStoreError("checkpoint gas_used is invalid")
        if header_version not in (1, 2) or isinstance(header_version, bool):
            raise StateStoreError("checkpoint header_version is invalid")
        if activation_height is not None and (
            isinstance(activation_height, bool)
            or not isinstance(activation_height, int)
            or activation_height <= 0
        ):
            raise StateStoreError(
                "checkpoint block header V2 activation height is invalid"
            )
        if header_version == 2 and (
            height <= 0
            or activation_height is None
            or activation_height > height
        ):
            raise StateStoreError("checkpoint V2 header activation is inconsistent")
        if (
            header_version == 1
            and activation_height is not None
            and activation_height <= height
        ):
            raise StateStoreError("checkpoint V1 header activation is inconsistent")
        if checkpoint["finalized"] is not True:
            raise StateStoreError("checkpoint is not finalized")
        raw_accounts = checkpoint["accounts"]
        if not isinstance(raw_accounts, dict):
            raise StateStoreError("checkpoint accounts are invalid")
        try:
            accounts = _decode_accounts(raw_accounts)
        except (KeyError, TypeError, ValueError) as exc:
            raise StateStoreError("checkpoint accounts are invalid") from exc
        normalized = _normalize_accounts(accounts)
        if raw_accounts != json.loads(_accounts_json(normalized)):
            raise StateStoreError("checkpoint accounts are not canonical")
        if checkpoint["state_root"] != compute_state_root(normalized):
            raise StateStoreError("checkpoint state_root integrity failure")
        _hash(checkpoint["block_hash"], "checkpoint block_hash")
        _hash(checkpoint["parent_hash"], "checkpoint parent_hash")
        _hash(checkpoint["state_root"], "checkpoint state_root")
        for field in ("block_hash", "parent_hash", "state_root"):
            if checkpoint[field] != checkpoint[field].lower():
                raise StateStoreError(f"checkpoint {field} is not canonical")
        certificate_hash = checkpoint["certificate_hash"]
        zero_hash = "0x" + ("0" * 64)
        if height == 0:
            if checkpoint["parent_hash"] != zero_hash:
                raise StateStoreError("genesis checkpoint parent_hash is invalid")
            if certificate_hash is not None:
                raise StateStoreError("genesis checkpoint cannot contain a certificate")
        elif not certificate_hash:
            raise StateStoreError("checkpoint lacks finality evidence")
        if certificate_hash is not None:
            _hash(certificate_hash, "checkpoint certificate_hash")
            if certificate_hash != certificate_hash.lower():
                raise StateStoreError("checkpoint certificate_hash is not canonical")
        return {
            "schema_version": "junca-state-checkpoint-verification/v2",
            "chain_id": checkpoint["chain_id"],
            "height": checkpoint["height"],
            "header_version": header_version,
            "block_header_v2_activation_height": activation_height,
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
        base_height = int(rows[0]["height"])
        metadata_base = self.connection.execute(
            "SELECT value FROM metadata WHERE key='base_height'"
        ).fetchone()
        if (
            metadata_base is None
            or not metadata_base["value"].isdigit()
            or int(metadata_base["value"]) != base_height
        ):
            raise StateStoreError("stored base_height metadata is invalid")
        previous_hash = rows[0]["parent_hash"]
        _hash(previous_hash, "base parent_hash")
        activation = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?",
            (BLOCK_HEADER_V2_START_KEY,),
        ).fetchone()
        activation_height: int | None = None
        activation_source = "UNSCHEDULED"
        if activation is not None:
            value = activation["value"]
            if not value.isdigit() or int(value) <= 0:
                raise StateStoreError("block header V2 activation metadata is invalid")
            activation_height = int(value)
            activation_source = "PERSISTED_SCHEDULE"
        else:
            activation_height = self._inferred_v2_start_height()
            if activation_height is not None:
                activation_source = "FINALIZED_BLOCK_HISTORY"
            else:
                locked = self.connection.execute(
                    "SELECT value FROM metadata WHERE key=?",
                    (BLOCK_HEADER_V2_LOCK_KEY,),
                ).fetchone()
                if locked is not None:
                    raise StateStoreError(
                        "block header V2 activation metadata is missing"
                    )
        seen_v2 = False
        for offset, row in enumerate(rows):
            expected_height = base_height + offset
            if row["height"] != expected_height:
                raise StateStoreError("block heights are not contiguous")
            _validate_stored_block_identity(row)
            if row["parent_hash"] != previous_hash:
                raise StateStoreError("stored parent_hash chain is invalid")
            header_version = row["header_version"]
            if (
                isinstance(header_version, bool)
                or not isinstance(header_version, int)
                or header_version not in (1, 2)
            ):
                raise StateStoreError("stored block header version is invalid")
            if row["height"] == 0 and header_version != 1:
                raise StateStoreError("genesis block header version is invalid")
            if header_version == 2:
                seen_v2 = True
            elif seen_v2:
                raise StateStoreError("stored block header version downgrade detected")
            if activation_height is not None:
                expected_header_version = (
                    2 if row["height"] >= activation_height else 1
                )
                if header_version != expected_header_version:
                    raise StateStoreError(
                        "stored block header version violates activation schedule"
                    )
            if (
                isinstance(row["base_fee_per_gas"], bool)
                or not isinstance(row["base_fee_per_gas"], int)
                or row["base_fee_per_gas"] <= 0
                or isinstance(row["gas_used"], bool)
                or not isinstance(row["gas_used"], int)
                or row["gas_used"] < 0
            ):
                raise StateStoreError("stored execution values are invalid")
            try:
                normalized = _decode_accounts_json(row["accounts_json"])
                receipts = json.loads(row["receipts_json"])
                if not isinstance(receipts, list):
                    raise TypeError
            except StateStoreError:
                raise
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise StateStoreError("stored state payload is invalid") from exc
            if _accounts_json(normalized) != row["accounts_json"]:
                raise StateStoreError("stored account snapshot is not canonical")
            if (
                json.dumps(
                    receipts,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                != row["receipts_json"]
            ):
                raise StateStoreError("stored receipts are not canonical")
            try:
                receipt_objects = _decode_receipts(receipts)
                is_pruned_checkpoint_base = (
                    offset == 0
                    and base_height > 0
                    and not receipt_objects
                )
                if not is_pruned_checkpoint_base:
                    total_burned, total_tips = validate_receipt_sequence(
                        base_fee_per_gas=row["base_fee_per_gas"],
                        gas_used=row["gas_used"],
                        receipts=receipt_objects,
                    )
            except ProtocolTransitionError as exc:
                raise StateStoreError(f"stored receipt integrity failure: {exc}") from exc
            if compute_state_root(normalized) != row["state_root"]:
                raise StateStoreError("stored state_root integrity failure")
            if header_version == 2:
                if is_pruned_checkpoint_base:
                    # The checkpoint digest and separately trusted block hash
                    # anchor this intentionally pruned base. Every descendant
                    # V2 block remains locally recomputable in full.
                    expected_block_hash = row["block_hash"]
                else:
                    transition = BlockTransition(
                        chain_id=self.chain_id,
                        base_fee_per_gas=row["base_fee_per_gas"],
                        gas_used=row["gas_used"],
                        total_base_fee_burned=total_burned,
                        total_validator_tips=total_tips,
                        state_root=row["state_root"],
                        accounts=normalized,
                        receipts=receipt_objects,
                    )
                    timestamp = self.connection.execute(
                        "SELECT timestamp FROM block_timestamps WHERE height=?",
                        (row["height"],),
                    ).fetchone()
                    try:
                        expected_block_hash = compute_finalized_block_hash(
                            chain_id=self.chain_id,
                            height=row["height"],
                            parent_hash=row["parent_hash"],
                            transition=transition,
                            block_timestamp=(
                                None
                                if timestamp is None
                                else int(timestamp["timestamp"])
                            ),
                        )
                    except ProtocolTransitionError as exc:
                        raise StateStoreError(
                            f"stored V2 commitment integrity failure: {exc}"
                        ) from exc
                if expected_block_hash != row["block_hash"]:
                    raise StateStoreError("stored V2 block_hash commitment mismatch")
            if row["height"] > 0 and (
                not row["finalized"] or not row["certificate_hash"]
            ):
                raise StateStoreError("non-genesis block lacks finality evidence")
            if row["certificate_hash"] is not None:
                _hash(row["certificate_hash"], "stored certificate_hash")
            previous_hash = row["block_hash"]
        return {
            "schema_version": "junca-persistent-state-integrity/v1",
            "chain_id": self.chain_id,
            "base_height": base_height,
            "head_height": rows[-1]["height"],
            "head_hash": rows[-1]["block_hash"],
            "state_root": rows[-1]["state_root"],
            "block_count": len(rows),
            "block_header_v2_start_height": activation_height,
            "block_header_v2_activation_source": activation_source,
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

    def _migrate_block_header_versions(self) -> None:
        """Add the immutable per-block V2 anchor to pre-upgrade databases."""
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(blocks)").fetchall()
        }
        if "header_version" not in columns:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                self.connection.execute(
                    "ALTER TABLE blocks ADD COLUMN header_version INTEGER "
                    "NOT NULL DEFAULT 1 CHECK(header_version IN (1,2))"
                )
                activation = self.connection.execute(
                    "SELECT value FROM metadata WHERE key=?",
                    (BLOCK_HEADER_V2_START_KEY,),
                ).fetchone()
                if activation is not None:
                    value = activation["value"]
                    if not value.isdigit() or int(value) <= 0:
                        raise StateStoreError(
                            "block header V2 activation metadata is invalid"
                        )
                    self.connection.execute(
                        "UPDATE blocks SET header_version=2 WHERE height>=?",
                        (int(value),),
                    )
                    self.connection.execute(
                        "INSERT OR IGNORE INTO metadata(key,value) VALUES(?, '1')",
                        (BLOCK_HEADER_V2_LOCK_KEY,),
                    )
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
        elif self.connection.execute(
            "SELECT value FROM metadata WHERE key=?",
            (BLOCK_HEADER_V2_START_KEY,),
        ).fetchone() is not None:
            self.connection.execute(
                "INSERT OR IGNORE INTO metadata(key,value) VALUES(?, '1')",
                (BLOCK_HEADER_V2_LOCK_KEY,),
            )
        self.connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS blocks_header_version_immutable
            BEFORE UPDATE OF header_version ON blocks
            BEGIN
              SELECT RAISE(ABORT, 'finalized block header_version is immutable');
            END;
            """
        )

    def _base_height(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='base_height'"
        ).fetchone()
        if row is None or not row["value"].isdigit():
            return -1
        return int(row["value"])

    def _inferred_v2_start_height(self) -> int | None:
        row = self.connection.execute(
            "SELECT MIN(height) AS height FROM blocks WHERE header_version=2"
        ).fetchone()
        if row is None or row["height"] is None:
            return None
        first_v2 = int(row["height"])
        base_height = self._base_height()
        if first_v2 == base_height and base_height > 0:
            base = self.connection.execute(
                "SELECT receipts_json FROM blocks WHERE height=?",
                (base_height,),
            ).fetchone()
            if base is not None and base["receipts_json"] == "[]":
                return base_height
        return first_v2

    def _persist_block_header_v2_activation(self, height: int) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT value FROM metadata WHERE key=?",
                (BLOCK_HEADER_V2_START_KEY,),
            ).fetchone()
            if existing is not None and existing["value"] != str(height):
                raise StateStoreError("block header V2 activation schedule mismatch")
            self.connection.execute(
                "INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)",
                (BLOCK_HEADER_V2_START_KEY, str(height)),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO metadata(key,value) VALUES(?, '1')",
                (BLOCK_HEADER_V2_LOCK_KEY,),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def _block_header_v2_start_height(self) -> int | None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?",
            (BLOCK_HEADER_V2_START_KEY,),
        ).fetchone()
        if row is None:
            inferred = self._inferred_v2_start_height()
            if inferred is not None:
                return inferred
            locked = self.connection.execute(
                "SELECT value FROM metadata WHERE key=?",
                (BLOCK_HEADER_V2_LOCK_KEY,),
            ).fetchone()
            if locked is not None:
                raise StateStoreError("block header V2 activation metadata is missing")
            return None
        value = row["value"]
        if not value.isdigit() or int(value) <= 0:
            raise StateStoreError("block header V2 activation metadata is invalid")
        return int(value)

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
            header_version=row["header_version"],
        )


def _normalize_accounts(accounts: Mapping[str, AccountState]) -> dict[str, AccountState]:
    normalized: dict[str, AccountState] = {}
    for address, account in accounts.items():
        key = address.lower()
        if len(key) != 42 or not key.startswith("0x"):
            raise StateStoreError("account address must be a 20-byte hex value")
        if any(character not in _ASCII_HEX for character in key[2:]):
            raise StateStoreError("account address must be a 20-byte hex value")
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
        allow_nan=False,
    )


def _decode_accounts(raw_accounts: Mapping[object, object]) -> dict[str, AccountState]:
    accounts: dict[str, AccountState] = {}
    for address, value in raw_accounts.items():
        if not isinstance(address, str) or not isinstance(value, dict):
            raise StateStoreError("account snapshot is invalid")
        if set(value) != {"balance", "nonce"}:
            raise StateStoreError("account snapshot fields are invalid")
        try:
            accounts[address] = AccountState(
                balance=value["balance"],
                nonce=value["nonce"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StateStoreError("account snapshot is invalid") from exc
    return _normalize_accounts(accounts)


def _decode_accounts_json(payload: str) -> dict[str, AccountState]:
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise StateStoreError("stored account snapshot is invalid") from exc
    if not isinstance(raw, dict):
        raise StateStoreError("stored account snapshot is invalid")
    accounts = _decode_accounts(raw)
    if _accounts_json(accounts) != payload:
        raise StateStoreError("stored account snapshot is not canonical")
    return accounts


def _decode_receipts(raw_receipts: object) -> tuple[TransactionReceipt, ...]:
    required = {
        "transaction_hash",
        "transaction_index",
        "sender",
        "recipient",
        "gas_used",
        "effective_gas_price",
        "base_fee_burned",
        "validator_tip",
        "status",
    }
    if not isinstance(raw_receipts, list):
        raise StateStoreError("stored receipts are invalid")
    decoded: list[TransactionReceipt] = []
    for raw_receipt in raw_receipts:
        if not isinstance(raw_receipt, dict) or set(raw_receipt) != required:
            raise StateStoreError("stored receipt fields are invalid")
        try:
            decoded.append(TransactionReceipt(**raw_receipt))
        except (TypeError, ValueError) as exc:
            raise StateStoreError("stored receipt is invalid") from exc
    return tuple(decoded)


def _decode_finality_certificate(payload: str) -> FinalityCertificate:
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise StateStoreError("stored finality certificate is invalid") from exc
    required = {
        "schema_version",
        "chain_id",
        "height",
        "round",
        "block_hash",
        "signed_power",
        "total_power",
        "validator_ids",
        "vote_hashes",
        "certificate_hash",
        "finality_status",
        "mainnet_changed",
        "assets_moved",
        "bridge_activated",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or raw["schema_version"] != "junca-finality-certificate/v1"
        or raw["finality_status"] != "FINALIZED"
        or raw["mainnet_changed"] is not False
        or raw["assets_moved"] is not False
        or raw["bridge_activated"] is not False
    ):
        raise StateStoreError("stored finality certificate is invalid")
    integer_fields = ("chain_id", "height", "round", "signed_power", "total_power")
    if any(
        isinstance(raw[field], bool) or not isinstance(raw[field], int)
        for field in integer_fields
    ):
        raise StateStoreError("stored finality certificate is invalid")
    if (
        raw["chain_id"] <= 0
        or raw["height"] <= 0
        or raw["round"] < 0
        or raw["signed_power"] <= 0
        or raw["total_power"] <= 0
        or raw["signed_power"] > raw["total_power"]
        or raw["signed_power"] * 3 <= raw["total_power"] * 2
    ):
        raise StateStoreError("stored finality certificate is invalid")
    validators = raw["validator_ids"]
    vote_hashes = raw["vote_hashes"]
    if (
        not isinstance(validators, list)
        or not validators
        or validators != sorted(set(validators))
        or any(not isinstance(item, str) or not item for item in validators)
        or not isinstance(vote_hashes, list)
        or len(vote_hashes) != len(validators)
    ):
        raise StateStoreError("stored finality certificate is invalid")
    _hash(raw["block_hash"], "stored certificate block_hash")
    _hash(raw["certificate_hash"], "stored certificate_hash")
    for item in vote_hashes:
        _hash(item, "stored certificate vote_hash")
    body = {
        "block_hash": raw["block_hash"],
        "chain_id": raw["chain_id"],
        "height": raw["height"],
        "round": raw["round"],
        "signed_power": raw["signed_power"],
        "total_power": raw["total_power"],
        "validator_ids": validators,
        "vote_hashes": vote_hashes,
    }
    expected_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if raw["certificate_hash"] != expected_hash:
        raise StateStoreError("stored finality certificate hash mismatch")
    return FinalityCertificate(
        chain_id=raw["chain_id"],
        height=raw["height"],
        round=raw["round"],
        block_hash=raw["block_hash"],
        signed_power=raw["signed_power"],
        total_power=raw["total_power"],
        validator_ids=tuple(validators),
        vote_hashes=tuple(vote_hashes),
        certificate_hash=raw["certificate_hash"],
    )


def _validate_stored_block_identity(row: sqlite3.Row) -> None:
    for field in ("block_hash", "parent_hash", "state_root"):
        value = row[field]
        _hash(value, f"stored {field}")
        if value != value.lower():
            raise StateStoreError(f"stored {field} is not canonical")
    if row["height"] == 0:
        if row["parent_hash"] != "0x" + ("0" * 64):
            raise StateStoreError("stored genesis parent_hash is invalid")
        if row["certificate_hash"] is not None:
            raise StateStoreError("stored genesis cannot contain a certificate")
    elif not row["finalized"] or not row["certificate_hash"]:
        raise StateStoreError("non-genesis block lacks finality evidence")
    if row["certificate_hash"] is not None:
        _hash(row["certificate_hash"], "stored certificate_hash")
        if row["certificate_hash"] != row["certificate_hash"].lower():
            raise StateStoreError("stored certificate_hash is not canonical")


def _checkpoint_digest(body: Mapping[str, object]) -> str:
    try:
        canonical = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StateStoreError("checkpoint is not canonically serializable") from exc
    return "0x" + hashlib.sha256(
        b"JUNCA_STATE_CHECKPOINT_V1\x00" + canonical
    ).hexdigest()


def _hash(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise StateStoreError(f"{field} must be a 32-byte hex value")
    if any(character not in _ASCII_HEX for character in value[2:]):
        raise StateStoreError(f"{field} must be a 32-byte hex value")
