from __future__ import annotations

import base64
import hashlib
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
REQUEST = "9" * 64
MIGRATION_DIGEST = "7" * 64


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
        "schema_version": "junca-runtime-pre-rollout-baseline/v1",
        "state": "PRE_ROLLOUT_BASELINE_VERIFIED",
        "request_sha256": REQUEST,
        "migration_evidence_sha256": MIGRATION_DIGEST,
        "baseline_mode": "public_endpoints",
        "public_services_enabled": True,
        "public_endpoint_acceptance": True,
        "public_endpoint_outage": None,
        "network": "Public Testnet",
        "notice": "Public Testnet / No Monetary Value",
        "ami_provenance": {
            "State": "available",
            "OwnerId": "595710543956",
            "Region": "us-east-1",
            "SourceCommit": COMMIT,
            "NodeArtifactSHA256": ARTIFACT,
            "GenesisSHA256": GENESIS,
            "RequestDigest": REQUEST,
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
        "explorer_baseline_sha256": EXPLORER_DIGEST,
        "ebs_baseline_sha256": EBS_DIGEST,
        "release_boundary": dict(BOUNDARY),
    }
    explorer = binding() | {
        "schema_version": "junca-public-explorer-pre-rollout-baseline/v1",
        "baseline_mode": "public_endpoints",
        "public_services_enabled": True,
        "public_endpoint_acceptance": True,
        "public_endpoint_outage": None,
        "candidate_accepted": False,
        "status": "BASELINE_VERIFIED",
        "request_sha256": REQUEST,
        "observed_runtime": manifest["previous_runtime"],
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
        "schema_version": "junca-validator-ebs-pre-rollout-baseline/v1",
        "candidate_accepted": False,
        "state": "BASELINE_VERIFIED",
        "request_sha256": REQUEST,
        "migration_evidence_sha256": MIGRATION_DIGEST,
        "observed_runtime": manifest["previous_runtime"],
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


def endpoint_outage():
    body = b"<html><body>502 Bad Gateway</body></html>"
    observations = [
        {
            "name": name,
            "method": method,
            "url": url,
            "curl_exit_code": 0,
            "http_status": 502,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_base64": base64.b64encode(body).decode("ascii"),
            "stderr": "",
        }
        for name, method, url in (
            (
                "health",
                "GET",
                "https://health.jaios-governance.org/health",
            ),
            (
                "explorer",
                "GET",
                "https://explorer.jaios-governance.org/explorer.json",
            ),
            ("rpc", "POST", "https://rpc.jaios-governance.org/"),
        )
    ]
    return {
        "schema_version": "junca-public-endpoint-outage/v1",
        "status": "PUBLIC_ENDPOINTS_UNAVAILABLE",
        "public_services_enabled": True,
        "public_endpoint_acceptance": False,
        "observed_at": "2026-07-27T00:00:00Z",
        "endpoint_test_exit_code": 1,
        "endpoint_test": {
            "status": "FAIL",
            "error": "health endpoint unavailable",
        },
        "observations": observations,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


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

    def test_ami_provenance_must_bind_request_digest(self):
        manifest, explorer, ebs = evidence()
        manifest["ami_provenance"]["RequestDigest"] = "0" * 64
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.ami_provenance.RequestDigest:mismatch",
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
        self.assertIn(
            "explorer.schema_version:not_pre_rollout_baseline",
            decision["failures"],
        )
        self.assertIn("explorer.candidate_binding:mismatch", decision["failures"])

    def test_private_ssm_baseline_passes_without_public_endpoint_assertions(self):
        manifest, explorer, ebs = evidence()
        manifest["baseline_mode"] = "private_ssm"
        manifest["public_services_enabled"] = False
        manifest["public_endpoint_acceptance"] = False
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": {
                    "mode": "private_ssm",
                    "scope": (
                        "Public Testnet Pre-rollout Baseline / "
                        "Private SSM Read-only"
                    ),
                    "validator_count": 3,
                    "chain_id": 8453,
                    "validators": [
                        {
                            "validator_id": f"validator-0{index}",
                            "instance_id": f"i-{index:017x}",
                            "signer_resource_digest": f"{index}" * 64,
                            "durable_timestamp_state":
                                "DURABLE_PERSISTED",
                            "timestamp_schema_tables": [
                                "block_timestamps",
                                "blocks",
                                "finality_certificates",
                                "metadata",
                            ],
                        }
                        for index in range(1, 4)
                    ],
                    "finalized_head": {
                        "height": 100,
                        "hash": "0x" + "a" * 64,
                        "timestamp": 2_000_000_000,
                        "timestamp_state": "DURABLE_PERSISTED",
                        "certificate_hash": "0x" + "b" * 64,
                    },
                    "quorum": {
                        "signed_power": 3,
                        "total_power": 3,
                        "validator_ids": [
                            "validator-01",
                            "validator-02",
                            "validator-03",
                        ],
                    },
                },
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertTrue(decision["accepted"], decision["failures"])

    def test_private_ssm_baseline_rejects_identity_head_and_quorum_drift(self):
        manifest, explorer, ebs = evidence()
        manifest["baseline_mode"] = "private_ssm"
        manifest["public_services_enabled"] = False
        manifest["public_endpoint_acceptance"] = False
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": {
                    "mode": "private_ssm",
                    "scope": (
                        "Public Testnet Pre-rollout Baseline / "
                        "Private SSM Read-only"
                    ),
                    "validator_count": 3,
                    "validators": [
                        {
                            "validator_id": f"validator-0{index}",
                            "instance_id": "i-00000000000000001",
                            "signer_resource_digest": f"{index}" * 64,
                        }
                        for index in range(1, 4)
                    ],
                    "finalized_head": {
                        "height": 0,
                        "hash": "bad",
                        "certificate_hash": "bad",
                    },
                    "quorum": {
                        "signed_power": 2,
                        "total_power": 3,
                        "validator_ids": [
                            "validator-01",
                            "validator-02",
                        ],
                    },
                },
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "private_ssm.validators:not_exact_three", decision["failures"]
        )
        self.assertIn(
            "private_ssm.finalized_head:invalid", decision["failures"]
        )
        self.assertIn(
            "private_ssm.quorum:not_exact_three", decision["failures"]
        )

    def test_public_outage_private_ssm_is_not_public_endpoint_acceptance(self):
        manifest, explorer, ebs = evidence()
        outage = endpoint_outage()
        manifest.update(
            {
                "baseline_mode": "private_ssm",
                "public_services_enabled": True,
                "public_endpoint_acceptance": False,
                "public_endpoint_outage": outage,
            }
        )
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": True,
                "public_endpoint_acceptance": False,
                "public_endpoint_outage": outage,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": {
                    "mode": "private_ssm",
                    "scope": (
                        "Public Testnet Pre-rollout Baseline / "
                        "Private SSM Read-only"
                    ),
                    "validator_count": 3,
                    "chain_id": 20260723,
                    "validators": [
                        {
                            "validator_id": f"validator-0{index}",
                            "instance_id": f"i-{index:017x}",
                            "signer_resource_digest": f"{index}" * 64,
                            "durable_timestamp_state":
                                "DURABLE_PERSISTED",
                            "timestamp_schema_tables": [
                                "block_timestamps",
                                "blocks",
                                "finality_certificates",
                                "metadata",
                            ],
                        }
                        for index in range(1, 4)
                    ],
                    "finalized_head": {
                        "height": 100,
                        "hash": "0x" + "a" * 64,
                        "timestamp": 2_000_000_000,
                        "timestamp_state": "DURABLE_PERSISTED",
                        "certificate_hash": "0x" + "b" * 64,
                    },
                    "quorum": {
                        "signed_power": 3,
                        "total_power": 3,
                        "validator_ids": list(gate.VALIDATOR_IDS),
                    },
                },
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertTrue(decision["accepted"], decision["failures"])
        self.assertEqual(decision["baseline_mode"], "private_ssm")
        self.assertFalse(decision["public_endpoint_acceptance"])
        self.assertEqual(
            decision["public_endpoint_outage_status"],
            "PUBLIC_ENDPOINTS_UNAVAILABLE",
        )
        self.assertFalse(manifest["public_endpoint_acceptance"])

    def test_private_ssm_legacy_timestamp_absence_is_explicit_and_exact_three(
        self,
    ):
        manifest, explorer, ebs = evidence()
        manifest["baseline_mode"] = "private_ssm"
        manifest["public_services_enabled"] = False
        manifest["public_endpoint_acceptance"] = False
        legacy_tables = [
            "blocks",
            "finality_certificates",
            "metadata",
        ]
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": {
                    "mode": "private_ssm",
                    "scope": (
                        "Public Testnet Pre-rollout Baseline / "
                        "Private SSM Read-only"
                    ),
                    "validator_count": 3,
                    "chain_id": 20260723,
                    "validators": [
                        {
                            "validator_id": f"validator-0{index}",
                            "instance_id": f"i-{index:017x}",
                            "signer_resource_digest": f"{index}" * 64,
                            "durable_timestamp_state":
                                "LEGACY_NOT_PERSISTED",
                            "timestamp_schema_tables": legacy_tables,
                        }
                        for index in range(1, 4)
                    ],
                    "finalized_head": {
                        "height": 100,
                        "hash": "0x" + "a" * 64,
                        "timestamp": None,
                        "timestamp_state": "LEGACY_NOT_PERSISTED",
                        "certificate_hash": "0x" + "b" * 64,
                    },
                    "quorum": {
                        "signed_power": 3,
                        "total_power": 3,
                        "validator_ids": list(gate.VALIDATOR_IDS),
                    },
                },
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertTrue(decision["accepted"], decision["failures"])

        explorer["readback"]["validators"][1][
            "durable_timestamp_state"
        ] = "DURABLE_PERSISTED"
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "private_ssm.validators.timestamp_schema:not_exact_three",
            decision["failures"],
        )

    def test_public_outage_binding_and_digest_tamper_fail_closed(self):
        manifest, explorer, ebs = evidence()
        outage = endpoint_outage()
        manifest.update(
            {
                "baseline_mode": "private_ssm",
                "public_services_enabled": True,
                "public_endpoint_acceptance": False,
                "public_endpoint_outage": outage,
            }
        )
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": True,
                "public_endpoint_acceptance": False,
                "public_endpoint_outage": outage,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": {
                    "mode": "private_ssm",
                    "scope": (
                        "Public Testnet Pre-rollout Baseline / "
                        "Private SSM Read-only"
                    ),
                    "validator_count": 3,
                    "validators": [
                        {
                            "validator_id": f"validator-0{index}",
                            "instance_id": f"i-{index:017x}",
                            "signer_resource_digest": f"{index}" * 64,
                        }
                        for index in range(1, 4)
                    ],
                    "finalized_head": {
                        "height": 100,
                        "hash": "0x" + "a" * 64,
                        "certificate_hash": "0x" + "b" * 64,
                    },
                    "quorum": {
                        "signed_power": 3,
                        "total_power": 3,
                        "validator_ids": list(gate.VALIDATOR_IDS),
                    },
                },
            }
        )
        manifest["public_endpoint_outage"] = dict(outage)
        manifest["public_endpoint_outage"]["observations"] = [
            dict(item) for item in outage["observations"]
        ]
        manifest["public_endpoint_outage"]["observations"][0][
            "body_base64"
        ] = base64.b64encode(b"tampered").decode("ascii")
        explorer["public_endpoint_outage"] = manifest[
            "public_endpoint_outage"
        ]
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "public_outage.health:body_digest_mismatch",
            decision["failures"],
        )

        manifest["public_endpoint_acceptance"] = True
        explorer["public_endpoint_acceptance"] = True
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "private_ssm.public_endpoint_acceptance:not_false",
            decision["failures"],
        )

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
        manifest["explorer_baseline_sha256"] = "0" * 64
        manifest["ebs_baseline_sha256"] = "0" * 64
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "manifest.explorer_baseline_sha256:mismatch", decision["failures"]
        )
        self.assertIn("manifest.ebs_baseline_sha256:mismatch", decision["failures"])

    def test_boundary_drift_is_rejected(self):
        manifest, explorer, ebs = evidence()
        manifest["release_boundary"]["mainnet_changed"] = True
        explorer["release_boundary"]["assets_moved"] = True
        ebs["release_boundary"]["bridge_activated"] = True
        decision = evaluate(manifest, explorer, ebs)
        self.assertGreaterEqual(decision["failure_count"], 3)

    def test_workflow_is_read_only_and_runtime_source_bound(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn(
            "source_commit:\n"
            "        description: Exact 40-character source commit bound to the "
            "runtime artifacts\n"
            "        required: true\n"
            "        type: string",
            workflow,
        )
        self.assertIn("SOURCE_COMMIT: ${{ inputs.source_commit }}", workflow)
        self.assertNotIn("SOURCE_COMMIT: ${{ github.sha }}", workflow)
        self.assertIn('[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]', workflow)

    def test_workflow_verifies_evidence_run_provenance(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("evidence_workflow_name:", workflow)
        self.assertNotIn("evidence_artifact_name:", workflow)
        self.assertIn("Verify pre-rollout evidence run provenance", workflow)
        self.assertIn(
            '"repos/${{ github.repository }}/actions/runs/${EVIDENCE_RUN_ID}"',
            workflow,
        )
        for required in (
            '.status == "completed"',
            '.conclusion == "success"',
            '.name == "JUNCA Runtime Release Evidence Collector"',
            '.path == ".github/workflows/junca-runtime-release-evidence-collector.yml"',
            '.event == "workflow_dispatch"',
            '.head_branch == "main"',
            ".repository.full_name == $repository",
            ".head_repository.full_name == $repository",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn(".head_sha == $source_commit", workflow)
        self.assertEqual(
            workflow.count("uses: actions/download-artifact@v4"),
            1,
        )
        self.assertEqual(
            workflow.count(
                "name: junca-runtime-release-evidence-${{ "
                "inputs.evidence_run_id }}"
            ),
            1,
        )
        self.assertIn("repository: ${{ github.repository }}", workflow)
        self.assertIn("github-token: ${{ github.token }}", workflow)
        self.assertIn("run-id: ${{ inputs.evidence_run_id }}", workflow)
        self.assertNotIn("gh run download", workflow)
        self.assertNotIn("pattern:", workflow)
        self.assertNotIn("artifact-ids:", workflow)
        self.assertNotIn("merge-multiple:", workflow)
        self.assertIn(
            'test "$(find evidence -type f | wc -l)" = 3',
            workflow,
        )
        for evidence_file in (
            "junca-runtime-pre-rollout-baseline.json",
            "junca-public-explorer-pre-rollout-baseline.json",
            "junca-validator-ebs-pre-rollout-baseline.json",
        ):
            self.assertIn(f"test -f evidence/{evidence_file}", workflow)

    def test_workflow_contains_no_deployment_or_apply_command(self):
        workflow = WORKFLOW.read_text(encoding="utf-8").lower()
        self.assertNotIn("terraform apply", workflow)
        self.assertNotIn("aws ec2 run-instances", workflow)
        self.assertNotIn("aws autoscaling", workflow)
        self.assertNotIn("aws imagebuilder create-image", workflow)


if __name__ == "__main__":
    unittest.main()
