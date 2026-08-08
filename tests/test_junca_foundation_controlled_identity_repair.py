from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "scripts/junca_public_testnet_foundation.sh"


class FoundationControlledIdentityRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = FOUNDATION.read_text(encoding="utf-8")

    def test_missing_identity_enters_existing_controlled_repair_gate(self) -> None:
        expected = """verify_junca_system_identity || true
if [[ \"$repair_status_admitted\" != true &&
      ( \"$runtime_config_access_verified\" != true ||
        \"$system_identity_verified\" != true ) ]]; then
  admit_controlled_active_repair || true
fi
if [[ \"$repair_status_admitted\" == true &&
      \"$system_identity_verified\" != true ]]; then
  ensure_junca_system_identity || true
fi
"""
        self.assertIn(expected, self.script)

    def test_legacy_runtime_config_only_admission_is_retired(self) -> None:
        legacy = """if [[ \"$runtime_config_access_verified\" != true ]]; then
  admit_controlled_active_repair || true
fi
verify_junca_system_identity || true
"""
        self.assertNotIn(legacy, self.script)


if __name__ == "__main__":
    unittest.main()
