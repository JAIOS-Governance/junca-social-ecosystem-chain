#!/usr/bin/env python3
"""Second-route deterministic identity patch with structural bootstrap replacement."""

from __future__ import annotations

import apply_deterministic_identity_patch as base


def patch_user_data_structurally() -> None:
    text = base.USER_DATA.read_text(encoding="utf-8")
    start_marker = "getent group junca >/dev/null || groupadd --system junca\n"
    end_marker = "install -d -o root -g junca -m 0750 /etc/junca\n"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0 or end <= start:
        raise SystemExit(
            "USER_DATA_IDENTITY_BOUNDARY_MISSING "
            f"start={start} end={end}"
        )

    replacement = (
        "getent group junca >/dev/null || "
        "groupadd --system --gid 992 junca\n"
        "test \"$(getent group junca | cut -d: -f3)\" = \"992\"\n"
        "id -u junca >/dev/null 2>&1 || "
        "useradd --system --uid 992 --gid 992 "
        "--home-dir /var/lib/junca --shell /sbin/nologin "
        "--no-create-home junca\n"
        "test \"$(id -u junca)\" = \"992\"\n"
        "test \"$(id -g junca)\" = \"992\"\n"
    )
    updated = text[:start] + replacement + text[end:]
    if updated.count("groupadd --system --gid 992 junca") != 1:
        raise SystemExit("USER_DATA_DETERMINISTIC_GROUP_COUNT_INVALID")
    if updated.count("useradd --system --uid 992 --gid 992") != 1:
        raise SystemExit("USER_DATA_DETERMINISTIC_USER_COUNT_INVALID")
    base.USER_DATA.write_text(updated, encoding="utf-8")


def main() -> None:
    base.patch_foundation()
    base.patch_component()
    patch_user_data_structurally()
    base.write_test()


if __name__ == "__main__":
    main()
