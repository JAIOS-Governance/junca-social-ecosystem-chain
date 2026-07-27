from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/junca_validator_ami_build_request.py"
REQUEST = ROOT / "tests/fixtures/junca_validator_ami_build_request.json"
SPEC = importlib.util.spec_from_file_location("ami_request", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_request() -> dict:
    return json.loads(REQUEST.read_text(encoding="utf-8"))


class ValidatorAmiBuildRequestTests(unittest.TestCase):
    def test_canonical_request_is_authorized_and_digest_bound(self):
        request = canonical_request()
        outputs = MODULE.validate_request(request)
        self.assertEqual(outputs["source_run_id"], "30273062161")
        self.assertEqual(
            outputs["source_commit"],
            "598152b38364e1cc85ec5e6e737f3e5830945d8a",
        )
        self.assertEqual(
            outputs["request_sha256"],
            MODULE.canonical_request_sha256(request),
        )

    def test_tampered_immutable_input_is_rejected(self):
        request = canonical_request()
        request["node_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "request_sha256 mismatch",
        ):
            MODULE.validate_request(request)

    def test_artifact_names_must_be_bound_to_source_run(self):
        request = canonical_request()
        request["node_artifact_name"] = "junca-validator-runtime-1"
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "node artifact is not bound",
        ):
            MODULE.validate_request(request)

    def test_release_boundary_cannot_enable_mainnet_assets_or_bridge(self):
        for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
            with self.subTest(boundary=boundary):
                request = canonical_request()
                request["boundaries"][boundary] = True
                request["request_sha256"] = MODULE.canonical_request_sha256(request)
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    "release boundary mismatch",
                ):
                    MODULE.validate_request(request)

    def test_unknown_fields_fail_closed(self):
        request = canonical_request()
        request["unexpected"] = True
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "fields do not match",
        ):
            MODULE.validate_request(request)

    def test_wrong_approval_phrase_is_rejected(self):
        request = canonical_request()
        request["approval_phrase"] = "APPROVE"
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "approval phrase mismatch",
        ):
            MODULE.validate_request(request)

    def test_manual_sealing_uses_same_canonical_digest(self):
        request = canonical_request()
        expected = request["request_sha256"]
        request["request_sha256"] = ""
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        self.assertEqual(request["request_sha256"], expected)
        self.assertEqual(MODULE.validate_request(request)["request_sha256"], expected)

    def test_completed_migration_binding_preserves_runtime_identity_digest(self):
        request = canonical_request()
        runtime_digest = request["request_sha256"]
        request["migration_run_id"] = "30303030303"
        request["migration_evidence_sha256"] = "7" * 64
        self.assertEqual(
            MODULE.canonical_request_sha256(request),
            runtime_digest,
        )
        outputs = MODULE.validate_request(
            request,
            require_migration_binding=True,
        )
        self.assertEqual(outputs["request_sha256"], runtime_digest)
        self.assertEqual(outputs["migration_run_id"], "30303030303")
        self.assertEqual(outputs["migration_evidence_sha256"], "7" * 64)

    def test_release_phase_requires_complete_valid_migration_binding(self):
        request = canonical_request()
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "completed migration binding is required",
        ):
            MODULE.validate_request(
                request,
                require_migration_binding=True,
            )
        request["migration_run_id"] = "30303030303"
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "fields do not match",
        ):
            MODULE.validate_request(request)
        request["migration_evidence_sha256"] = "invalid"
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "migration_evidence_sha256",
        ):
            MODULE.validate_request(
                request,
                require_migration_binding=True,
            )


if __name__ == "__main__":
    unittest.main()
