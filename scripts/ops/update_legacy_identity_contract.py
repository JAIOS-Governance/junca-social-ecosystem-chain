#!/usr/bin/env python3
"""Replace the obsolete dynamic-allocation identity test with the migration contract."""

from __future__ import annotations

from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tests/test_junca_social_ecosystem_chain_aws_foundation.py"
START = "    def test_legacy_system_identity_repair_is_exact_and_fail_closed(self) -> None:\n"
END = "\n    def test_system_identity_repair_follows_the_controlled_stop"


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    start = text.find(START)
    end = text.find(END, start)
    if start < 0 or end < 0:
        raise SystemExit(f"IDENTITY_TEST_BOUNDARY_MISSING start={start} end={end}")

    source = textwrap.dedent(
        '''
        def test_legacy_system_identity_repair_is_exact_and_fail_closed(self) -> None:
            remote = validator_service_recovery_remote_script(
                self.foundation_script
            )
            start = remote.index("verify_junca_system_identity() {")
            end = remote.index(
                "\\n\\nverify_durable_mount_persistence_contract", start
            )
            functions = remote[start:end]
            normalized = " ".join(functions.split())
            for required in (
                "groupadd --system --gid 992 junca",
                "groupmod --gid 992 junca",
                "useradd --system --uid 992 --gid 992",
                "--home-dir /var/lib/junca",
                "--shell /sbin/nologin --no-create-home junca",
                "usermod --uid 992 --gid 992 --home /var/lib/junca",
                "JUNCA_SYSTEM_UID_992_COLLISION",
                "JUNCA_SYSTEM_GID_992_COLLISION",
                "JUNCA_SYSTEM_IDENTITY_ACTIVE_PROCESS",
                '[[ "$repair_status_admitted" == true ]]',
                'find "$path" -xdev -uid "$old_uid"',
                'find "$path" -xdev -gid "$old_group_gid"',
            ):
                self.assertIn(required, normalized)
            for forbidden in (
                '[[ -z "$passwd_entry" ]] || return 1',
                "groupadd --system junca",
                "useradd --system --gid junca",
            ):
                self.assertNotIn(forbidden, normalized)
        '''
    ).lstrip()
    replacement = textwrap.indent(source, "    ")
    PATH.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


if __name__ == "__main__":
    main()
