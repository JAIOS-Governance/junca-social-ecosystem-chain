from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/junca_validator_state_migration_request.py"
REQUEST = ROOT / "tests/fixtures/junca_validator_state_migration_request.json"
SPEC = importlib.util.spec_from_file_location("migration_request", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_request() -> dict:
    return json.loads(REQUEST.read_text(encoding="utf-8"))


class ValidatorStateMigrationRequestTests(unittest.TestCase):
    def test_canonical_request_is_exact_and_digest_bound(self):
        request = canonical_request()
        outputs = MODULE.validate_request(request)
        self.assertEqual(
            outputs["request_sha256"],
            MODULE.canonical_request_sha256(request),
        )

    def test_tampered_state_target_or_boundary_is_rejected(self):
        mutations = (
            ("terraform_state_bucket", "different-bucket"),
            ("dynamodb_lock_table", "different-lock"),
            ("deployment_role_arn", "arn:aws:iam::595710543956:role/Other"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                request = canonical_request()
                request[field] = value
                request["request_sha256"] = MODULE.canonical_request_sha256(
                    request
                )
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    "mismatch",
                ):
                    MODULE.validate_request(request)
        request = canonical_request()
        request["boundaries"]["mainnet_changed"] = True
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "boundaries mismatch",
        ):
            MODULE.validate_request(request)

    def test_unknown_or_partial_request_fails_closed(self):
        request = canonical_request()
        request["unexpected"] = True
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "fields do not match",
        ):
            MODULE.validate_request(request)

    def test_request_digest_tampering_is_rejected(self):
        request = canonical_request()
        request["request_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "request_sha256 mismatch",
        ):
            MODULE.validate_request(request)


if __name__ == "__main__":
    unittest.main()
