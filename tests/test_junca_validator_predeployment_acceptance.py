import copy
import hashlib
import unittest

from jaios.social_ecosystem_chain.predeployment_acceptance import evaluate_predeployment


COMMIT = "a" * 40
BINARY = "b" * 64
GENESIS = "c" * 64
SIGNERS = [
    f"arn:aws:kms:us-east-1:595710543956:key/validator-{number}"
    for number in ("01", "02", "03")
]
IDENTITY = {
    "official_chain_name": "JUNCA Social Ecosystem Chain",
    "governance": "JAIOS Institutional Governance",
    "network_label": "Public Testnet / No Monetary Value",
    "source_commit": COMMIT,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
    "bridge_route": "PAUSED",
}


def evidence():
    artifact = {
        **IDENTITY,
        "state": "READY_FOR_AWS_AMI_READBACK",
        "ami_id": "ami-0123456789abcdef0",
        "node_artifact_sha256": BINARY,
        "genesis_sha256": GENESIS,
        "signer_resource_digests": [
            hashlib.sha256(value.encode()).hexdigest() for value in SIGNERS
        ],
        "ami_readback_verified": True,
        "live_runtime_verified": False,
    }
    foundation = {
        **IDENTITY,
        "status": "AWS_FOUNDATION_READBACK_VERIFIED",
        "aws_account_id": "595710543956",
        "aws_region": "us-east-1",
        "availability_zones": ["us-east-1a", "us-east-1b", "us-east-1c"],
        "private_subnet_ids": ["subnet-11111111", "subnet-22222222", "subnet-33333333"],
        "validator_signer_kms_key_arns": SIGNERS,
        "kms_key_usage": "SIGN_VERIFY",
    }
    bootstrap = {
        **IDENTITY,
        "chain_id": 20260726,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "validator_count": 3,
        "quorum_threshold": 2,
        "genesis_sha256": GENESIS,
        "node_artifact_sha256": BINARY,
        "bootnode_endpoints": [
            "enode://validator01@10.0.1.10:30303",
            "enode://validator02@10.0.2.10:30303",
            "enode://validator03@10.0.3.10:30303",
        ],
    }
    return artifact, foundation, bootstrap


class PredeploymentAcceptanceTests(unittest.TestCase):
    def test_accepts_only_complete_bound_machine_manifest(self):
        result = evaluate_predeployment(*evidence())
        self.assertTrue(result["accepted"])
        self.assertEqual(result["decision"], "PREDEPLOYMENT_ACCEPTED")
        self.assertEqual(result["failure_count"], 0)
        self.assertFalse(result["live_runtime_verified"])
        self.assertRegex(result["manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_pending_inputs_are_rejected_with_explicit_missing_fields(self):
        artifact, foundation, bootstrap = evidence()
        artifact.update({"state": "BLOCKED_FAIL_CLOSED", "ami_id": "PENDING"})
        artifact.pop("node_artifact_sha256")
        foundation.update({
            "status": "PENDING",
            "availability_zones": [],
            "private_subnet_ids": [],
            "validator_signer_kms_key_arns": [],
        })
        bootstrap.update({"bootnode_endpoints": ["PENDING"]})
        result = evaluate_predeployment(artifact, foundation, bootstrap)
        self.assertFalse(result["accepted"])
        self.assertIn("artifact.ami_id:missing_or_invalid", result["failures"])
        self.assertIn("artifact.node_artifact_sha256:missing_or_invalid", result["failures"])
        self.assertIn("foundation.availability_zones:not_three_distinct", result["failures"])
        self.assertIn("foundation.validator_signers:not_three_canonical", result["failures"])
        self.assertIn("bootstrap.bootnode_endpoints:not_three_distinct", result["failures"])

    def test_rejects_cross_account_signers_and_mismatched_genesis(self):
        artifact, foundation, bootstrap = evidence()
        foundation["validator_signer_kms_key_arns"][0] = (
            "arn:aws:kms:us-east-1:000000000000:key/validator-01"
        )
        bootstrap["genesis_sha256"] = "d" * 64
        result = evaluate_predeployment(artifact, foundation, bootstrap)
        self.assertFalse(result["accepted"])
        self.assertIn("foundation.validator_signers:not_three_canonical", result["failures"])
        self.assertIn("bootstrap.genesis_sha256:mismatch", result["failures"])

    def test_rejects_false_live_or_release_boundary_claims(self):
        artifact, foundation, bootstrap = evidence()
        artifact["live_runtime_verified"] = True
        bootstrap["mainnet_changed"] = True
        result = evaluate_predeployment(artifact, foundation, bootstrap)
        self.assertFalse(result["accepted"])
        self.assertIn("artifact.live_runtime_verified:must_be_false_predeploy", result["failures"])
        self.assertIn("bootstrap.mainnet_changed:not_false", result["failures"])

    def test_rejects_source_commit_drift(self):
        artifact, foundation, bootstrap = evidence()
        bootstrap["source_commit"] = "f" * 40
        result = evaluate_predeployment(artifact, foundation, bootstrap)
        self.assertFalse(result["accepted"])
        self.assertIn("source_commit:missing_or_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
