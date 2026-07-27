#!/usr/bin/env python3
"""Backfill one corroborated legacy finality certificate into durable state.

The legacy public-testnet runtime persisted the certificate hash in ``blocks``
but did not persist the certificate body.  The immutable runtime restores its
last certificate from ``finality_certificates``.  This gate writes no chain
state and invents no certificate: it accepts only an exact certificate body
observed independently on at least two validators and already bound to the
durable finalized head by its certificate hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Mapping


CHAIN_ID = 20260723
NETWORK = "Public Testnet / No Monetary Value"
VALIDATOR_IDS = ["validator-01", "validator-02", "validator-03"]
HASH = re.compile(r"^0x[0-9a-f]{64}$")
INSTANCE_ID = re.compile(r"^i-[0-9a-f]{8,17}$")
CERTIFICATE_FIELDS = {
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
REQUEST_FIELDS = {
    "schema_version",
    "network",
    "chain_id",
    "head_height",
    "head_hash",
    "certificate_hash",
    "certificate",
    "corroborating_observations",
    "mainnet_changed",
    "assets_moved",
    "bridge_activated",
}
OBSERVATION_FIELDS = {
    "instance_id",
    "validator_id",
    "head_height",
    "head_hash",
    "certificate_hash",
    "certificate",
}


class BackfillError(ValueError):
    """Raised when recovery evidence or durable state fails closed."""


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackfillError("backfill request is unreadable") from exc
    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise BackfillError("backfill request fields are invalid")
    if (
        value["schema_version"]
        != "junca-finality-certificate-backfill-request/v1"
        or value["network"] != NETWORK
        or value["chain_id"] != CHAIN_ID
        or value["mainnet_changed"] is not False
        or value["assets_moved"] is not False
        or value["bridge_activated"] is not False
    ):
        raise BackfillError("backfill request boundary is invalid")
    height = value["head_height"]
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise BackfillError("backfill head height is invalid")
    require_hash(value["head_hash"], "backfill head hash")
    require_hash(value["certificate_hash"], "backfill certificate hash")
    certificate = validate_certificate(value["certificate"])
    if (
        certificate["height"] != height
        or certificate["block_hash"] != value["head_hash"]
        or certificate["certificate_hash"] != value["certificate_hash"]
    ):
        raise BackfillError("backfill certificate does not bind requested head")

    observations = value["corroborating_observations"]
    if not isinstance(observations, list) or len(observations) < 2:
        raise BackfillError("two corroborating validator observations are required")
    instance_ids: set[str] = set()
    validator_ids: set[str] = set()
    expected_certificate = canonical_json(certificate)
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != OBSERVATION_FIELDS:
            raise BackfillError("corroborating observation fields are invalid")
        instance_id = observation["instance_id"]
        validator_id = observation["validator_id"]
        if (
            not isinstance(instance_id, str)
            or INSTANCE_ID.fullmatch(instance_id) is None
            or instance_id in instance_ids
            or validator_id not in VALIDATOR_IDS
            or validator_id in validator_ids
        ):
            raise BackfillError("corroborating validator identities are invalid")
        instance_ids.add(instance_id)
        validator_ids.add(validator_id)
        observed_certificate = validate_certificate(observation["certificate"])
        if (
            observation["head_height"] != height
            or observation["head_hash"] != value["head_hash"]
            or observation["certificate_hash"] != value["certificate_hash"]
            or canonical_json(observed_certificate) != expected_certificate
        ):
            raise BackfillError("corroborating observations do not agree")
    return value


def validate_certificate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CERTIFICATE_FIELDS:
        raise BackfillError("finality certificate fields are invalid")
    if (
        value["schema_version"] != "junca-finality-certificate/v1"
        or value["chain_id"] != CHAIN_ID
        or value["finality_status"] != "FINALIZED"
        or value["mainnet_changed"] is not False
        or value["assets_moved"] is not False
        or value["bridge_activated"] is not False
    ):
        raise BackfillError("finality certificate boundary is invalid")
    for field in ("chain_id", "height", "round", "signed_power", "total_power"):
        if isinstance(value[field], bool) or not isinstance(value[field], int):
            raise BackfillError("finality certificate integer fields are invalid")
    if (
        value["height"] <= 0
        or value["round"] < 0
        or value["signed_power"] != 3
        or value["total_power"] != 3
        or value["validator_ids"] != VALIDATOR_IDS
        or not isinstance(value["vote_hashes"], list)
        or len(value["vote_hashes"]) != 3
        or len(set(value["vote_hashes"])) != 3
    ):
        raise BackfillError("finality certificate quorum is invalid")
    require_hash(value["block_hash"], "certificate block hash")
    require_hash(value["certificate_hash"], "certificate hash")
    for vote_hash in value["vote_hashes"]:
        require_hash(vote_hash, "certificate vote hash")
    body = {
        "block_hash": value["block_hash"],
        "chain_id": value["chain_id"],
        "height": value["height"],
        "round": value["round"],
        "signed_power": value["signed_power"],
        "total_power": value["total_power"],
        "validator_ids": value["validator_ids"],
        "vote_hashes": value["vote_hashes"],
    }
    expected = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + canonical_json(body).encode("utf-8")
    ).hexdigest()
    if value["certificate_hash"] != expected:
        raise BackfillError("finality certificate hash mismatch")
    return value


def require_hash(value: Any, label: str) -> None:
    if not isinstance(value, str) or HASH.fullmatch(value) is None:
        raise BackfillError(f"{label} is invalid")


def require_regular_database(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise BackfillError("state database is unreadable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise BackfillError("state database must be a regular non-symlink file")


def validate_certificate_table(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name='finality_certificates'
        """
    ).fetchone()
    if row is None:
        return False
    columns = connection.execute(
        "PRAGMA table_info(finality_certificates)"
    ).fetchall()
    column_shape = [
        (
            item["name"],
            item["type"].upper(),
            int(item["notnull"]),
            int(item["pk"]),
        )
        for item in columns
    ]
    if column_shape != [
        ("height", "INTEGER", 0, 1),
        ("certificate_json", "TEXT", 1, 0),
    ]:
        raise BackfillError("finality certificate table schema is invalid")
    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(finality_certificates)"
    ).fetchall()
    if len(foreign_keys) != 1:
        raise BackfillError("finality certificate table foreign key is invalid")
    foreign_key = foreign_keys[0]
    if (
        foreign_key["table"] != "blocks"
        or foreign_key["from"] != "height"
        or foreign_key["to"] != "height"
    ):
        raise BackfillError("finality certificate table foreign key is invalid")
    return True


