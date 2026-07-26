import copy
import json
from pathlib import Path
import tempfile
import unittest

from jaios.social_ecosystem_chain.validator_artifacts import (
    ValidatorArtifactError,
    build_validator_artifact_handoff,
    pending_validator_artifact_handoff,
)


def specification():
    return {
        "governance": "JAIOS Institutional Governance",
        "notice": "Public Testnet / No Monetary Value",
        "aws_account_id": "595710543956",
        "aws_region": "us-east-1",
        "source_commit": "a" * 40,
        "ami_id": "ami-0123456789abcdef0",
        "chain_id": 20260723,
        "validator_ids": ["validator-01", "validator-02", "validator-03"],
        "signer_arns": [
            f"arn:aws:kms:us-east-1:595710543956:key/key-{number}"
            for number in range(1, 4)
        ],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class ValidatorArtifactTests(unittest.TestCase):
    def _files(self, root: Path):
        binary = root / "junca"
        binary.write_bytes(b"immutable-node-binary")
        genesis = root / "genesis.json"
        genesis.write_text(
            json.dumps(
                {
                    "chain_id": 20260723,
                    "network": "public-testnet",
                    "notice": "Public Testnet / No Monetary Value",
                    "validator_ids": [
                        "validator-01",
                        "validator-02",
                        "validator-03",
                    ],
                }
            ),
            encoding="utf-8",
        )
        return binary, genesis

    def test_verified_inputs_create_deterministic_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, genesis = self._files(Path(directory))
            first = build_validator_artifact_handoff(
                specification(), node_binary=binary, genesis=genesis
            )
            second = build_validator_artifact_handoff(
                specification(), node_binary=binary, genesis=genesis
            )
        self.assertEqual(first.evidence, second.evidence)
        self.assertEqual(first.state, "READY_FOR_AWS_AMI_READBACK")
        self.assertEqual(first.evidence["validator_count"], 3)
        self.assertFalse(first.evidence["live_runtime_verified"])

    def test_pending_handoff_never_claims_live_runtime(self):
        result = pending_validator_artifact_handoff()
        self.assertEqual(result.state, "BLOCKED_FAIL_CLOSED")
        self.assertFalse(result.evidence["live_runtime_verified"])
        self.assertIn("three_validator_quorum", result.evidence["blockers"])

    def test_rejects_wrong_account_region_or_safety_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, genesis = self._files(Path(directory))
            for field, value in (
                ("aws_account_id", "000000000000"),
                ("aws_region", "ap-northeast-1"),
                ("mainnet_changed", True),
            ):
                mutated = copy.deepcopy(specification())
                mutated[field] = value
                with self.assertRaises(ValidatorArtifactError):
                    build_validator_artifact_handoff(
                        mutated, node_binary=binary, genesis=genesis
                    )

    def test_rejects_genesis_validator_or_chain_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, genesis = self._files(Path(directory))
            value = json.loads(genesis.read_text(encoding="utf-8"))
            value["chain_id"] = 1
            genesis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValidatorArtifactError, "chain_id"):
                build_validator_artifact_handoff(
                    specification(), node_binary=binary, genesis=genesis
                )


if __name__ == "__main__":
    unittest.main()
