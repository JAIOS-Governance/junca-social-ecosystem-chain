from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


class AwsInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = Path("infrastructure/aws/main.tf").read_text(encoding="utf-8")
        self.variables = Path("infrastructure/aws/variables.tf").read_text(
            encoding="utf-8"
        )

    def test_three_validators_and_failure_domain_check(self) -> None:
        self.assertIn("validator-01 = 0", self.main)
        self.assertIn("validator-02 = 1", self.main)
        self.assertIn("validator-03 = 2", self.main)
        self.assertIn('check "three_failure_domains"', self.main)

    def test_public_boundary_is_read_only_replicated_tls_and_rate_limited(self) -> None:
        self.assertIn("desired_count   = var.rpc_desired_count", self.main)
        self.assertIn("desired_count   = var.explorer_desired_count", self.main)
        self.assertIn('"READ_ONLY", value = "true"', self.main)
        self.assertIn("eth_sendRawTransaction", self.main)
        self.assertIn('resource "aws_acm_certificate"', self.main)
        self.assertIn('resource "aws_wafv2_web_acl"', self.main)

    def test_unsafe_rpc_negative_policy_is_fail_closed(self) -> None:
        policy = json.loads(
            Path("infrastructure/aws/rpc-method-policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(policy["default_action"], "deny")
        for prefix in ("admin_", "debug_", "personal_", "miner_"):
            self.assertIn(prefix, policy["denied_method_prefixes"])
        for method in ("eth_sendRawTransaction", "eth_sendTransaction"):
            self.assertIn(method, policy["denied_methods"])
            self.assertNotIn(method, policy["allowed_methods"])
        self.assertIn("eth_getTransactionReceipt", policy["allowed_methods"])

    def test_signer_is_reference_only_and_apply_is_fail_closed(self) -> None:
        self.assertIn('default     = false', self.variables)
        self.assertIn("validator_signer_kms_key_arns", self.main)
        self.assertNotIn("private_key =", self.main)
        self.assertNotIn("seed_phrase", self.main)

    def test_preflight_is_complete_but_blocks_apply(self) -> None:
        completed = subprocess.run(
            ["python", "scripts/junca_social_ecosystem_chain_aws_preflight.py"],
            check=True,
            capture_output=True,
            text=True,
        )
        evidence = json.loads(completed.stdout)
        self.assertEqual(evidence["state"], "BLOCKED_FAIL_CLOSED")
        self.assertFalse(evidence["apply_authorized"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
