from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "junca_runtime_release_manifest_gate.py"
)
WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "junca-runtime-release-manifest-gate.yml"
)
SPEC = importlib.util.spec_from_file_location("runtime_manifest_gate", SCRIPT)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

COMMIT = "a" * 40
ARTIFACT = "b" * 64
GENESIS = "c" * 64
AMI = "ami-0123456789abcdef0"
EXPLORER_DIGEST = "d" * 64
EBS_DIGEST = "e" * 64
BOUNDARY = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}


def binding():
    return {
        "source_commit": COMMIT,
        "node_artifact_sha256": ARTIFACT,
        "genesis_sha256": GENESIS,
        "ami_id": AMI,
    }


def evidence():
    signers = [
        {
            "validator_id": f"validator-0{index}",
            "resource_arn": (
                "arn:aws:kms:us-east-1:595710543956:key/"
                f"validator-0{index}"
            ),
        }
        for index in range(1, 4)
    ]
    manifest = binding() | {
        "schema_version": "junca-runtime-release-manifest/v1",
        "state": "RELEASE_CANDIDATE",
        "network": "Public Testnet",
        "notice": "Public Testnet / No Monetary Value",
        "ami_provenance": {
            "State": "available",
            "OwnerId": "595710543956",
            "Region": "us-east-1",
            "SourceCommit": COMMIT,
            "NodeArtifactSHA256": ARTIFACT,
            "GenesisSHA256": GENESIS,
            "MainnetChanged": "false",
            "AssetsMoved": "false",
            "BridgeActivated": "false",
        },
        "signer_bindings": signers,
        "previous_runtime": {
            "source_commit": "1" * 40,
            "node_artifact_sha256": "2" * 64,
            "genesis_sha256": "3" * 64,
            "ami_id": "ami-11111111111111111",
        },
        "explorer_acceptance_sha256": EXPLORER_DIGEST,
        "ebs_migration_sha256": EBS_DIGEST,
        "release_boundary": dict(BOUNDARY),
    }
    explorer = binding() | {
        "schema_version": "junca-public-explorer-acceptance/v2",
        "accepted": True,
        "status": "PASS",
        "finalized_only": True,
        "read_only": True,
        "unsafe_rpc_rejection": True,
        "release_boundary": dict(BOUNDARY),
    }
    volumes = [
        {
            "validator_id": f"validator-0{index}",
            "volume_id": f"vol-{index:017x}",
            "rollback_snapshot_id": f"snap-{index:017x}",
            "encrypted": True,
            "volume_type": "gp3",
            "mount_path": "/var/lib/junca",
            "filesystem_verified": True,
            "state_store_integrity": True,
            "finality_certificate_recovered": True,
        }
        for index in range(1, 4)
    ]
    ebs = binding() | {
        "schema_version": "junca-validator-ebs-migration/v1",
        "state": "VERIFIED_PASS",
        "migration_complete": True,
        "data_loss": False,
        "validator_volumes": volumes,
        "release_boundary": dict(BOUNDARY),
    }
    return manifest, explorer, ebs


def evaluate(manifest, explorer, ebs):
    return gate.evaluate(
        manifest,
        explorer,
        ebs,
        explorer_evidence_sha256=EXPLORER_DIGEST,
        ebs_evidence_sha256=EBS_DIGEST,
        expected_source_commit=COMMIT,
        expected_artifact_sha256=ARTIFACT,
        expected_genesis_sha256=GENESIS,
    )


class RuntimeReleaseManifestGateTests(unittest.TestCase):
    def test_complete_candidate_passes(self):
        decision = evaluate(*evidence())
        self.assertTrue(decision["accepted"])
        self.assertEqual(decision["decision"], "PROMOTION_GATE_PASS")

    def test_old_runtime_cannot_be_promoted_as_new_candidate(self):
        manifest, explorer, ebs = evidence()
        manifest["previous_runtime"] = binding()
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn("manifest.previous_runtime:equals_candidate", decision["failures"])

    def test_expected_head_and_artifact_binding_rejects_stale_manifest(self):
        manifest, explorer, ebs = evidence()
        manifest["source_commit"] = "9" * 40
        manifest["node_artifact_sha256"] = "8" * 64
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.candidate_binding:stale_or_mismatched", decision["failures"]
        )

    def test_ami_provenance_must_bind_exact_artifact_and_genesis(self):
        manifest, explorer, ebs = evidence()
        manifest["ami_provenance"]["NodeArtifactSHA256"] = "0" * 64
        manifest["ami_provenance"]["GenesisSHA256"] = "0" * 64
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.ami_provenance.NodeArtifactSHA256:mismatch",
            decision["failures"],
        )
        self.assertIn(
            "manifest.ami_provenance.GenesisSHA256:mismatch",
            decision["failures"],
        )

    def test_signer_set_must_be_exact_distinct_three(self):
        manifest, explorer, ebs = evidence()
        manifest["signer_bindings"][2] = dict(manifest["signer_bindings"][1])
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.signer_bindings:not_exact_three", decision["failures"]
        )

    def test_explorer_v1_or_unbound_acceptance_is_rejected(self):
        manifest, explorer, ebs = evidence()
        explorer["schema_version"] = "junca-public-explorer-acceptance/v1"
        explorer["ami_id"] = "ami-99999999999999999"
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn("explorer.schema_version:not_v2", decision["failures"])
        self.assertIn("explorer.candidate_binding:mismatch", decision["failures"])

    def test_ebs_requires_three_durable_verified_volumes(self):
        manifest, explorer, ebs = evidence()
        ebs["validator_volumes"][1]["encrypted"] = False
        ebs["validator_volumes"][2]["state_store_integrity"] = False
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "ebs.validator_volumes:acceptance_incomplete", decision["failures"]
        )

    def test_evidence_digest_substitution_is_rejected(self):
        manifest, explorer, ebs = evidence()
        manifest["explorer_acceptance_sha256"] = "0" * 64
        manifest["ebs_migration_sha256"] = "0" * 64
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.explorer_acceptance_sha256:mismatch", decision["failures"]
        )
        self.assertIn("manifest.ebs_migration_sha256:mismatch", decision["failures"])

    def test_boundary_drift_is_rejected(self):
        manifest, explorer, ebs = evidence()
        manifest["release_boundary"]["mainnet_changed"] = True
        explorer["release_boundary"]["assets_moved"] = True
        ebs["release_boundary"]["bridge_activated"] = True
        decision = evaluate(manifest, explorer, ebs)
        self.assertGreaterEqual(decision["failure_count"], 3)

    def test_workflow_is_read_only_and_head_bound(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("SOURCE_COMMIT: ${{ github.sha }}", workflow)

    def test_workflow_contains_no_deployment_or_apply_command(self):
        workflow = WORKFLOW.read_text(encoding="utf-8").lower()
        self.assertNotIn("terraform apply", workflow)
        self.assertNotIn("aws ec2 run-instances", workflow)
        self.assertNotIn("aws autoscaling", workflow)
        self.assertNotIn("aws imagebuilder create-image", workflow)


if __name__ == "__main__":
    unittest.main()