def backfill(database: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    require_regular_database(database)
    certificate_json = canonical_json(request["certificate"])
    connection = sqlite3.connect(
        str(database),
        isolation_level=None,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackfillError("state database quick_check failed")
        metadata = connection.execute(
            "SELECT value FROM metadata WHERE key='chain_id'"
        ).fetchone()
        if metadata is None or metadata["value"] != str(CHAIN_ID):
            raise BackfillError("state database chain_id is invalid")
        connection.execute("BEGIN EXCLUSIVE")
        try:
            head = connection.execute(
                """
                SELECT height,block_hash,finalized,certificate_hash
                FROM blocks ORDER BY height DESC LIMIT 1
                """
            ).fetchone()
            if (
                head is None
                or head["height"] != request["head_height"]
                or head["block_hash"] != request["head_hash"]
                or head["finalized"] != 1
                or head["certificate_hash"] != request["certificate_hash"]
            ):
                raise BackfillError(
                    "durable finalized head does not match backfill evidence"
                )
            if not validate_certificate_table(connection):
                connection.execute(
                    """
                    CREATE TABLE finality_certificates(
                      height INTEGER PRIMARY KEY,
                      certificate_json TEXT NOT NULL,
                      FOREIGN KEY(height) REFERENCES blocks(height)
                    )
                    """
                )
            existing = connection.execute(
                """
                SELECT certificate_json FROM finality_certificates
                WHERE height=?
                """,
                (request["head_height"],),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO finality_certificates(height,certificate_json)
                    VALUES(?,?)
                    """,
                    (request["head_height"], certificate_json),
                )
                state = "BACKFILLED"
            elif existing["certificate_json"] == certificate_json:
                state = "ALREADY_BACKFILLED"
            else:
                raise BackfillError(
                    "conflicting finality certificate body already exists"
                )
            persisted = connection.execute(
                """
                SELECT certificate_json FROM finality_certificates
                WHERE height=?
                """,
                (request["head_height"],),
            ).fetchone()
            if persisted is None or persisted["certificate_json"] != certificate_json:
                raise BackfillError("finality certificate readback failed")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        os.sync()
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackfillError("state database post-write quick_check failed")
    finally:
        connection.close()
    return {
        "schema_version": "junca-finality-certificate-backfill-result/v1",
        "state": state,
        "chain_id": CHAIN_ID,
        "head_height": request["head_height"],
        "head_hash": request["head_hash"],
        "certificate_hash": request["certificate_hash"],
        "request_sha256": hashlib.sha256(
            canonical_json(request).encode("utf-8")
        ).hexdigest(),
        "corroborating_validator_count": len(
            request["corroborating_observations"]
        ),
        "write_scope": "finality_certificate_schema_and_head_body_only",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        request = load_request(args.request)
        result = backfill(args.database, request)
    except (BackfillError, OSError, sqlite3.Error) as exc:
        raise SystemExit(f"certificate backfill rejected: {exc}") from exc
    output = canonical_json(result) + "\n"
    if args.result is None:
        print(output, end="")
    else:
        args.result.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
