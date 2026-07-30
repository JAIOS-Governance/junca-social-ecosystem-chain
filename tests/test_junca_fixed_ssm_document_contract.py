from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts.junca_fixed_ssm_document_contract import (
    CANONICAL_DOCUMENT_SHA256,
    CANONICAL_SHELL_SHA256,
    ContractError,
    DOCUMENT_SPECS,
    extract_shell,
    load_document_text,
    validate_contract,
    validate_document_text,
    validate_invocation,
)


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_ROOT = ROOT / "infrastructure/aws/ssm-documents"
CALLER = ROOT / "scripts/junca_fixed_ssm_caller.sh"
RUNBOOK = (
    ROOT / "docs/runbooks/junca-public-testnet-fixed-ssm-launch-design.md"
)
SHA256 = "a" * 64
GENESIS_SHA256 = "b" * 64
NOW = 1_000_000
FUTURE_ALIGNED_EPOCH = 1_000_020


def document_text(name: str) -> str:
    return (DOCUMENT_ROOT / f"{name}.yaml").read_text(encoding="utf-8")


def document_shell(name: str) -> str:
    text = document_text(name)
    return extract_shell(load_document_text(text, label=name), label=name)


def health_fixture() -> dict[str, object]:
    block_hash = "0x" + ("b" * 64)
    vote_hashes = [
        "0x" + ("1" * 64),
        "0x" + ("2" * 64),
        "0x" + ("3" * 64),
    ]
    certificate_body = {
        "block_hash": block_hash,
        "chain_id": 20260723,
        "height": 1,
        "round": 0,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "vote_hashes": vote_hashes,
    }
    canonical_body = json.dumps(
        certificate_body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    certificate_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00" + canonical_body
    ).hexdigest()
    certificate = {
        "schema_version": "junca-finality-certificate/v1",
        "chain_id": 20260723,
        "height": 1,
        "round": 0,
        "block_hash": block_hash,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "vote_hashes": vote_hashes,
        "certificate_hash": certificate_hash,
        "finality_status": "FINALIZED",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    return {
        "status": "healthy",
        "network": "Public Testnet / No Monetary Value",
        "chain_id": 20260723,
        "validator_id": "validator-01",
        "head_height": 1,
        "head_hash": block_hash,
        "head_timestamp": 1_800_000_000,
        "peer_count": 2,
        "automatic_finality_enabled": False,
        "block_interval_seconds": 0,
        "slot_epoch_seconds": 0,
        "automatic_finality_loop_running": False,
        "consensus": {
            "last_certificate_hash": certificate_hash,
            "last_certificate": certificate,
        },
        "private_key_material_accepted": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def health_readback_filter() -> str:
    script = document_shell("JuncaPTHealthReadback")
    match = re.search(
        r"/usr/bin/jq -ce '\n(?P<filter>.*?)\n\s+' <<<\"\$health\"",
        script,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("HealthReadback jq filter was not found")
    return match.group("filter")


def run_health_filter(health: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["jq", "-ce", health_readback_filter()],
        input=json.dumps(health),
        text=True,
        capture_output=True,
        check=False,
    )


def run_certificate_digest(
    certificate: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    script = document_shell("JuncaPTHealthReadback")
    start = script.index("certificate_digest_matches()")
    end = script.index("\n\n", start)
    harness = (
        script[start:end]
        + '\ncertificate_digest_matches "$CERTIFICATE"\n'
    )
    environment = dict(os.environ)
    environment["CERTIFICATE"] = json.dumps(
        certificate,
        sort_keys=True,
        separators=(",", ":"),
    )
    return subprocess.run(
        ["bash", "-c", harness],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def bootstrap_durable_filter() -> str:
    script = document_shell("JuncaPTBootstrapReadiness")
    match = re.search(
        r"/usr/bin/jq -ce '\n(?P<filter>.*?)\n\s+' <<<\"\$durable_raw\"",
        script,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("Bootstrap durable jq filter was not found")
    return match.group("filter")


def run_durable_filter(
    certificate: dict[str, object],
    *,
    height: int | float = 1,
) -> subprocess.CompletedProcess[str]:
    row = {
        "height": height,
        "block_hash": certificate["block_hash"],
        "certificate_hash": certificate["certificate_hash"],
        "certificate_json": json.dumps(
            certificate,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    return subprocess.run(
        ["jq", "-ce", bootstrap_durable_filter()],
        input=json.dumps([row]),
        text=True,
        capture_output=True,
        check=False,
    )


class RepositoryContractTests(unittest.TestCase):
    def test_repository_contract_accepts_exact_six_documents(self) -> None:
        report = validate_contract(DOCUMENT_ROOT)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["document_count"], 6)
        self.assertEqual(
            [item["name"] for item in report["documents"]],
            sorted(DOCUMENT_SPECS),
        )
        self.assertEqual(
            report["status"],
            "REPOSITORY_CONTRACT_ONLY_NOT_DEPLOYED",
        )
        self.assertEqual(
            report["operational_decision"],
            "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        )
        self.assertFalse(report["mainnet_changed"])
        self.assertFalse(report["assets_moved"])
        self.assertFalse(report["bridge_activated"])
        self.assertFalse(report["transaction_submission_enabled"])

    def test_yaml_schema_plugin_and_parameter_surface_are_exact(self) -> None:
        for name, spec in DOCUMENT_SPECS.items():
            with self.subTest(name=name):
                loaded = load_document_text(document_text(name), label=name)
                self.assertEqual(loaded["schemaVersion"], "2.2")
                self.assertEqual(len(loaded["mainSteps"]), 1)
                self.assertEqual(
                    loaded["mainSteps"][0]["action"],
                    "aws:runShellScript",
                )
                self.assertEqual(
                    list(loaded["parameters"]),
                    list(spec["parameters"]),
                )
                for parameter, pattern in spec["parameters"].items():
                    definition = loaded["parameters"][parameter]
                    self.assertEqual(definition["type"], "String")
                    self.assertEqual(definition["allowedPattern"], pattern)
                    self.assertEqual(
                        definition["interpolationType"],
                        "ENV_VAR",
                    )

    def test_dependency_minimal_fresh_runner_contract(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                str(ROOT / "scripts/junca_fixed_ssm_document_contract.py"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["accepted"])

    def test_restart_runbook_describes_allowlisted_journal_metadata(
        self,
    ) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        restart_row = next(
            line
            for line in runbook.splitlines()
            if line.startswith("| `JuncaPTRestartHealth`")
        )
        self.assertIn(
            "allowlisted timestamp, priority, and unit metadata",
            restart_row,
        )
        self.assertIn("at most the final 100 journal entries", restart_row)
        self.assertIn("Journal messages are never returned", restart_row)
        self.assertNotIn("final 100 journal lines", restart_row)

    def test_ssm_sh_invocation_reexecutes_the_fixed_bash_interpreter(
        self,
    ) -> None:
        preamble = "\n".join(
            document_shell("JuncaPTHealthReadback").splitlines()[:5]
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "ssm-script.sh"
            path.write_text(
                preamble + '\nprintf \'%s\\n\' "${BASH_VERSION:-missing}"\n',
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["/bin/sh", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertRegex(completed.stdout.strip(), r"^[0-9]+\.")

    def test_canonical_document_and_shell_digests_are_exact(self) -> None:
        self.assertEqual(set(CANONICAL_DOCUMENT_SHA256), set(DOCUMENT_SPECS))
        self.assertEqual(set(CANONICAL_SHELL_SHA256), set(DOCUMENT_SPECS))
        for name in DOCUMENT_SPECS:
            with self.subTest(name=name):
                text = document_text(name)
                shell = document_shell(name)
                self.assertEqual(
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    CANONICAL_DOCUMENT_SHA256[name],
                )
                self.assertEqual(
                    hashlib.sha256(shell.encode("utf-8")).hexdigest(),
                    CANONICAL_SHELL_SHA256[name],
                )

    def test_every_extracted_shell_passes_bash_n(self) -> None:
        for name in DOCUMENT_SPECS:
            with self.subTest(name=name):
                script = document_shell(name)
                self.assertEqual(
                    script.splitlines()[:5],
                    [
                        "#!/usr/bin/bash",
                        'if [ -z "${BASH_VERSION:-}" ]; then',
                        '  exec /usr/bin/bash "$0" "$@"',
                        "fi",
                        "set -euo pipefail",
                    ],
                )
                completed = subprocess.run(
                    ["bash", "-n"],
                    input=script,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_no_document_mixes_python_or_heredoc_shell(self) -> None:
        for name in DOCUMENT_SPECS:
            with self.subTest(name=name):
                script = document_shell(name)
                self.assertNotRegex(script, r"(?i)\bpython(?:2|3)?\b")
                self.assertNotRegex(script, r"<<-?\s*['\"]?\w+")
                self.assertNotIn("{{", script)
                self.assertNotIn("}}", script)

    def test_all_network_access_is_fixed_localhost_health(self) -> None:
        for name in DOCUMENT_SPECS:
            with self.subTest(name=name):
                script = document_shell(name)
                urls = re.findall(r"https?://[^\s\"']+", script)
                self.assertEqual(
                    set(urls),
                    {"http://127.0.0.1:8545/health"},
                )
                self.assertEqual(script.count("/usr/bin/curl "), 1)
                self.assertIn("--noproxy '*'", script)
                self.assertIn("--proto '=http'", script)
                self.assertIn("--connect-timeout 2 --max-time 5", script)
                self.assertIn('--max-filesize "$MAX_JSON_BYTES"', script)
                self.assertIn(".peer_count == 2", script)

    def test_manifest_digests_and_live_evidence_are_fail_closed(self) -> None:
        manifest = json.loads(
            (DOCUMENT_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["status"],
            "REPOSITORY_CONTRACT_ONLY_NOT_DEPLOYED",
        )
        for entry in manifest["documents"]:
            with self.subTest(name=entry["name"]):
                digest = hashlib.sha256(
                    (DOCUMENT_ROOT / entry["file"]).read_bytes()
                ).hexdigest()
                self.assertEqual(entry["repository_sha256"], digest)
                self.assertIsNone(entry["accepted_live_document_version"])
                self.assertIsNone(entry["accepted_live_content_sha256"])
                self.assertFalse(entry["live_readback_present"])

    def test_manifest_binds_repository_ami_and_defers_live_acceptance(self) -> None:
        manifest = json.loads(
            (DOCUMENT_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        deferred = "\n".join(manifest["not_implemented_by_this_manifest"])
        self.assertIn("JuncaPTReplaceValidator Automation document", deferred)
        self.assertIn("launch-template", deferred)
        self.assertIn("AMI replacement execution role", deferred)
        self.assertIn("live AWS deployment or invocation", deferred)
        self.assertIn("live AMI build and post-reboot", deferred)
        self.assertIn("mutation lock directory", deferred)
        self.assertNotIn("immutable AMI provisioning", deferred)
        self.assertTrue(
            manifest["runtime_lock_contract"]["repository_provisioning_present"]
        )
        self.assertFalse(
            manifest["runtime_lock_contract"]["live_readback_present"]
        )

    def test_read_only_and_mutating_documents_remain_separate(self) -> None:
        expected_mutating = {"JuncaPTFinalitySet", "JuncaPTRestartHealth"}
        actual_mutating = {
            name
            for name, spec in DOCUMENT_SPECS.items()
            if spec["access_class"] == "mutating"
        }
        self.assertEqual(actual_mutating, expected_mutating)
        for name, spec in DOCUMENT_SPECS.items():
            script = document_shell(name)
            if spec["access_class"] == "read-only":
                self.assertNotRegex(
                    script,
                    r"/usr/bin/systemctl\s+(restart|start|stop)",
                )
                self.assertNotRegex(
                    script,
                    r"/usr/bin/(mv|cp|rm|sed\s+-i)\b",
                )

    def test_finality_inspect_separates_preflight_from_exact_epoch_time(
        self,
    ) -> None:
        script = document_shell("JuncaPTFinalityInspect")
        self.assertIn('test "$slot_epoch" -gt 0', script)
        preflight = script[
            script.index('if [[ "$mode" == preflight ]]; then') :
            script.index(
                "fi",
                script.index('if [[ "$mode" == preflight ]]; then'),
            )
        ]
        self.assertIn('test "$slot_epoch" -gt "$request_now_epoch"', preflight)
        self.assertIn(
            'test "$slot_epoch" -le "$((request_now_epoch + 60))"',
            preflight,
        )
        self.assertNotIn(
            'test "$slot_epoch" -gt "$(/usr/bin/date +%s)"',
            script,
        )

    def test_finality_set_preserves_precommit_original(self) -> None:
        script = document_shell("JuncaPTFinalitySet")
        commit = script.index(
            '/usr/bin/mv -f -- "$RUNTIME_CANDIDATE" "$RUNTIME_ENV"'
        )
        backup = script.index('"$RUNTIME_ENV" "$RUNTIME_BACKUP"')
        candidate = script.index('"$RUNTIME_ENV" "$RUNTIME_CANDIDATE"')
        desired_edit = script.index("/usr/bin/sed -i -E")
        prepared = script.index("write_transaction_marker PREPARED")
        mutation_active = script.index("mutation_in_progress=true")
        trap = script.index("trap failure_guard EXIT")
        self.assertLess(backup, candidate)
        self.assertLess(candidate, desired_edit)
        self.assertLess(desired_edit, commit)
        self.assertLess(desired_edit, prepared)
        self.assertLess(prepared, mutation_active)
        self.assertLess(mutation_active, trap)
        self.assertLess(trap, commit)
        self.assertIn('/usr/bin/sync -f "$RUNTIME_BACKUP"', script)
        self.assertIn('/usr/bin/sync -f "$RUNTIME_CANDIDATE"', script)
        self.assertNotIn("/usr/bin/mktemp", script)
        self.assertNotIn(
            '>>"$RUNTIME_ENV"',
            script[:commit],
        )
        sed_starts = [
            match.start()
            for match in re.finditer(r"/usr/bin/sed -i -E", script[:commit])
        ]
        self.assertEqual(len(sed_starts), 3)
        for start in sed_starts:
            command = script[start : start + 240]
            self.assertIn('"$RUNTIME_CANDIDATE"', command)
            self.assertNotIn('\n  "$RUNTIME_ENV"', command)

    def test_finality_set_persists_recoverable_transaction_states(self) -> None:
        script = document_shell("JuncaPTFinalitySet")
        commit = script.index(
            '/usr/bin/mv -f -- "$RUNTIME_CANDIDATE" "$RUNTIME_ENV"'
        )
        prepared = script.index("write_transaction_marker PREPARED")
        accepted = script.index("write_transaction_marker ACCEPTED")
        cleanup = script.index(
            "cleanup_accepted_transaction",
            accepted,
        )
        self.assertLess(prepared, commit)
        self.assertLess(commit, accepted)
        self.assertLess(accepted, cleanup)
        self.assertIn('(.state == "PREPARED" or .state == "ACCEPTED")', script)
        self.assertIn("recover_prepared_transaction()", script)
        self.assertIn(
            '/usr/bin/mv -f -- "$RUNTIME_RECOVERY" "$RUNTIME_ENV"',
            script,
        )
        recovery_function = script[
            script.index("recover_prepared_transaction()") :
            script.index("transaction_artifact_present()")
        ]
        self.assertIn("health_matches_expected", recovery_function)
        self.assertIn('"$transaction_original_enabled"', recovery_function)
        self.assertIn('"$transaction_original_interval"', recovery_function)
        self.assertIn('"$transaction_original_epoch"', recovery_function)
        self.assertIn('/usr/bin/sync -f "$JUNCA_DIRECTORY"', recovery_function)
        self.assertIn('"mutation_rolled_back":true', script)
        self.assertIn(
            '"operational_decision":"BLOCKED_MANUAL_SECURITY_BOOTSTRAP_RECOVERY"',
            script,
        )

    def test_accepted_reentry_revalidates_health_before_cleanup(self) -> None:
        script = document_shell("JuncaPTFinalitySet")
        verification = script[
            script.index("verify_accepted_transaction()") :
            script.index("transaction_artifact_present()")
        ]
        self.assertIn(
            ')" = "$candidate_runtime_env_sha256" || return 1',
            verification,
        )
        self.assertIn("load_candidate_finality", verification)
        self.assertIn("health_matches_expected", verification)
        self.assertIn("/usr/bin/systemctl is-active", verification)
        self.assertIn("/usr/bin/systemctl restart", verification)
        self.assertIn("for accepted_recovery_attempt in {1..60}; do", verification)
        self.assertEqual(script.count("if verify_accepted_transaction &&"), 2)
        for match in re.finditer(
            r"if verify_accepted_transaction &&",
            script,
        ):
            branch = script[match.start() : match.start() + 180]
            self.assertIn("cleanup_accepted_transaction", branch)
            self.assertLess(
                branch.index("verify_accepted_transaction"),
                branch.index("cleanup_accepted_transaction"),
            )

    def test_transaction_reentry_precedes_new_request_validation(self) -> None:
        script = document_shell("JuncaPTFinalitySet")
        marker_reentry = script.index(
            'if [[ -e "$TRANSACTION_MARKER" ||'
        )
        orphan_reentry = script.index("if transaction_artifact_present; then")
        request_read = script.index(
            'expected_artifact="${SSM_ExpectedArtifactSha256}"'
        )
        future_epoch_validation = script.index(
            'test "$slot_epoch" -gt "$request_now_epoch"'
        )
        self.assertLess(marker_reentry, request_read)
        self.assertLess(orphan_reentry, request_read)
        self.assertLess(request_read, future_epoch_validation)

    def test_enabled_acceptance_requires_bounded_epoch_and_new_finality(
        self,
    ) -> None:
        script = document_shell("JuncaPTFinalitySet")
        pre_head = script.index(
            'pre_mutation_head_height="$last_health_head_height"'
        )
        pre_certificate = script.index(
            'pre_mutation_certificate_hash="$last_health_certificate_hash"'
        )
        commit = script.index(
            '/usr/bin/mv -f -- "$RUNTIME_CANDIDATE" "$RUNTIME_ENV"'
        )
        progress = script.index(
            "post_mutation_progress_matches",
            commit,
        )
        accepted = script.index("write_transaction_marker ACCEPTED")
        self.assertLess(pre_head, commit)
        self.assertLess(pre_certificate, commit)
        self.assertLess(commit, progress)
        self.assertLess(progress, accepted)
        self.assertIn(
            'test "$slot_epoch" -le "$((request_now_epoch + 60))"',
            script,
        )
        self.assertIn(
            'test "$last_health_head_height" -gt \\\n'
            '    "$pre_mutation_head_height"',
            script,
        )
        self.assertIn(
            'test "$last_health_head_timestamp" -ge "$slot_epoch"',
            script,
        )
        self.assertIn(
            'test "$last_health_certificate_hash" != \\\n'
            '    "$pre_mutation_certificate_hash"',
            script,
        )

    def test_finality_set_fixed_directory_and_artifacts_are_fail_closed(self) -> None:
        script = document_shell("JuncaPTFinalitySet")
        self.assertIn('readonly JUNCA_DIRECTORY=/etc/junca', script)
        self.assertIn(
            '/usr/bin/stat -c \'%U:%G:%a\' "$JUNCA_DIRECTORY"',
            script,
        )
        self.assertIn(')" = root:root:750', script)
        for path in (
            "/etc/junca/.runtime.env.rollback",
            "/etc/junca/.runtime.env.candidate",
            "/etc/junca/.runtime.env.recovery",
            "/etc/junca/.runtime.env.transaction.json",
            "/etc/junca/.runtime.env.transaction.next",
        ):
            self.assertIn(path, script)

    def test_restart_failure_never_returns_journal_messages(self) -> None:
        script = document_shell("JuncaPTRestartHealth")
        self.assertIn("--no-pager --lines=100 --output=json", script)
        self.assertIn(
            "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT",
            script,
        )
        self.assertIn("journal_message_included: false", script)
        self.assertNotIn("--output=short-iso", script)
        self.assertNotIn(".MESSAGE", script)
        self.assertNotIn("status_output", script)
        self.assertNotIn("journal_output", script)
        self.assertIn("unit_exec_code_available=true", script)
        self.assertIn("unit_exec_status_available=true", script)
        self.assertIn("--argjson exec_main_code", script)
        self.assertIn("--argjson exec_main_status", script)
        self.assertNotIn("--arg exec_main_code", script)
        self.assertIn("journal_metadata_available=true", script)
        self.assertIn("journal_metadata_available=false", script)
        self.assertIn("journal_metadata='[]'", script)
        self.assertIn("if ! [[ \"$unit_active\" =~", script)
        self.assertIn("if ! [[ \"$unit_exec_code\" =~", script)

    def test_mutating_documents_share_the_exact_lock(self) -> None:
        for name in ("JuncaPTFinalitySet", "JuncaPTRestartHealth"):
            with self.subTest(name=name):
                script = document_shell(name)
                self.assertIn(
                    "readonly MUTATION_LOCK_DIRECTORY="
                    "/run/lock/junca-validator-mutation",
                    script,
                )
                self.assertIn(
                    'exec 9<"$MUTATION_LOCK_DIRECTORY"',
                    script,
                )
                self.assertIn(
                    "/usr/bin/flock --exclusive --nonblock 9",
                    script,
                )

    def test_restart_empty_systemd_values_normalize_before_json(self) -> None:
        script = document_shell("JuncaPTRestartHealth")
        self.assertIn(
            'if ! [[ "$unit_active" =~ ^[a-z-]{1,32}$ ]]; then',
            script,
        )
        self.assertIn("unit_active=unavailable", script)
        self.assertIn(
            'if ! [[ "$unit_exec_code" =~ ^[0-9]{1,10}$ ]]; then',
            script,
        )
        self.assertIn("unit_exec_code_available=false", script)
        self.assertIn("unit_exec_status_available=false", script)

    def test_restart_missing_or_oversize_journal_normalizes_to_empty(
        self,
    ) -> None:
        script = document_shell("JuncaPTRestartHealth")
        journal = script[script.index("journal_metadata_available=true") :]
        self.assertIn("journal_metadata_available=false", journal)
        self.assertIn("journal_metadata='[]'", journal)
        self.assertIn(')" -le "$MAX_JSON_BYTES"', journal)
        self.assertIn("length <= 100", journal)
        self.assertLess(
            journal.index("journal_metadata_available=false"),
            journal.index("failure=\"$("),
        )

    def test_health_readback_projects_an_exact_allowlist(self) -> None:
        health = health_fixture()
        health["future_secret_token"] = "must-never-leave-localhost"
        completed = run_health_filter(health)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        projected = json.loads(completed.stdout)
        self.assertNotIn("future_secret_token", projected)
        self.assertEqual(
            set(projected),
            {
                "schema_version",
                "status",
                "network",
                "chain_id",
                "validator_id",
                "head_height",
                "head_hash",
                "head_timestamp",
                "peer_count",
                "automatic_finality_enabled",
                "block_interval_seconds",
                "slot_epoch_seconds",
                "automatic_finality_loop_running",
                "consensus",
                "private_key_material_accepted",
                "mainnet_changed",
                "assets_moved",
                "bridge_activated",
            },
        )

    def test_health_readback_rejects_contradictory_false_flag(self) -> None:
        health = health_fixture()
        health["bridge_activated"] = True
        completed = run_health_filter(health)
        self.assertNotEqual(completed.returncode, 0)

    def test_health_readback_rejects_isolated_peer(self) -> None:
        health = health_fixture()
        health["peer_count"] = 1
        self.assertNotEqual(run_health_filter(health).returncode, 0)

    def test_health_readback_rejects_duplicate_or_extra_certificate_fields(
        self,
    ) -> None:
        duplicate = health_fixture()
        duplicate_certificate = duplicate["consensus"]["last_certificate"]
        duplicate_certificate["vote_hashes"][2] = \
            duplicate_certificate["vote_hashes"][1]
        self.assertNotEqual(run_health_filter(duplicate).returncode, 0)

        extra = health_fixture()
        extra["consensus"]["last_certificate"]["future_secret"] = "rejected"
        self.assertNotEqual(run_health_filter(extra).returncode, 0)

    def test_certificate_domain_digest_accepts_exact_and_rejects_forgery(
        self,
    ) -> None:
        health = health_fixture()
        certificate = health["consensus"]["last_certificate"]
        accepted = run_certificate_digest(certificate)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        forged = dict(certificate)
        forged["certificate_hash"] = "0x" + ("f" * 64)
        rejected = run_certificate_digest(forged)
        self.assertNotEqual(rejected.returncode, 0)

    def test_durable_certificate_rejects_fractional_and_invalid_rounds(
        self,
    ) -> None:
        health = health_fixture()
        certificate = health["consensus"]["last_certificate"]
        accepted = run_durable_filter(certificate)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        fractional_height = dict(certificate)
        fractional_height["height"] = 1.5
        self.assertNotEqual(
            run_durable_filter(fractional_height, height=1.5).returncode,
            0,
        )
        fractional_round = dict(certificate)
        fractional_round["round"] = 0.5
        self.assertNotEqual(
            run_durable_filter(fractional_round).returncode,
            0,
        )
        negative_round = dict(certificate)
        negative_round["round"] = -1
        self.assertNotEqual(
            run_durable_filter(negative_round).returncode,
            0,
        )

    def test_raw_health_unknown_fields_are_projected_before_argv_use(self) -> None:
        for name in DOCUMENT_SPECS:
            with self.subTest(name=name):
                script = document_shell(name)
                self.assertNotIn("then . else", script)
                self.assertNotIn('accepted_health="$health"', script)

    def test_runtime_observation_matches_readiness_owner_mode_contracts(
        self,
    ) -> None:
        script = document_shell("JuncaPTRuntimeObservation")
        for owner_mode in (
            "junca:junca:640",
            "root:junca:640",
            "root:root:644",
            "root:root:444",
        ):
            self.assertIn(owner_mode, script)


class DocumentNegativeTests(unittest.TestCase):
    def assert_rejected(
        self,
        name: str,
        changed: str,
        message: str | None = None,
    ) -> None:
        context = self.assertRaises(ContractError)
        with context:
            validate_document_text(name, changed)
        if (
            message is not None
            and "canonical document digest differs"
            not in str(context.exception)
        ):
            self.assertIn(message, str(context.exception))

    def test_duplicate_yaml_key_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        self.assert_rejected(
            "JuncaPTHealthReadback",
            "schemaVersion: '2.2'\n" + original,
            "duplicate YAML key",
        )

    def test_extra_top_level_key_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        self.assert_rejected(
            "JuncaPTHealthReadback",
            original + "\nunexpected: true\n",
            "top-level keys",
        )

    def test_extra_general_command_parameter_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "parameters: {}",
            "parameters:\n"
            "  Commands:\n"
            "    type: String\n"
            "    description: unsafe\n"
            "    allowedPattern: '.*'\n"
            "    interpolationType: ENV_VAR",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "parameter keys/order",
        )

    def test_extra_plugin_input_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "      runCommand:",
            "      timeoutSeconds: '60'\n"
            "      runCommand:",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "plugin inputs",
        )

    def test_duplicate_ssm_environment_key_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalityInspect")
        assignment = '          enabled="${SSM_Enabled}"'
        changed = original.replace(
            assignment,
            assignment + "\n" + assignment,
        )
        self.assert_rejected(
            "JuncaPTFinalityInspect",
            changed,
            "references must be exact and unique",
        )

    def test_unquoted_ssm_environment_key_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalityInspect")
        changed = original.replace(
            'enabled="${SSM_Enabled}"',
            "enabled=$SSM_Enabled",
        )
        self.assert_rejected(
            "JuncaPTFinalityInspect",
            changed,
            "references",
        )

    def test_direct_ssm_interpolation_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalityInspect")
        changed = original.replace(
            'enabled="${SSM_Enabled}"',
            'enabled="{{ Enabled }}"',
        )
        self.assert_rejected(
            "JuncaPTFinalityInspect",
            changed,
            "direct SSM interpolation",
        )

    def test_loosened_allowed_pattern_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalityInspect")
        changed = original.replace(
            "allowedPattern: '^(true|false)$'",
            "allowedPattern: '.*'",
            1,
        )
        self.assert_rejected(
            "JuncaPTFinalityInspect",
            changed,
            "allowedPattern differs",
        )

    def test_missing_env_var_interpolation_type_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalityInspect")
        changed = original.replace(
            "    interpolationType: ENV_VAR",
            "    interpolationType: DEFAULT",
            1,
        )
        self.assert_rejected(
            "JuncaPTFinalityInspect",
            changed,
            "interpolationType must be ENV_VAR",
        )

    def test_python_in_bash_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/python3 -c 'print(1)'",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "Python execution",
        )

    def test_heredoc_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/true <<'PAYLOAD'\n"
            "          fixed\n"
            "          PAYLOAD",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "heredoc",
        )

    def test_remote_url_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "http://127.0.0.1:8545/health",
            "https://example.invalid/health",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "fixed localhost health URL",
        )

    def test_package_install_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/dnf install arbitrary-package",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "package mutation",
        )

    def test_bash_syntax_error_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          if true; then",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "bash -n failed",
        )

    def test_false_safety_flag_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            ".mainnet_changed == false",
            ".mainnet_changed == true",
            1,
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "contradictory mainnet_changed true flag",
        )

    def test_read_only_service_restart_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/systemctl restart junca-validator.service",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "every systemctl call must have a fixed timeout",
        )

    def test_unbounded_output_contract_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          readonly MAX_JSON_BYTES=65536",
            "          readonly MAX_JSON_BYTES=999999",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "bounded JSON output contract",
        )

    def test_shell_builtin_truncation_of_runtime_env_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          : > /etc/junca/runtime.env",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "canonical shell body digest differs",
        )

    def test_bin_cat_ssh_private_key_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /bin/cat /etc/ssh/ssh_host_rsa_key",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "sensitive operating-system path",
        )

    def test_allowlisted_jq_ssh_private_key_read_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/jq -Rs . /etc/ssh/ssh_host_rsa_key",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "sensitive operating-system path",
        )

    def test_allowlisted_command_injection_is_rejected_by_shell_digest(
        self,
    ) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/jq -Rs . /etc/junca/runtime.env",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "canonical shell body digest differs",
        )

    def test_touch_and_arbitrary_redirection_are_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        touch = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          /usr/bin/touch /etc/junca/rogue",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            touch,
            "absolute executable allowlist differs",
        )
        redirect = original.replace(
            "          set -euo pipefail",
            "          set -euo pipefail\n"
            "          echo poisoned > /etc/junca/rogue",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            redirect,
            "canonical shell body digest differs",
        )

    def test_curl_max_time_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalitySet")
        changed = original.replace(
            "--connect-timeout 2 --max-time 5",
            "--connect-timeout 2",
        )
        self.assert_rejected(
            "JuncaPTFinalitySet",
            changed,
            "fixed localhost curl transport/time/size contract differs",
        )

    def test_curl_proxy_or_protocol_guard_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        for fragment in ("--noproxy '*'", "--proto '=http'"):
            with self.subTest(fragment=fragment):
                self.assert_rejected(
                    "JuncaPTHealthReadback",
                    original.replace(fragment, ""),
                    "fixed localhost curl transport/time/size contract differs",
                )

    def test_sqlite_timeout_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTBootstrapReadiness")
        changed = original.replace(
            "/usr/bin/timeout 15 /usr/bin/sqlite3",
            "/usr/bin/sqlite3",
        )
        self.assert_rejected(
            "JuncaPTBootstrapReadiness",
            changed,
            "every sqlite3 call must have a fixed timeout",
        )

    def test_cloud_init_timeout_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTBootstrapReadiness")
        changed = original.replace(
            "/usr/bin/timeout 300 /usr/bin/cloud-init status --wait",
            "/usr/bin/cloud-init status --wait",
        )
        self.assert_rejected(
            "JuncaPTBootstrapReadiness",
            changed,
            "cloud-init readiness must have the fixed timeout",
        )

    def test_systemctl_restart_timeout_change_is_rejected(self) -> None:
        original = document_text("JuncaPTRestartHealth")
        changed = original.replace(
            "/usr/bin/timeout --signal=TERM --kill-after=10 30",
            "/usr/bin/timeout --signal=TERM --kill-after=10 300",
            1,
        )
        self.assert_rejected(
            "JuncaPTRestartHealth",
            changed,
            "canonical shell body digest differs",
        )

    def test_bash_reexec_guard_change_is_rejected(self) -> None:
        original = document_text("JuncaPTHealthReadback")
        changed = original.replace(
            '            exec /usr/bin/bash "$0" "$@"\n',
            "",
        )
        self.assert_rejected(
            "JuncaPTHealthReadback",
            changed,
            "fixed Bash shebang/re-exec/fail-fast preamble differs",
        )

    def test_mutation_lock_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTRestartHealth")
        changed = original.replace(
            "          if ! /usr/bin/flock --exclusive --nonblock 9; then",
            "          if ! true; then",
        )
        self.assert_rejected(
            "JuncaPTRestartHealth",
            changed,
            "absolute executable allowlist differs",
        )

    def test_accepted_reentry_health_gate_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalitySet")
        changed = original.replace(
            "                  if verify_accepted_transaction &&",
            "                  if true &&",
            1,
        )
        self.assert_rejected(
            "JuncaPTFinalitySet",
            changed,
            "canonical shell body digest differs",
        )

    def test_enabled_progress_postcondition_removal_is_rejected(self) -> None:
        original = document_text("JuncaPTFinalitySet")
        changed = original.replace(
            "              post_mutation_progress_matches",
            "              true",
            1,
        )
        self.assert_rejected(
            "JuncaPTFinalitySet",
            changed,
            "canonical shell body digest differs",
        )


class InvocationContractTests(unittest.TestCase):
    def test_cli_accepts_exact_invocation_file_without_pyyaml(self) -> None:
        with TemporaryDirectory() as temporary:
            parameters = Path(temporary) / "parameters.json"
            parameters.write_text(
                json.dumps(
                    {
                        "ExpectedArtifactSha256": SHA256,
                        "Enabled": "false",
                        "BlockIntervalSeconds": "0",
                        "SlotEpochSeconds": "0",
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    str(
                        ROOT
                        / "scripts/junca_fixed_ssm_document_contract.py"
                    ),
                    "--document-name",
                    "JuncaPTFinalitySet",
                    "--parameters-file",
                    str(parameters),
                    "--now-epoch",
                    str(NOW),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        decision = json.loads(completed.stdout)
        self.assertTrue(decision["accepted"])
        self.assertEqual(
            decision["schema_version"],
            "junca-fixed-ssm-invocation-decision/v1",
        )
        self.assertEqual(
            decision["document_name"],
            "JuncaPTFinalitySet",
        )
        self.assertFalse(decision["mainnet_changed"])
        self.assertFalse(decision["assets_moved"])
        self.assertFalse(decision["bridge_activated"])

    def test_cli_rejects_partial_invocation_arguments(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                str(ROOT / "scripts/junca_fixed_ssm_document_contract.py"),
                "--document-name",
                "JuncaPTHealthReadback",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "requires document, parameters, and time",
            completed.stderr,
        )

    def test_valid_disabled_preflight_invocation(self) -> None:
        result = validate_invocation(
            "JuncaPTFinalityInspect",
            {
                "ExpectedArtifactSha256": SHA256,
                "Enabled": "false",
                "BlockIntervalSeconds": "0",
                "SlotEpochSeconds": "0",
                "Mode": "preflight",
                "AllowMissingFinalityKeys": "true",
            },
            now_epoch=NOW,
        )
        self.assertEqual(result["Enabled"], "false")

    def test_valid_enabled_exact_invocation(self) -> None:
        result = validate_invocation(
            "JuncaPTFinalityInspect",
            {
                "ExpectedArtifactSha256": SHA256,
                "Enabled": "true",
                "BlockIntervalSeconds": "30",
                "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH),
                "Mode": "exact",
                "AllowMissingFinalityKeys": "false",
            },
            now_epoch=NOW,
        )
        self.assertEqual(result["SlotEpochSeconds"], str(FUTURE_ALIGNED_EPOCH))

    def test_post_set_past_epoch_exact_inspection_is_valid(self) -> None:
        result = validate_invocation(
            "JuncaPTFinalityInspect",
            {
                "ExpectedArtifactSha256": SHA256,
                "Enabled": "true",
                "BlockIntervalSeconds": "30",
                "SlotEpochSeconds": "999990",
                "Mode": "exact",
                "AllowMissingFinalityKeys": "false",
            },
            now_epoch=NOW,
        )
        self.assertEqual(result["SlotEpochSeconds"], "999990")

    def test_past_epoch_enabled_preflight_inspection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "must be future"):
            validate_invocation(
                "JuncaPTFinalityInspect",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": "999990",
                    "Mode": "preflight",
                    "AllowMissingFinalityKeys": "false",
                },
                now_epoch=NOW,
            )

    def test_far_future_enabled_preflight_inspection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "60-second horizon"):
            validate_invocation(
                "JuncaPTFinalityInspect",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH + 300),
                    "Mode": "preflight",
                    "AllowMissingFinalityKeys": "false",
                },
                now_epoch=NOW,
            )

    def test_valid_finality_set_invocation(self) -> None:
        result = validate_invocation(
            "JuncaPTFinalitySet",
            {
                "ExpectedArtifactSha256": SHA256,
                "Enabled": "true",
                "BlockIntervalSeconds": "30",
                "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH),
            },
            now_epoch=NOW,
        )
        self.assertEqual(result["BlockIntervalSeconds"], "30")

    def test_valid_readiness_and_no_parameter_invocations(self) -> None:
        readiness = validate_invocation(
            "JuncaPTBootstrapReadiness",
            {
                "ValidatorId": "validator-03",
                "ExpectedArtifactSha256": SHA256,
                "ExpectedGenesisSha256": GENESIS_SHA256,
            },
            now_epoch=NOW,
        )
        self.assertEqual(readiness["ValidatorId"], "validator-03")
        for name in ("JuncaPTRestartHealth", "JuncaPTHealthReadback"):
            with self.subTest(name=name):
                self.assertEqual(
                    validate_invocation(name, {}, now_epoch=NOW),
                    {},
                )

    def test_extra_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "parameter keys differ"):
            validate_invocation(
                "JuncaPTHealthReadback",
                {"Commands": "id"},
                now_epoch=NOW,
            )

    def test_missing_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "parameter keys differ"):
            validate_invocation(
                "JuncaPTRuntimeObservation",
                {},
                now_epoch=NOW,
            )

    def test_newline_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "invocation value rejected"):
            validate_invocation(
                "JuncaPTRuntimeObservation",
                {"ValidatorId": "validator-01\nid"},
                now_epoch=NOW,
            )

    def test_shell_metacharacter_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "invocation value rejected"):
            validate_invocation(
                "JuncaPTBootstrapReadiness",
                {
                    "ValidatorId": "validator-01;id",
                    "ExpectedArtifactSha256": SHA256,
                    "ExpectedGenesisSha256": GENESIS_SHA256,
                },
                now_epoch=NOW,
            )

    def test_non_string_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "must be a string"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": False,
                    "BlockIntervalSeconds": "0",
                    "SlotEpochSeconds": "0",
                },
                now_epoch=NOW,
            )

    def test_overlong_epoch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "invocation value rejected"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": "123456789012",
                },
                now_epoch=NOW,
            )

    def test_past_enabled_epoch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "must be future"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": "999990",
                },
                now_epoch=NOW,
            )

    def test_nonaligned_enabled_epoch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "30-second aligned"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": "1000001",
                },
                now_epoch=NOW,
            )

    def test_far_future_finality_set_epoch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "60-second horizon"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH + 300),
                },
                now_epoch=NOW,
            )

    def test_enabled_interval_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "interval must be 30"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "0",
                    "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH),
                },
                now_epoch=NOW,
            )

    def test_disabled_epoch_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "epoch must be zero"):
            validate_invocation(
                "JuncaPTFinalitySet",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "false",
                    "BlockIntervalSeconds": "0",
                    "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH),
                },
                now_epoch=NOW,
            )

    def test_exact_mode_cannot_allow_missing_keys(self) -> None:
        with self.assertRaisesRegex(ContractError, "exact mode"):
            validate_invocation(
                "JuncaPTFinalityInspect",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "false",
                    "BlockIntervalSeconds": "0",
                    "SlotEpochSeconds": "0",
                    "Mode": "exact",
                    "AllowMissingFinalityKeys": "true",
                },
                now_epoch=NOW,
            )

    def test_missing_keys_cannot_enable_finality(self) -> None:
        with self.assertRaisesRegex(ContractError, "missing keys require disabled"):
            validate_invocation(
                "JuncaPTFinalityInspect",
                {
                    "ExpectedArtifactSha256": SHA256,
                    "Enabled": "true",
                    "BlockIntervalSeconds": "30",
                    "SlotEpochSeconds": str(FUTURE_ALIGNED_EPOCH),
                    "Mode": "preflight",
                    "AllowMissingFinalityKeys": "true",
                },
                now_epoch=NOW,
            )


