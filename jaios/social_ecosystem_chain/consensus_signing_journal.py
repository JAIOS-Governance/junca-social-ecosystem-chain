"""Persistent consensus anti-double-signing boundary."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import sqlite3
from pathlib import Path


class ConsensusSigningJournalError(ValueError):
    """Raised when a vote could violate the persistent signing invariant."""


VoteSigner = Callable[[], bytes]


class ConsensusSigningJournal:
    """Persist one block choice per validator, height and round.

    The journal stores signatures, which are public consensus artifacts, but
    never stores key resource identifiers or private key material.
    """

    def __init__(self, path: str | Path, *, chain_id: int) -> None:
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise ConsensusSigningJournalError("chain_id must be a positive integer")
        self.chain_id = chain_id
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consensus_signatures (
                validator_id TEXT NOT NULL,
                height INTEGER NOT NULL,
                round INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                signature BLOB NOT NULL,
                PRIMARY KEY (validator_id, height, round)
            );
            """
        )
        self._bind_chain()

    def close(self) -> None:
        self.connection.close()

    def get_or_sign(
        self,
        *,
        validator_id: str,
        height: int,
        round: int,
        block_hash: str,
        signing_payload: bytes,
        signer: VoteSigner,
    ) -> bytes:
        if not validator_id or any(char.isspace() for char in validator_id):
            raise ConsensusSigningJournalError("validator_id is invalid")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ConsensusSigningJournalError("height must be a positive integer")
        if isinstance(round, bool) or not isinstance(round, int) or round < 0:
            raise ConsensusSigningJournalError("round must be a non-negative integer")
        if (
            not isinstance(block_hash, str)
            or len(block_hash) != 66
            or not block_hash.startswith("0x")
            or any(char not in "0123456789abcdef" for char in block_hash[2:])
        ):
            raise ConsensusSigningJournalError(
                "block_hash must be a canonical lowercase SHA-256"
            )
        if not isinstance(signing_payload, bytes) or not signing_payload:
            raise ConsensusSigningJournalError("signing_payload must be non-empty bytes")
        if not callable(signer):
            raise ConsensusSigningJournalError("signer is required")

        payload_digest = hashlib.sha256(signing_payload).hexdigest()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT block_hash, payload_digest, signature
                FROM consensus_signatures
                WHERE validator_id=? AND height=? AND round=?
                """,
                (validator_id, height, round),
            ).fetchone()
            if row is not None:
                if (
                    row["block_hash"] != block_hash
                    or row["payload_digest"] != payload_digest
                ):
                    raise ConsensusSigningJournalError(
                        "conflicting consensus vote would double-sign"
                    )
                signature = bytes(row["signature"])
                self.connection.execute("COMMIT")
                return signature

            signature = signer()
            if not isinstance(signature, bytes) or len(signature) not in {64, 65}:
                raise ConsensusSigningJournalError(
                    "signer returned an invalid consensus signature"
                )
            self.connection.execute(
                """
                INSERT INTO consensus_signatures (
                    validator_id, height, round, block_hash, payload_digest, signature
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    validator_id,
                    height,
                    round,
                    block_hash,
                    payload_digest,
                    signature,
                ),
            )
            self.connection.execute("COMMIT")
            return signature
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def evidence(self) -> dict[str, object]:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS signature_count, MAX(height) AS latest_height
            FROM consensus_signatures
            """
        ).fetchone()
        return {
            "schema_version": "junca-consensus-signing-journal/v1",
            "chain_id": self.chain_id,
            "signature_count": int(row["signature_count"]),
            "latest_height": row["latest_height"],
            "private_key_material_stored": False,
            "key_resource_stored": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }

    def _bind_chain(self) -> None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE name='chain_id'"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata (name, value) VALUES ('chain_id', ?)",
                (str(self.chain_id),),
            )
        elif row["value"] != str(self.chain_id):
            self.connection.close()
            raise ConsensusSigningJournalError(
                "signing journal is bound to a different chain_id"
            )
