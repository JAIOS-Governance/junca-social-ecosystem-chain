import pathlib
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github/workflows/junca-validator-runtime-diagnostic.yml"


class ValidatorRuntimeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_current_validator_set_and_config_shape_are_read_back(self) -> None:
        for expected in (
            "i-083280924b5536f17",
            "i-055763640261c47df",
            "i-054811d49cce9017b",
            "runtime_directory=",
            "genesis=",
            "validator_lexical=",
            "validator_resolved=",
            "junca_identity=",
            "stat -Lc",
            "readlink /etc/junca/validator.toml",
        ):
            self.assertIn(expected, self.workflow)

    def test_diagnostic_shape_probe_is_read_only(self) -> None:
        probe_start = self.workflow.index("printf runtime_directory=")
        probe_end = self.workflow.index(
            '"systemctl status junca-validator.service', probe_start
        )
        probe = self.workflow[probe_start:probe_end]
        for forbidden in (
            "systemctl stop",
            "systemctl start",
            "systemctl restart",
            "chmod",
            "chown",
            "install ",
            "rm ",
            "mv ",
            "cp ",
            "terraform",
        ):
            self.assertNotIn(forbidden, probe)


if __name__ == "__main__":
    unittest.main()