class FixedCallerContractTests(unittest.TestCase):
    COMMAND_ID = "12345678-1234-1234-1234-123456789abc"
    INSTANCE_ID = "i-0123456789abcdef0"
    DOCUMENT_NAME = "JuncaPTHealthReadback"
    DOCUMENT_VERSION = "1"

    def run_caller_function(
        self,
        function_name: str,
        fixture: dict[str, object],
        arguments: list[str],
    ) -> subprocess.CompletedProcess[str]:
        with TemporaryDirectory() as temporary:
            fixture_path = Path(temporary) / "fixture.json"
            fixture_path.write_text(
                json.dumps(fixture),
                encoding="utf-8",
            )
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        "set -euo pipefail\n"
                        f"source {CALLER}\n"
                        f"{function_name} \"$1\" \"${{@:2}}\"\n"
                    ),
                    "caller-contract-test",
                    str(fixture_path),
                    *arguments,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_send_is_exact_instance_bound_after_target_readback(self) -> None:
        caller = CALLER.read_text(encoding="utf-8")
        send = caller.split("junca_fixed_ssm_send_command() {", 1)[1]
        self.assertIn('--instance-ids "$expected_instance_id"', send)
        self.assertNotIn("--targets", send)
        self.assertIn(
            ".Command.InstanceIds == [$expected_instance_id]",
            send,
        )
        self.assertIn(".Command.Targets == []", send)
        self.assertLess(
            send.index("junca_fixed_ssm_validate_target"),
            send.index("aws ssm send-command"),
        )
        self.assertNotIn("AWS-RunShellScript", caller)
        self.assertNotIn("$LATEST", caller)

    def test_runtime_artifact_ci_tracks_and_parses_the_caller(self) -> None:
        workflow = (
            ROOT
            / ".github/workflows/junca-validator-runtime-artifacts.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '- "scripts/junca_fixed_ssm_caller.sh"',
            workflow,
        )
        self.assertIn(
            "bash -n scripts/junca_fixed_ssm_caller.sh",
            workflow,
        )

    def test_repository_only_manifest_blocks_before_aws_read_or_send(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            marker = Path(temporary) / "aws-called"
            completed = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        "set -euo pipefail\n"
                        f"source {CALLER}\n"
                        "aws() { printf called >\"$AWS_MARKER\"; }\n"
                        "if junca_fixed_ssm_validate_document "
                        "JuncaPTHealthReadback \"$1\"; then exit 91; fi\n"
                        "test ! -e \"$AWS_MARKER\"\n"
                    ),
                    "caller-manifest-block-test",
                    temporary,
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "AWS_ACCOUNT_ID": "595710543956",
                    "AWS_REGION": "us-east-1",
                    "JUNCA_PT_HEALTH_READBACK_VERSION": "1",
                    "AWS_MARKER": str(marker),
                },
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "live version is not accepted in manifest",
            completed.stderr,
        )
    def test_list_command_readback_rejects_empty_duplicate_and_mismatch(
        self,
    ) -> None:
        command = {
            "CommandId": self.COMMAND_ID,
            "DocumentName": self.DOCUMENT_NAME,
            "DocumentVersion": self.DOCUMENT_VERSION,
            "InstanceIds": [self.INSTANCE_ID],
            "Targets": [],
            "TargetCount": 1,
        }
        arguments = [
            self.COMMAND_ID,
            self.DOCUMENT_NAME,
            self.DOCUMENT_VERSION,
            self.INSTANCE_ID,
        ]
        accepted = self.run_caller_function(
            "junca_fixed_ssm_validate_list_command_readback",
            {"Commands": [command]},
            arguments,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        rejected = [
            {"Commands": []},
            {"Commands": [command, command]},
            {
                "Commands": [
                    {
                        **command,
                        "CommandId":
                            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    }
                ]
            },
            {
                "Commands": [
                    {
                        **command,
                        "InstanceIds": ["i-11111111111111111"],
                    }
                ]
            },
            {"Commands": [{**command, "TargetCount": 2}]},
        ]
        for fixture in rejected:
            with self.subTest(fixture=fixture):
                result = self.run_caller_function(
                    "junca_fixed_ssm_validate_list_command_readback",
                    fixture,
                    arguments,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_invocation_readback_is_bound_to_exact_command_id(self) -> None:
        fixture = {
            "Status": "Success",
            "CommandId": self.COMMAND_ID,
            "InstanceId": self.INSTANCE_ID,
            "DocumentName": self.DOCUMENT_NAME,
            "DocumentVersion": self.DOCUMENT_VERSION,
            "StandardOutputContent": "{}",
            "StandardErrorContent": "",
        }
        arguments = [
            self.INSTANCE_ID,
            self.DOCUMENT_NAME,
            self.DOCUMENT_VERSION,
            self.COMMAND_ID,
        ]
        accepted = self.run_caller_function(
            "junca_fixed_ssm_validate_invocation_readback",
            fixture,
            arguments,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        mismatch = {
            **fixture,
            "CommandId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        }
        rejected = self.run_caller_function(
            "junca_fixed_ssm_validate_invocation_readback",
            mismatch,
            arguments,
        )
        self.assertNotEqual(rejected.returncode, 0)


class ManifestNegativeTests(unittest.TestCase):
    def fixture_root(self) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        destination = Path(temporary.name) / "ssm-documents"
        shutil.copytree(DOCUMENT_ROOT, destination)
        return destination

    def test_document_digest_drift_is_rejected(self) -> None:
        root = self.fixture_root()
        path = root / "JuncaPTHealthReadback.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ContractError,
            "canonical document digest differs|repository digest differs",
        ):
            validate_contract(root)

    def test_live_version_claim_is_rejected(self) -> None:
        root = self.fixture_root()
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["documents"][0]["accepted_live_document_version"] = "1"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "must not claim a live version"):
            validate_contract(root)

    def test_unblocked_operational_decision_is_rejected(self) -> None:
        root = self.fixture_root()
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["operational_decision"] = "READY"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "must remain blocked"):
            validate_contract(root)

    def test_manifest_true_safety_flag_is_rejected(self) -> None:
        root = self.fixture_root()
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["assets_moved"] = True
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "assets_moved must be false"):
            validate_contract(root)

    def test_seventh_file_is_rejected(self) -> None:
        root = self.fixture_root()
        (root / "JuncaPTArbitraryShell.yaml").write_text(
            "schemaVersion: '2.2'\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "file inventory differs"):
            validate_contract(root)


if __name__ == "__main__":
    unittest.main()
