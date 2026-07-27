from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE_SCRIPT = ROOT / "scripts" / "junca_migrate_validator_state_node.sh"
BACKFILL_SCRIPT = ROOT / "scripts" / "junca_finality_certificate_backfill.py"
SPEC = importlib.util.spec_from_file_location(
    "certificate_backfill_resume_test", BACKFILL_SCRIPT
)
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
    return {
        "schema_version": "junca-finality-certificate-backfill-request/v1",
        "network": "Public Testnet / No Monetary Value",
        "chain_id": CHAIN_ID,
        "head_height": 1,
        "head_hash": HEAD_HASH,
        "certificate_hash": finality["certificate_hash"],
        "certificate": finality,
        "corroborating_observations": [
            {
                "instance_id": f"i-0123456789abcde{index}",
                "validator_id": f"validator-0{index}",
                "head_height": 1,
                "head_hash": HEAD_HASH,
                "certificate_hash": finality["certificate_hash"],
                "certificate": copy.deepcopy(finality),
            }
            for index in (2, 3)
        ],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def extract_shell_function(name: str) -> str:
    lines = NODE_SCRIPT.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index(f"{name}() {{\n")
    for end in range(start + 1, len(lines)):
        if lines[end] == "}\n":
            return "".join(lines[start : end + 1])
    raise AssertionError(f"unterminated shell function: {name}")


class ValidatorStateMigrationResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        self.create_legacy_database(self.source / "state.sqlite")
        (self.source / "node.identity").write_text(
            "validator-01\n", encoding="utf-8"
        )
        shutil.copytree(
            self.source,
            self.target,
            copy_function=shutil.copy2,
        )
        shutil.copystat(self.source, self.target)
        self.request_path = self.root / "backfill-request.json"
        self.request_path.write_text(
            json.dumps(request()), encoding="utf-8"
        )
        self.recovery = backfill.load_request(self.request_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def create_legacy_database(database: Path) -> None:
        finality = certificate()
        connection = sqlite3.connect(database)
        connection.executescript(
            """
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
        connection.executemany(
            "INSERT INTO metadata(key,value) VALUES(?,?)",
            (("chain_id", str(CHAIN_ID)), ("base_height", "1")),
        )
        connection.execute(
            "INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?)",
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

    def run_legacy_equivalence(
        self,
        target_database: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if target_database is None:
            target_database = self.target / "state.sqlite"
        program = (
            "set -euo pipefail\n"
            + extract_shell_function("verify_legacy_sqlite_equivalence")
            + 'verify_legacy_sqlite_equivalence "$1" "$2"\n'
        )
        return subprocess.run(
            [
                "bash",
                "-c",
                program,
                "resume-equivalence",
                str(self.source / "state.sqlite"),
                str(target_database),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def write_non_state_manifests(
        self,
    ) -> tuple[
        subprocess.CompletedProcess[str],
        Path,
        Path,
    ]:
        source_manifest = self.root / "source.metadata.json"
        target_manifest = self.root / "target.metadata.json"
        program = (
            "set -euo pipefail\n"
            + extract_shell_function("write_metadata_manifest")
            + 'write_metadata_manifest "$1" "$3" exclude-state\n'
            + 'write_metadata_manifest "$2" "$4" exclude-state\n'
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                program,
                "resume-manifest",
                str(self.source),
                str(self.target),
                str(source_manifest),
                str(target_manifest),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        return completed, source_manifest, target_manifest

    def run_non_state_manifest_comparison(
        self,
    ) -> subprocess.CompletedProcess[str]:
        written, source_manifest, target_manifest = (
            self.write_non_state_manifests()
        )
        if written.returncode != 0:
            return written
        return subprocess.run(
            ["cmp", str(source_manifest), str(target_manifest)],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_resume_accepts_already_backfilled_target_when_legacy_state_matches(
        self,
    ) -> None:
        first = backfill.backfill(
            self.target / "state.sqlite", self.recovery
        )
        second = backfill.backfill(
            self.target / "state.sqlite", self.recovery
        )

        self.assertEqual(first["state"], "BACKFILLED")
        self.assertEqual(second["state"], "ALREADY_BACKFILLED")
        equivalence = self.run_legacy_equivalence()
        self.assertEqual(equivalence.returncode, 0, equivalence.stderr)
        manifest = self.run_non_state_manifest_comparison()
        self.assertEqual(manifest.returncode, 0, manifest.stderr)

    def test_resume_rejects_blocks_drift(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        connection = sqlite3.connect(self.target / "state.sqlite")
        connection.execute("UPDATE blocks SET gas_used=1 WHERE height=1")
        connection.commit()
        connection.close()

        completed = self.run_legacy_equivalence()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("blocks rows changed during backfill", completed.stderr)

    def test_resume_rejects_extra_target_table(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        connection = sqlite3.connect(self.target / "state.sqlite")
        connection.execute("CREATE TABLE unexpected(value TEXT)")
        connection.commit()
        connection.close()

        completed = self.run_legacy_equivalence()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backfilled target state schema is unexpected",
            completed.stderr,
        )

    def test_resume_rejects_extra_trigger_view_and_non_auto_index(self) -> None:
        objects = {
            "trigger": (
                "CREATE TRIGGER unexpected_trigger AFTER UPDATE ON blocks "
                "BEGIN SELECT 1; END"
            ),
            "view": "CREATE VIEW unexpected_view AS SELECT * FROM blocks",
            "index": "CREATE INDEX unexpected_index ON blocks(gas_used)",
        }
        for object_type, statement in objects.items():
            with self.subTest(object_type=object_type):
                target_database = self.root / f"{object_type}.sqlite"
                shutil.copy2(
                    self.source / "state.sqlite",
                    target_database,
                )
                backfill.backfill(target_database, self.recovery)
                connection = sqlite3.connect(target_database)
                connection.execute(statement)
                connection.commit()
                connection.close()

                completed = self.run_legacy_equivalence(target_database)

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    "target SQLite objects differ from legacy source",
                    completed.stderr,
                )

    def test_exclude_state_manifest_allows_only_target_root_mtime_drift(
        self,
    ) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        target_stat = self.target.stat()
        os.utime(
            self.target,
            ns=(
                target_stat.st_atime_ns,
                target_stat.st_mtime_ns + 5_000_000_000,
            ),
        )

        completed = self.run_non_state_manifest_comparison()

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_exclude_state_manifest_rejects_non_state_mode_drift(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        (self.target / "node.identity").chmod(0o600)

        completed = self.run_non_state_manifest_comparison()

        self.assertNotEqual(completed.returncode, 0)

    def test_exclude_state_manifest_rejects_non_state_uid_drift(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        target_file = self.target / "node.identity"
        current_uid = target_file.stat().st_uid
        try:
            os.chown(target_file, current_uid + 1, -1)
        except OSError:
            written, source_manifest, target_manifest = (
                self.write_non_state_manifests()
            )
            self.assertEqual(written.returncode, 0, written.stderr)
            source_entries = json.loads(
                source_manifest.read_text(encoding="utf-8")
            )
            target_entries = json.loads(
                target_manifest.read_text(encoding="utf-8")
            )
            source_node_entry = next(
                entry
                for entry in source_entries
                if entry["path"] == "node.identity"
            )
            node_entry = next(
                entry
                for entry in target_entries
                if entry["path"] == "node.identity"
            )
            self.assertEqual(
                source_node_entry["uid"],
                (self.source / "node.identity").stat().st_uid,
            )
            self.assertEqual(node_entry["uid"], source_node_entry["uid"])
            node_entry["uid"] += 1
            target_manifest.write_text(
                json.dumps(
                    target_entries,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["cmp", str(source_manifest), str(target_manifest)],
                check=False,
                text=True,
                capture_output=True,
            )
        else:
            completed = self.run_non_state_manifest_comparison()

        self.assertNotEqual(completed.returncode, 0)

    def test_exclude_state_manifest_rejects_non_state_xattr_drift(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        target_file = self.target / "node.identity"
        try:
            os.setxattr(target_file, "user.junca-resume-test", b"drift")
        except OSError as error:
            self.skipTest(f"test filesystem does not support user xattrs: {error}")

        completed = self.run_non_state_manifest_comparison()

        self.assertNotEqual(completed.returncode, 0)

    def test_resume_rejects_non_state_file_drift(self) -> None:
        backfill.backfill(self.target / "state.sqlite", self.recovery)
        (self.target / "unexpected.txt").write_text(
            "drift\n", encoding="utf-8"
        )

        completed = self.run_non_state_manifest_comparison()

        self.assertNotEqual(completed.returncode, 0)

    def test_failure_while_service_stopped_restarts_validator(self) -> None:
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        call_log = self.root / "systemctl.calls"
        systemctl = fake_bin / "systemctl"
        systemctl.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >>"$SYSTEMCTL_CALL_LOG"\n',
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        mountpoint = fake_bin / "mountpoint"
        mountpoint.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        mountpoint.chmod(0o755)
        temporary_mount = self.root / "temporary-mount"
        program = (
            "set -euo pipefail\n"
            + extract_shell_function("rollback")
            + "root_path_moved=false\n"
            + "service_stopped=true\n"
            + "phase=verify\n"
            + f"temporary_mount={temporary_mount!s}\n"
            + "trap 'rollback \"$?\" \"$LINENO\" \"$BASH_COMMAND\"' ERR EXIT\n"
            + "false\n"
            + "service_stopped=false\n"
        )
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["SYSTEMCTL_CALL_LOG"] = str(call_log)

        completed = subprocess.run(
            ["bash", "-c", program],
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            call_log.read_text(encoding="utf-8"),
            "start junca-validator\n",
        )
        self.assertIn(
            "JUNCA_MIGRATION_FAILURE phase=verify",
            completed.stderr,
        )
        self.assertIn("status=1", completed.stderr)
        self.assertIn("command=false", completed.stderr)


if __name__ == "__main__":
    unittest.main()
