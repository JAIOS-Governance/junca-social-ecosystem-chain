from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain.deployment_preflight import (
    DeploymentPreflightError,
    load_deployment_preflight,
)


CONFIG = Path("config/junca_social_ecosystem_chain_deployment_preflight.json")


class DeploymentPreflightTests(unittest.TestCase):
    def test_canonical_preflight_is_blocked_without_false_promotion(self) -> None:
        preflight = load_deployment_preflight(CONFIG)
        self.assertEqual(preflight.state, "blocked")
        self.assertIn("validator-1-custody", preflight.missing_controls)
        self.assertIn("rollback-package", preflight.missing_controls)
        self.assertFalse(preflight.as_evidence()["secret_material_in_evidence"])
        with self.assertRaisesRegex(DeploymentPreflightError, "deployment blocked"):
            preflight.assert_deployable()

    def test_complete_redacted_evidence_is_ready(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["source_commit"] = "a" * 40
        for index, record in enumerate(raw["custody"]["validators"], start=1):
            record.update({
                "public_address": "0x" + str(index) * 40,
                "key_id_digest": str(index) * 64,
                "created_at": "2026-07-23T12:00:00Z",
                "attested": True,
            })
        raw["rollback"].update({
            "genesis_digest": "a" * 64,
            "binary_digest": "b" * 64,
            "backup_manifest_digest": "c" * 64,
            "restore_tested": True,
        })
        raw["runtime"] = {name: True for name in raw["runtime"]}
        preflight = self._load(raw)
        self.assertEqual(preflight.state, "ready")
        preflight.assert_deployable()

    def test_attestation_cannot_promote_pending_identity(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["custody"]["validators"][0]["attested"] = True
        with self.assertRaisesRegex(DeploymentPreflightError, "public address"):
            self._load(raw)

    def test_unattested_record_cannot_contain_identity_data(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["custody"]["validators"][0]["public_address"] = "0x" + "1" * 40
        with self.assertRaisesRegex(DeploymentPreflightError, "must remain pending"):
            self._load(raw)

    def test_secret_field_is_rejected(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["custody"]["private_key"] = "not-a-real-key"
        with self.assertRaisesRegex(DeploymentPreflightError, "secret field"):
            self._load(raw)

    def test_rollback_cannot_be_verified_without_digests(self) -> None:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["rollback"]["restore_tested"] = True
        with self.assertRaisesRegex(DeploymentPreflightError, "SHA-256"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "preflight.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_deployment_preflight(path)


if __name__ == "__main__":
    unittest.main()
