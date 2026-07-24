from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.runtime import (
    PublicTestnetRuntimeError,
    load_public_testnet_runtime,
)


RUNTIME = Path("config/junca_social_ecosystem_chain_runtime.json")


class PublicTestnetRuntimeTests(unittest.TestCase):
    def test_canonical_runtime_is_three_validator_testnet(self) -> None:
        runtime = load_public_testnet_runtime(RUNTIME)
        self.assertEqual(runtime.chain_id, 20260723)
        self.assertEqual(runtime.issuance_management, "JAIOS Institutional Governance")
        self.assertEqual(len(runtime.validators), 3)
        self.assertEqual(runtime.allowed_rpc_modules, ("eth", "net", "web3"))
        self.assertEqual(runtime.as_evidence()["deployment_status"], "pending-runtime-binding")

    def test_unsafe_rpc_module_is_rejected(self) -> None:
        raw = json.loads(RUNTIME.read_text(encoding="utf-8"))
        raw["rpc"]["allowed_modules"].append("admin")
        with self.assertRaisesRegex(PublicTestnetRuntimeError, "only eth"):
            self._load(raw)

    def test_inline_key_path_is_rejected(self) -> None:
        raw = json.loads(RUNTIME.read_text(encoding="utf-8"))
        raw["validators"][0]["key_file"] = "./validator.key"
        with self.assertRaisesRegex(PublicTestnetRuntimeError, "secret mounts"):
            self._load(raw)

    def test_legacy_key_reuse_is_rejected(self) -> None:
        raw = json.loads(RUNTIME.read_text(encoding="utf-8"))
        raw["custody"]["legacy_key_reuse"] = True
        with self.assertRaisesRegex(PublicTestnetRuntimeError, "legacy_key_reuse"):
            self._load(raw)

    def test_mainnet_misrepresentation_is_rejected(self) -> None:
        raw = json.loads(RUNTIME.read_text(encoding="utf-8"))
        raw["release"]["mainnet"] = True
        with self.assertRaisesRegex(PublicTestnetRuntimeError, "mainnet"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "runtime.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_public_testnet_runtime(path)


if __name__ == "__main__":
    unittest.main()
