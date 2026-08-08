#!/usr/bin/env python3
"""Repair Bash parameter expansion for renewed Foundation epoch variables."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, observed {count}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_foundation_renewal_env_expansion.py REPO")
    root = Path(sys.argv[1]).resolve()
    script = root / "scripts/junca_public_testnet_foundation.sh"
    text = script.read_text(encoding="utf-8")
    replacements = (
        (
            '''  validator_bootstrap_slot_epochs_json="${
    VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"
''',
            '''  validator_bootstrap_slot_epochs_json="${VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"
''',
            "bootstrap epochs expansion",
        ),
        (
            '''  rolling_resume_prior_slot_epoch_seconds="${
    ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"
''',
            '''  rolling_resume_prior_slot_epoch_seconds="${ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"
''',
            "prior epoch expansion",
        ),
        (
            '''  rolling_epoch_renewal_performed="${
    ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"
''',
            '''  rolling_epoch_renewal_performed="${ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"
''',
            "renewal flag expansion",
        ),
        (
            '''  rolling_epoch_renewal_prefix_count="${
    ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"
''',
            '''  rolling_epoch_renewal_prefix_count="${ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"
''',
            "renewal prefix expansion",
        ),
    )
    for old, new, label in replacements:
        text = replace_once(text, old, new, label)
    if '"${\n' in text:
        raise SystemExit("multiline Bash parameter expansion remains")
    script.write_text(text, encoding="utf-8")

    tests = root / "tests/test_junca_social_ecosystem_chain_aws_foundation.py"
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            )

    def test_durable_state_mount_is_exact_existing_and_fail_closed(self) -> None:
''',
        '''            )

    def test_foundation_renewal_env_expansions_are_single_line_bash(self) -> None:
        for required in (
            'validator_bootstrap_slot_epochs_json="${VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"',
            'rolling_resume_prior_slot_epoch_seconds="${ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"',
            'rolling_epoch_renewal_performed="${ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"',
            'rolling_epoch_renewal_prefix_count="${ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"',
        ):
            self.assertIn(required, self.foundation_script)
        self.assertNotIn('"${\\n', self.foundation_script)

    def test_durable_state_mount_is_exact_existing_and_fail_closed(self) -> None:
''',
        "renewal Bash regression test",
    )
    tests.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
