from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.verify_validator_runtime_layout import verify


ROOT = Path(__file__).resolve().parents[1]


class ValidatorRuntimeLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tempdir.name) / "runtime"
        subprocess.run(
            ["bash", "scripts/build_validator_runtime.sh", str(self.output)],
            cwd=ROOT,
            check=True,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_complete_runtime_passes(self) -> None:
        verify(self.output)

    def test_missing_gateway_unit_fails_closed(self) -> None:
        (self.output / "etc/systemd/system/junca-public-rpc.service").unlink()
        with self.assertRaisesRegex(ValueError, "required regular file missing"):
            verify(self.output)

    def test_gateway_running_as_root_fails_closed(self) -> None:
        service = self.output / "etc/systemd/system/junca-public-explorer.service"
        service.write_text(
            service.read_text(encoding="utf-8").replace("User=junca", "User=root"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "missing contract: User=junca"):
            verify(self.output)

    def test_missing_boot_enable_contract_fails_closed(self) -> None:
        service = self.output / "etc/systemd/system/junca-public-rpc.service"
        service.write_text(
            service.read_text(encoding="utf-8").replace(
                "WantedBy=multi-user.target",
                "WantedBy=",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ValueError,
            "missing contract: WantedBy=multi-user.target",
        ):
            verify(self.output)

    def test_missing_restart_contract_fails_closed(self) -> None:
        service = self.output / "etc/systemd/system/junca-validator.service"
        service.write_text(
            service.read_text(encoding="utf-8").replace(
                "Restart=on-failure",
                "Restart=no",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ValueError,
            "missing contract: Restart=on-failure",
        ):
            verify(self.output)

    def test_tampered_runtime_fails_closed(self) -> None:
        gateway = self.output / "usr/local/bin/junca-public-gateway"
        gateway.write_text(gateway.read_text(encoding="utf-8") + "\n# changed\n")
        with self.assertRaisesRegex(ValueError, "runtime digest mismatch"):
            verify(self.output)

    def test_duplicate_digest_entry_fails_closed(self) -> None:
        sums = self.output / "SHA256SUMS"
        first = sums.read_text(encoding="utf-8").splitlines()[0]
        sums.write_text(
            sums.read_text(encoding="utf-8") + first + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate runtime digest entry"):
            verify(self.output)


if __name__ == "__main__":
    unittest.main()
