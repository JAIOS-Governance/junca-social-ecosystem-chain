"""Persistent consensus anti-double-signing boundary."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import sqlite3
from pathlib import Path


class ConsensusSigningJournalError(ValueError):
    """Raised when a vote could violate the persistent signing invariant."""


VoteSigner = Callable[[], bytes]
VoteSignatureVerifier = Callable[[bytes], bool]


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
        integrity = self.connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            self.connection.close()
            raise ConsensusSigningJournalError(
                "signing journal integrity check failed"
            )
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
            CREATE TABLE IF NOT EXISTS validator_watermarks (
                validator_id TEXT PRIMARY KEY,
                height INTEGER NOT NULL,
                round INTEGER NOT NULL,
                CHECK (height > 0),
                CHECK (round >= 0)
            );
            """
        )
        self._bind_chain()
        self._restore_watermarks()

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
        signature_verifier: VoteSignatureVerifier,
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
        if not callable(signature_verifier):
            raise ConsensusSigningJournalError("signature_verifier is required")
        self._validate_signing_payload(
            validator_id=validator_id,
            height=height,
            round=round,
            block_hash=block_hash,
            signing_payload=signing_payload,
        )

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
                self._verify_signature(signature, signature_verifier)
                self.connection.execute("COMMIT")
                return signature

            watermark = self.connection.execute(
                """
                SELECT height, round
                FROM validator_watermarks
                WHERE validator_id=?
                """,
                (validator_id,),
            ).fetchone()
            if watermark is not None and (
                height < watermark["height"]
                or (height == watermark["height"] and round < watermark["round"])
            ):
                raise ConsensusSigningJournalError(
                    "consensus vote is below the persistent signing watermark"
                )

            signature = self._call_signer(signer)
            if not isinstance(signature, bytes) or len(signature) not in {64, 65}:
                raise ConsensusSigningJournalError(
                    "signer returned an invalid consensus signature"
                )
            self._verify_signature(signature, signature_verifier)
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
            self.connection.execute(
                """
                INSERT INTO validator_watermarks (validator_id, height, round)
                VALUES (?, ?, ?)
                ON CONFLICT(validator_id) DO UPDATE SET
                    height=excluded.height,
                    round=excluded.round
                WHERE excluded.height > validator_watermarks.height
                   OR (
                       excluded.height = validator_watermarks.height
                       AND excluded.round > validator_watermarks.round
                   )
                """,
                (validator_id, height, round),
            )
            self.connection.execute("COMMIT")
            return signature
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def evidence(self) -> dict[str, object]:
        signature_row = self.connection.execute(
            """
            SELECT COUNT(*) AS signature_count, MAX(height) AS latest_height
            FROM consensus_signatures
            """
        ).fetchone()
        watermark_row = self.connection.execute(
            """
            SELECT COUNT(*) AS validator_count, MAX(height) AS latest_height
            FROM validator_watermarks
            """
        ).fetchone()
        return {
            "schema_version": "junca-consensus-signing-journal/v5",
            "chain_id": self.chain_id,
            "signature_count": int(signature_row["signature_count"]),
            "latest_height": signature_row["latest_height"],
            "watermark_validator_count": int(watermark_row["validator_count"]),
            "watermark_latest_height": watermark_row["latest_height"],
            "rollback_signing_protected": True,
            "signature_verified_before_persist": True,
            "stored_signature_verified_before_replay": True,
            "canonical_payload_binding_enforced": True,
            "signer_provider_errors_sanitized": True,
            "startup_integrity_check": "PASS",
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

    def _restore_watermarks(self) -> None:
        """Backfill monotonic watermarks for journals created by schema v1."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                INSERT INTO validator_watermarks (validator_id, height, round)
                SELECT signatures.validator_id, signatures.height, signatures.round
                FROM consensus_signatures AS signatures
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM consensus_signatures AS newer
                    WHERE newer.validator_id = signatures.validator_id
                      AND (
                          newer.height > signatures.height
                          OR (
                              newer.height = signatures.height
                              AND newer.round > signatures.round
                          )
                      )
                )
                ON CONFLICT(validator_id) DO UPDATE SET
                    height=excluded.height,
                    round=excluded.round
                WHERE excluded.height > validator_watermarks.height
                   OR (
                       excluded.height = validator_watermarks.height
                       AND excluded.round > validator_watermarks.round
                   )
                """
            )
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            self.connection.close()
            raise

    @staticmethod
    def _call_signer(signer: VoteSigner) -> bytes:
        try:
            return signer()
        except Exception as exc:
            raise ConsensusSigningJournalError(
                "consensus signer provider call failed"
            ) from exc

    @staticmethod
    def _verify_signature(
        signature: bytes,
        verifier: VoteSignatureVerifier,
    ) -> None:
        try:
            verified = verifier(signature)
        except Exception as exc:
            raise ConsensusSigningJournalError(
                "consensus signature verification failed"
            ) from exc
        if verified is not True:
            raise ConsensusSigningJournalError(
                "consensus signature verification failed"
            )

    def _validate_signing_payload(
        self,
        *,
        validator_id: str,
        height: int,
        round: int,
        block_hash: str,
        signing_payload: bytes,
    ) -> None:
        expected = json.dumps(
            {
                "block_hash": block_hash,
                "chain_id": self.chain_id,
                "height": height,
                "round": round,
                "validator_id": validator_id,
                "vote_type": "PRECOMMIT",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if signing_payload != expected:
            raise ConsensusSigningJournalError(
                "signing_payload does not match canonical consensus vote"
            )
