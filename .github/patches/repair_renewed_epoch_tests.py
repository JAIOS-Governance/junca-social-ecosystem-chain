#!/usr/bin/env python3
"""Update legacy Foundation epoch assertions for governed expiry renewal."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    observed = text.count(old)
    if observed != count:
        raise SystemExit(f"{label}: expected {count} matches, observed {observed}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: repair_renewed_epoch_tests.py REPO")
    path = (
        Path(sys.argv[1]).resolve()
        / "tests/test_junca_social_ecosystem_chain_aws_foundation.py"
    )
    text = path.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        '"Generate one-time shared automatic finality epoch"',
        '"Generate or renew the shared automatic finality epoch"',
        2,
        "epoch workflow name",
    )
    text = replace_exact(
        text,
        '            "A resume reuses this exact epoch",\n',
        '            "RENEW_EXPIRED_QUIESCED_EPOCH",\n'
        '            "prior_bootstrap_epochs=",\n'
        '            "ROLLING_EPOCH_RENEWAL_PERFORMED",\n',
        1,
        "renewal workflow assertions",
    )
    text = replace_exact(
        text,
        '            ".automatic_finality == {",\n',
        '            ".automatic_finality.slot_epoch_seconds ==",\n'
        '            "terraform_bootstrap.slot_epoch_seconds",\n'
        '            "epoch_renewal:",\n',
        1,
        "renewal evidence assertions",
    )
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
