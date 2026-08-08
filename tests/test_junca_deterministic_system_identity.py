from pathlib import Path
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

    def test_image_builder_commands_remain_yaml_scalars(self) -> None:
        risky = '- test "$(getent group junca | cut -d: -f3)" = "992"'
        safe = '- \'test "$(getent group junca | cut -d: -f3)" = "992"\''
        self.assertNotIn(risky, self.component)
        self.assertEqual(self.component.count(safe), 2)

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
