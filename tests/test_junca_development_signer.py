from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from jaios.social_ecosystem_chain.development_signer import (
    DEVELOPMENT_MODE_ENV,
    DeterministicDevelopmentKmsAdapter,
    development_resource,
)
from jaios.social_ecosystem_chain.validator_node import ValidatorNodeError


class DeterministicDevelopmentKmsAdapterTest(unittest.TestCase):
    def test_adapter_is_disabled_without_explicit_environment_gate(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValidatorNodeError, "disabled"):
                DeterministicDevelopmentKmsAdapter()

    def test_signature_is_deterministic_and_resource_bound(self) -> None:
        with patch.dict(os.environ, {DEVELOPMENT_MODE_ENV: "1"}, clear=True):
            adapter = DeterministicDevelopmentKmsAdapter()
            payload = b"local-finality-payload"
            resource = development_resource("validator-01")
            signature = adapter.sign(resource, payload)
            self.assertEqual(len(signature), 64)
            self.assertEqual(signature, adapter.sign(resource, payload))
            self.assertTrue(adapter.verify(resource, payload, signature))
            self.assertFalse(
                adapter.verify(development_resource("validator-02"), payload, signature)
            )

    def test_non_allowlisted_resource_is_rejected(self) -> None:
        with patch.dict(os.environ, {DEVELOPMENT_MODE_ENV: "1"}, clear=True):
            adapter = DeterministicDevelopmentKmsAdapter()
            with self.assertRaisesRegex(ValidatorNodeError, "resource is invalid"):
                adapter.sign("arn:aws:kms:us-east-1:123456789012:key/example", b"x")

    def test_evidence_preserves_safety_boundary(self) -> None:
        with patch.dict(os.environ, {DEVELOPMENT_MODE_ENV: "1"}, clear=True):
            evidence = DeterministicDevelopmentKmsAdapter().evidence()
        self.assertEqual(evidence["mode"], "isolated-local-development-only")
        self.assertFalse(evidence["cryptographic_key_management"])
        self.assertFalse(evidence["private_key_material_accepted"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
