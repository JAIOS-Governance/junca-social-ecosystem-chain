from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.state_store import PersistentStateStore


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "junca_finality_certificate_backfill.py"
SPEC = importlib.util.spec_from_file_location("certificate_backfill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
backfill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backfill)

CHAIN_ID = 20260723
HEAD_HASH = "0x" + ("a" * 64)
PARENT_HASH = "0x" + ("b" * 64)
STATE_ROOT = "0x" + ("c" * 64)


def certificate() -> dict[str, object]:
    body: dict[str, object] = {
        "block_hash": HEAD_HASH,
        "chain_id": CHAIN_ID,
        "height": 1,
        "round": 0,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "vote_hashes": [
            "0x" + ("1" * 64),
            "0x" + ("2" * 64),
            "0x" + ("3" * 64),
        ],
    }
    certificate_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "junca-finality-certificate/v1",
        **body,
        "certificate_hash": certificate_hash,
        "finality_status": "FINALIZED",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def request() -> dict[str, object]:
    finality = certificate()
    observations = []
    for index in (2, 3):
        observations.append(
            {
                "instance_id": f"i-0123456789abcde{index}",
                "validator_id": f"validator-0{index}",
                "head_height": 1,
                "head_hash": HEAD_HASH,
                "certificate_hash": finality["certificate_hash"],
                "certificate": copy.deepcopy(finality),
            }
        )
    return {
        "schema_version": "junca-finality-certificate-backfill-request/v1",
        "network": "Public Testnet / No Monetary Value",
        "chain_id": CHAIN_ID,
        "head_height": 1,
        "head_hash": HEAD_HASH,
        "certificate_hash": finality["certificate_hash"],
        "certificate": finality,
        "corroborating_observations": observations,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class CertificateBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.database = Path(self.directory.name, "state.sqlite")
        self.create_legacy_database()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def create_legacy_database(self) -> None:
        finality = certificate()
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE metadata(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE blocks(
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
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES('chain_id',?)",
            (str(CHAIN_ID),),
        )
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES('base_height','1')"
        )
        connection.execute(
            """
            INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                1,
                HEAD_HASH,
                PARENT_HASH,
                STATE_ROOT,
                1000,
                0,
                1,
                finality["certificate_hash"],
                "{}",
                "[]",
            ),
        )
        connection.commit()
        connection.close()

    def test_backfills_exact_corroborated_certificate_and_is_idempotent(self) -> None:
        recovery = backfill.load_request(self.write_request(request()))
        first = backfill.backfill(self.database, recovery)
        second = backfill.backfill(self.database, recovery)
        self.assertEqual(first["state"], "BACKFILLED")
        self.assertEqual(second["state"], "ALREADY_BACKFILLED")
        connection = sqlite3.connect(self.database)
        row = connection.execute(
            "SELECT height,certificate_json FROM finality_certificates"
        ).fetchone()
        connection.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], backfill.canonical_json(certificate()))
        current_store = PersistentStateStore(self.database, chain_id=CHAIN_ID)
        self.addCleanup(current_store.close)
        restored = current_store.latest_finality_certificate()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.as_evidence(), certificate())

    def test_rejects_disagreeing_or_duplicate_observers(self) -> None:
        disagreement = request()
        disagreement["corroborating_observations"][1]["head_hash"] = PARENT_HASH
        with self.assertRaisesRegex(
            backfill.BackfillError, "observations do not agree"
        ):
            backfill.load_request(self.write_request(disagreement))

        duplicate = request()
        duplicate["corroborating_observations"][1]["instance_id"] = (
            duplicate["corroborating_observations"][0]["instance_id"]
        )
        with self.assertRaisesRegex(
            backfill.BackfillError, "identities are invalid"
        ):
            backfill.load_request(self.write_request(duplicate))

    def test_rejects_tampered_certificate_body(self) -> None:
        tampered = request()
        tampered["certificate"]["round"] = 1
        for observation in tampered["corroborating_observations"]:
            observation["certificate"]["round"] = 1
        with self.assertRaisesRegex(backfill.BackfillError, "hash mismatch"):
            backfill.load_request(self.write_request(tampered))

    def test_rejects_durable_head_drift_without_writing(self) -> None:
        recovery = backfill.load_request(self.write_request(request()))
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE blocks SET block_hash=? WHERE height=1",
            ("0x" + ("d" * 64),),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(backfill.BackfillError, "does not match"):
            backfill.backfill(self.database, recovery)
        connection = sqlite3.connect(self.database)
        table = connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='finality_certificates'
            """
        ).fetchone()[0]
        connection.close()
        self.assertEqual(table, 0)

    def test_rejects_existing_conflicting_body(self) -> None:
        recovery = backfill.load_request(self.write_request(request()))
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE finality_certificates(
              height INTEGER PRIMARY KEY,
              certificate_json TEXT NOT NULL,
              FOREIGN KEY(height) REFERENCES blocks(height)
            );
            """
        )
        connection.execute(
            "INSERT INTO finality_certificates VALUES(1,'{}')"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(backfill.BackfillError, "conflicting"):
            backfill.backfill(self.database, recovery)

    def test_rejects_symlink_database(self) -> None:
        recovery = backfill.load_request(self.write_request(request()))
        link = Path(self.directory.name, "state-link.sqlite")
        link.symlink_to(self.database)
        with self.assertRaisesRegex(backfill.BackfillError, "non-symlink"):
            backfill.backfill(link, recovery)

    def write_request(self, value: dict[str, object]) -> Path:
        path = Path(self.directory.name, "request.json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
