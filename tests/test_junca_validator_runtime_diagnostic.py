import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/junca-validator-runtime-diagnostic.yml"


class ValidatorRuntimeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_current_instances_and_finality_shape_are_read_back(self) -> None:
        for expected in (
            "i-0b15c21a599bf41be",
            "i-055763640261c47df",
            "i-054811d49cce9017b",
            "runtime_env_lexical=",
            "runtime_env_resolved=",
            "runtime_env_keys=",
            "node_artifact_count=",
            "node_artifact_match=",
            "automatic_finality=",
            "block_interval=",
            "slot_epoch=",
            "junca_runtime_read=",
        ):
            self.assertIn(expected, self.workflow)

    def test_shape_probe_is_read_only(self) -> None:
        start = self.workflow.index("printf runtime_directory=")
        end = self.workflow.index('"systemctl status junca-validator.service', start)
        probe = self.workflow[start:end]
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
