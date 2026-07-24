from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.deployment_bundle import (
    DeploymentBundleError,
    build_rollback_manifest,
    load_launch_manifest,
    render_genesis,
    serialize_genesis,
)


CONFIG = Path("config/junca_social_ecosystem_chain_launch_manifest.json")


class DeploymentBundleTests(unittest.TestCase):
    def test_canonical_manifest_remains_pending_without_runtime_addresses(self) -> None:
        manifest = load_launch_manifest(CONFIG)
        self.assertEqual(manifest.state, "pending-bindings")
        self.assertEqual(len(manifest.missing_bindings), 4)
        self.assertFalse(manifest.as_evidence()["secret_material_in_manifest"])
        with self.assertRaisesRegex(DeploymentBundleError, "pending bindings"):
            render_genesis(manifest)

    def test_bound_manifest_generates_deterministic_genesis_and_rollback(self) -> None:
        raw = self._raw()
        manifest = self._load(raw)
        first = render_genesis(manifest)
        second = render_genesis(manifest)
        self.assertEqual(first, second)
        self.assertEqual(first["config"]["chainId"], 20260723)
        self.assertEqual(first["config"]["posv"]["period"], 2)
        self.assertEqual(first["config"]["posv"]["epoch"], 900)
        self.assertEqual(len(first["extraData"]), 2 + 64 + 120 + 130)
        serialized = serialize_genesis(first)
        self.assertEqual(serialized, serialize_genesis(second))
        rollback = build_rollback_manifest(
            first,
            binary_digest="b" * 64,
            source_commit="a" * 40,
        )
        self.assertEqual(rollback["genesis_digest"], hashlib.sha256(serialized).hexdigest())
        self.assertEqual(rollback["restore_test_status"], "pending-runtime-rehearsal")
        self.assertFalse(rollback["secret_material_in_bundle"])

    def test_duplicate_validator_address_is_rejected(self) -> None:
        raw = self._raw()
        raw["validators"][1]["address"] = raw["validators"][0]["address"]
        with self.assertRaisesRegex(DeploymentBundleError, "unique"):
            self._load(raw)

    def test_foundation_cannot_be_validator(self) -> None:
        raw = self._raw()
        raw["foundation_address"] = raw["validators"][0]["address"]
        with self.assertRaisesRegex(DeploymentBundleError, "separate"):
            self._load(raw)

    def test_secret_marker_is_rejected(self) -> None:
        raw = self._raw()
        raw["private_key"] = "not-a-real-key"
        with self.assertRaisesRegex(DeploymentBundleError, "secret material"):
            self._load(raw)

    def test_mainnet_promotion_is_rejected(self) -> None:
        raw = self._raw()
        raw["release"]["mainnet"] = True
        with self.assertRaisesRegex(DeploymentBundleError, "mainnet"):
            self._load(raw)

    def test_invalid_binary_digest_is_rejected(self) -> None:
        manifest = self._load(self._raw())
        with self.assertRaisesRegex(DeploymentBundleError, "binary_digest"):
            build_rollback_manifest(
                render_genesis(manifest),
                binary_digest="invalid",
                source_commit="a" * 40,
            )

    @staticmethod
    def _raw() -> dict[str, object]:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        for index, item in enumerate(raw["validators"], start=1):
            item["address"] = "0x" + str(index) * 40
        raw["foundation_address"] = "0x" + "4" * 40
        raw["prefund"] = [{"address": "0x" + "5" * 40, "balance": "0x3635c9adc5dea00000"}]
        return raw

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "manifest.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_launch_manifest(path)


if __name__ == "__main__":
    unittest.main()
