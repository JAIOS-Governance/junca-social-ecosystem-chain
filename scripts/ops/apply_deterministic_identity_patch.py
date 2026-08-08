#!/usr/bin/env python3
"""Apply the bounded JSEC validator system-identity source repair."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "scripts/junca_public_testnet_foundation.sh"
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
USER_DATA = ROOT / "infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"
TEST = ROOT / "tests/test_junca_deterministic_system_identity.py"


def replace_once(text: str, old: str, new: str, signature: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{signature} count={count}")
    return text.replace(old, new, 1)


def patch_foundation() -> None:
    text = FOUNDATION.read_text(encoding="utf-8")
    old = '''ensure_junca_system_identity() {
  local passwd_entry=""
  local group_entry=""
  local group_name=""
  local group_gid=""
  if verify_junca_system_identity; then
    return 0
  fi
  system_identity_repair_attempted=true
  passwd_entry="$(getent passwd junca 2>/dev/null || true)"
  group_entry="$(getent group junca 2>/dev/null || true)"
  [[ -z "$passwd_entry" ]] || return 1
  if [[ -n "$group_entry" ]]; then
    IFS=: read -r group_name _ group_gid _ <<<"$group_entry"
    [[ "$group_name" == junca && "$group_gid" == 992 ]] || return 1
  else
    [[ -z "$(getent group 992 2>/dev/null || true)" ]] || return 1
    groupadd --system --gid 992 junca || return 1
  fi
  [[ -z "$(getent passwd 992 2>/dev/null || true)" ]] || return 1
  useradd --system --uid 992 --gid 992 --home-dir /var/lib/junca \
    --shell /sbin/nologin --no-create-home junca || return 1
  verify_junca_system_identity || return 1
  system_identity_repaired=true
}
'''
    new = '''ensure_junca_system_identity() {
  local passwd_entry=""
  local group_entry=""
  local occupied_entry=""
  local passwd_name=""
  local old_uid=""
  local old_primary_gid=""
  local old_home=""
  local old_shell=""
  local group_name=""
  local old_group_gid=""
  local path=""
  if verify_junca_system_identity; then
    return 0
  fi
  [[ "$repair_status_admitted" == true ]] || return 1
  system_identity_repair_attempted=true
  passwd_entry="$(getent passwd junca 2>/dev/null || true)"
  group_entry="$(getent group junca 2>/dev/null || true)"

  if [[ -n "$group_entry" ]]; then
    IFS=: read -r group_name _ old_group_gid _ <<<"$group_entry"
    [[ "$group_name" == junca ]] || return 1
    if [[ "$old_group_gid" != 992 ]]; then
      occupied_entry="$(getent group 992 2>/dev/null || true)"
      if [[ -n "$occupied_entry" && "$occupied_entry" != "$group_entry" ]]; then
        echo "JUNCA_SYSTEM_GID_992_COLLISION entry=${occupied_entry%%:*}" >&2
        return 1
      fi
      groupmod --gid 992 junca || return 1
    fi
  else
    occupied_entry="$(getent group 992 2>/dev/null || true)"
    if [[ -n "$occupied_entry" ]]; then
      echo "JUNCA_SYSTEM_GID_992_COLLISION entry=${occupied_entry%%:*}" >&2
      return 1
    fi
    groupadd --system --gid 992 junca || return 1
  fi

  if [[ -n "$passwd_entry" ]]; then
    IFS=: read -r passwd_name _ old_uid old_primary_gid _ old_home \
      old_shell <<<"$passwd_entry"
    [[ "$passwd_name" == junca ]] || return 1
    systemctl stop junca-public-rpc.service \
      junca-public-explorer.service >/dev/null 2>&1 || true
    if [[ "$old_uid" != 992 ]]; then
      occupied_entry="$(getent passwd 992 2>/dev/null || true)"
      if [[ -n "$occupied_entry" && "$occupied_entry" != "$passwd_entry" ]]; then
        echo "JUNCA_SYSTEM_UID_992_COLLISION entry=${occupied_entry%%:*}" >&2
        return 1
      fi
      for attempt in $(seq 1 20); do
        if ! pgrep -u "$old_uid" >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done
      if pgrep -u "$old_uid" >/dev/null 2>&1; then
        echo "JUNCA_SYSTEM_IDENTITY_ACTIVE_PROCESS uid=${old_uid}" >&2
        return 1
      fi
    fi
    usermod --uid 992 --gid 992 --home /var/lib/junca \
      --shell /sbin/nologin junca || return 1
  else
    occupied_entry="$(getent passwd 992 2>/dev/null || true)"
    if [[ -n "$occupied_entry" ]]; then
      echo "JUNCA_SYSTEM_UID_992_COLLISION entry=${occupied_entry%%:*}" >&2
      return 1
    fi
    useradd --system --uid 992 --gid 992 \
      --home-dir /var/lib/junca --shell /sbin/nologin \
      --no-create-home junca || return 1
  fi

  for path in /etc/junca /var/lib/junca /opt/junca; do
    [[ -e "$path" && ! -L "$path" ]] || continue
    if [[ -n "$old_uid" && "$old_uid" != 992 ]]; then
      find "$path" -xdev -uid "$old_uid" -exec chown -h 992 {} + ||
        return 1
    fi
    if [[ -n "$old_group_gid" && "$old_group_gid" != 992 ]]; then
      find "$path" -xdev -gid "$old_group_gid" -exec chgrp -h 992 {} + ||
        return 1
    fi
  done
  sync
  verify_junca_system_identity || return 1
  system_identity_repaired=true
}
'''
    text = replace_once(text, old, new, "FOUNDATION_ENSURE_IDENTITY_SIGNATURE_MISMATCH")

    old_containment = '''        if [[ "$containment_health_status" == "healthy" &&
              "$containment_validator_id" == "$expected_validator_id" ]]; then
          containment_recovered=true
          break
        fi
'''
    new_containment = '''        if [[ "$containment_health_status" == "healthy" &&
              "$containment_validator_id" == "$expected_validator_id" ]]; then
          if systemctl start junca-public-rpc.service \
              junca-public-explorer.service >/dev/null 2>&1; then
            containment_recovered=true
          fi
          break
        fi
'''
    text = replace_once(
        text,
        old_containment,
        new_containment,
        "FOUNDATION_CONTAINMENT_SIGNATURE_MISMATCH",
    )
    FOUNDATION.write_text(text, encoding="utf-8")


def patch_component() -> None:
    text = COMPONENT.read_text(encoding="utf-8")
    old = '''            - getent group junca >/dev/null || groupadd --system junca
            - id -u junca >/dev/null 2>&1 || useradd --system --gid junca --home-dir /var/lib/junca --shell /sbin/nologin junca
'''
    new = '''            - getent group junca >/dev/null || groupadd --system --gid 992 junca
            - test "$(getent group junca | cut -d: -f3)" = "992"
            - id -u junca >/dev/null 2>&1 || useradd --system --uid 992 --gid 992 --home-dir /var/lib/junca --shell /sbin/nologin --no-create-home junca
            - test "$(id -u junca)" = "992"
            - test "$(id -g junca)" = "992"
'''
    text = replace_once(text, old, new, "IMAGE_COMPONENT_IDENTITY_SIGNATURE_MISMATCH")
    old_validate = '''            - id -u junca
            - getent group junca
'''
    new_validate = '''            - test "$(id -u junca)" = "992"
            - test "$(id -g junca)" = "992"
            - test "$(getent group junca | cut -d: -f3)" = "992"
'''
    text = replace_once(
        text,
        old_validate,
        new_validate,
        "IMAGE_COMPONENT_VALIDATION_SIGNATURE_MISMATCH",
    )
    COMPONENT.write_text(text, encoding="utf-8")


def patch_user_data() -> None:
    text = USER_DATA.read_text(encoding="utf-8")
    old = '''getent group junca >/dev/null || groupadd --system junca
id -u junca >/dev/null 2>&1 || \
  useradd --system --gid junca --home-dir /var/lib/junca --shell /sbin/nologin junca
'''
    new = '''getent group junca >/dev/null || groupadd --system --gid 992 junca
test "$(getent group junca | cut -d: -f3)" = "992"
id -u junca >/dev/null 2>&1 || \
  useradd --system --uid 992 --gid 992 --home-dir /var/lib/junca \
    --shell /sbin/nologin --no-create-home junca
test "$(id -u junca)" = "992"
test "$(id -g junca)" = "992"
'''
    text = replace_once(text, old, new, "USER_DATA_IDENTITY_SIGNATURE_MISMATCH")
    USER_DATA.write_text(text, encoding="utf-8")


def write_test() -> None:
    TEST.write_text(
        '''from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "scripts/junca_public_testnet_foundation.sh"
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
USER_DATA = ROOT / "infra/aws/public-testnet/templates/validator-user-data.sh.tftpl"


class DeterministicSystemIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.foundation = FOUNDATION.read_text(encoding="utf-8")
        cls.component = COMPONENT.read_text(encoding="utf-8")
        cls.user_data = USER_DATA.read_text(encoding="utf-8")

    def test_immutable_image_pins_uid_and_gid(self) -> None:
        for value in (
            "groupadd --system --gid 992 junca",
            "useradd --system --uid 992 --gid 992",
            'test "$(id -u junca)" = "992"',
            'test "$(id -g junca)" = "992"',
        ):
            self.assertIn(value, self.component)
        self.assertNotIn("groupadd --system junca", self.component)
        self.assertNotIn("useradd --system --gid junca", self.component)

    def test_bootstrap_requires_deterministic_identity(self) -> None:
        for value in (
            "groupadd --system --gid 992 junca",
            "useradd --system --uid 992 --gid 992",
            'test "$(id -u junca)" = "992"',
            'test "$(id -g junca)" = "992"',
        ):
            self.assertIn(value, self.user_data)

    def test_live_prefix_migrates_legacy_dynamic_identity(self) -> None:
        for value in (
            "groupmod --gid 992 junca",
            "usermod --uid 992 --gid 992 --home /var/lib/junca",
            'find "$path" -xdev -uid "$old_uid"',
            'find "$path" -xdev -gid "$old_group_gid"',
            "JUNCA_SYSTEM_UID_992_COLLISION",
            "JUNCA_SYSTEM_GID_992_COLLISION",
            "JUNCA_SYSTEM_IDENTITY_ACTIVE_PROCESS",
            '[[ "$repair_status_admitted" == true ]]',
        ):
            self.assertIn(value, self.foundation)

    def test_containment_restores_public_gateways(self) -> None:
        self.assertIn("systemctl start junca-public-rpc.service", self.foundation)
        self.assertIn("junca-public-explorer.service >/dev/null 2>&1", self.foundation)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_foundation()
    patch_component()
    patch_user_data()
    write_test()


if __name__ == "__main__":
    main()
