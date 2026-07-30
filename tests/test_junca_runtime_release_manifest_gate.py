from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
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
REQUEST_SCHEMA = "junca-validator-ami-build-request/v2"
IMAGE_BUILDER_ARN = (
    "arn:aws:imagebuilder:us-east-1:595710543956:"
    "image/junca-validator-123/1.0.0/1"
)
PARENT_AMI = "ami-22222222222222222"
PARENT_AMI_NAME = (
    "al2023-ami-2023.12.20260724.0-kernel-6.18-x86_64"
)
DNF_RELEASEVER = "2023.12.20260724"
BOTO3_NEVRA = "python3-boto3-0:1.40.31-1.amzn2023.0.1.noarch"
BOTOCORE_NEVRA = (
    "python3-botocore-0:1.40.31-1.amzn2023.0.1.noarch"
)
FINALIZED_TIMESTAMP = 2_000_000_000
OBSERVED_AT = datetime.fromtimestamp(
    FINALIZED_TIMESTAMP + 30,
    timezone.utc,
).isoformat()


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
            "RequestSchema": REQUEST_SCHEMA,
            "ImageBuilderArn": IMAGE_BUILDER_ARN,
            "ParentAMIId": PARENT_AMI,
            "ParentAMIOwnerId": "137112412989",
            "ParentAMIName": PARENT_AMI_NAME,
            "ComponentSourceSHA256": "1" * 64,
            "DependencyLockSHA256": "2" * 64,
            "SupplyChainPolicySHA256": "3" * 64,
            "DnfReleasever": DNF_RELEASEVER,
            "Boto3NEVRA": BOTO3_NEVRA,
            "BotocoreNEVRA": BOTOCORE_NEVRA,
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
        "observed_runtime": copy.deepcopy(manifest["previous_runtime"]),
        "finalized_only": True,
        "read_only": True,
        "unsafe_rpc_rejection": True,
        "readback": {
            "mode": "public_endpoints",
            "observed_at": OBSERVED_AT,
            "finalized_head": {
                "height": 1,
                "hash": "0x" + "4" * 64,
                "timestamp": hex(FINALIZED_TIMESTAMP),
                "state_root": "0x" + "6" * 64,
                "certificate_hash": "0x" + "5" * 64,
            },
            "checks": {
                "health": "PASS",
                "explorer": {
                    "result": "PASS",
                    "finalized_height": 1,
                    "finalized_hash": "0x" + "4" * 64,
                    "signed_power": 3,
                    "total_power": 3,
                    "certificate_hash": "0x" + "5" * 64,
                    "peer_count": 2,
                },
                "safe_rpc": {
                    "result": "PASS",
                    "methods": list(gate.SAFE_RPC_METHODS),
                },
                "unsafe_rpc_rejection": {
                    "result": "PASS",
                    "methods": list(gate.UNSAFE_RPC_METHODS),
                },
            },
        },
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
        "migration_execution_binding": {
            "repository":
                "JAIOS-Governance/junca-social-ecosystem-chain",
            "run_id": "1",
            "head_sha": "4" * 40,
            "migration_request_sha256": "5" * 64,
        },
        "migration_validator_mappings": [
            {
                "validator_id": f"validator-0{index}",
                "instance_id": f"i-{index:017x}",
                "signer_arn": signers[index - 1]["resource_arn"],
                "state_volume_id": volumes[index - 1]["volume_id"],
                "rollback_snapshot_id":
                    volumes[index - 1]["rollback_snapshot_id"],
                "root_volume_id": f"vol-{index + 3:017x}",
            }
            for index in range(1, 4)
        ],
        "migration_finalized_head": {
            "height": 1,
            "hash": "0x" + "4" * 64,
            "certificate_hash": "0x" + "5" * 64,
        },
        "immutable_runtime_certificate_activation_pending": True,
        "observed_runtime": copy.deepcopy(manifest["previous_runtime"]),
        "migration_complete": True,
        "data_loss": False,
        "validator_volumes": volumes,
        "release_boundary": dict(BOUNDARY),
    }
    observed_runtimes = [
        {
            "validator_id": f"validator-0{index}",
            "instance_id": f"i-{index:017x}",
            "image_id": manifest["previous_runtime"]["ami_id"],
            "state": "running",
            "terraform_approved_ami": True,
            "candidate_ami": False,
            "root_volume_id": f"vol-{index + 3:017x}",
        }
        for index in range(1, 4)
    ]
    lineage = {
        "observed_runtime_ami_state":
            "EXACT_PRE_ROLLOUT_INVENTORY_NOT_CANDIDATE_ACCEPTANCE",
        "observed_validator_runtimes": observed_runtimes,
        "observed_runtime_ami_ids": [
            manifest["previous_runtime"]["ami_id"]
        ],
        "runtime_ami_drift_detected": False,
        "candidate_ami_preexisting": False,
        "migration_lineage_state": "RETAINED_STATE_LINEAGE_VERIFIED",
        "migration_retained_state_lineage_verified": True,
        "migration_instance_rotation_detected": False,
        "migration_root_volume_rotation_detected": False,
        "migration_original_validator_mappings":
            ebs["migration_validator_mappings"],
        "migration_current_validator_mappings":
            ebs["migration_validator_mappings"],
        "migration_retained_state_volume_ids": [
            item["volume_id"] for item in volumes
        ],
        "migration_retained_rollback_snapshot_ids": [
            item["rollback_snapshot_id"] for item in volumes
        ],
        "migration_retained_signer_arns": [
            item["resource_arn"] for item in signers
        ],
    }
    manifest.update(copy.deepcopy(lineage))
    explorer.update(copy.deepcopy(lineage))
    ebs.update(copy.deepcopy(lineage))
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


def private_ssm_readback(
    *,
    timestamp_state="DURABLE_PERSISTED",
    timestamp=2_000_000_000,
):
    tables = (
        [
            "block_timestamps",
            "blocks",
            "finality_certificates",
            "metadata",
        ]
        if timestamp_state == "DURABLE_PERSISTED"
        else ["blocks", "finality_certificates", "metadata"]
    )
    head = {
        "height": 1,
        "hash": "0x" + "4" * 64,
        "timestamp": timestamp,
        "timestamp_state": timestamp_state,
        "certificate_hash": "0x" + "5" * 64,
    }
    return {
        "mode": "private_ssm",
        "scope": (
            "Public Testnet Pre-rollout Baseline / Private SSM Read-only"
        ),
        "observed_at": "2033-05-18T03:34:20Z",
        "validator_count": 3,
        "chain_id": 20260723,
        "validators": [
            {
                "validator_id": f"validator-0{index}",
                "instance_id": f"i-{index:017x}",
                "signer_resource_digest": hashlib.sha256(
                    (
                        "arn:aws:kms:us-east-1:595710543956:key/"
                        f"validator-0{index}"
                    ).encode()
                ).hexdigest(),
                "peer_count": 2,
                "runtime_certificate_state": "ACTIVATION_PENDING",
                "durable_certificate_hash": head["certificate_hash"],
                "durable_timestamp_state": timestamp_state,
                "timestamp_schema_tables": tables,
            }
            for index in range(1, 4)
        ],
        "finalized_head": head,
        "immutable_runtime_certificate_activation_pending": True,
        "runtime_certificate_states": ["ACTIVATION_PENDING"] * 3,
        "durable_certificate_binding": {
            "height": head["height"],
            "hash": head["hash"],
            "certificate_hash": head["certificate_hash"],
            "validator_count": 3,
        },
        "quorum": {
            "signed_power": 3,
            "total_power": 3,
            "validator_ids": list(gate.VALIDATOR_IDS),
        },
    }


class RuntimeReleaseManifestGateTests(unittest.TestCase):
    def test_complete_candidate_passes(self):
        decision = evaluate(*evidence())
        self.assertTrue(decision["accepted"])
        self.assertEqual(decision["decision"], "PROMOTION_GATE_PASS")
        self.assertEqual(
            decision["candidate"]["ami_supply_chain"],
            {
                "request_schema": REQUEST_SCHEMA,
                "image_builder_arn": IMAGE_BUILDER_ARN,
                "parent_ami_id": PARENT_AMI,
                "parent_ami_owner_id": "137112412989",
                "parent_ami_name": PARENT_AMI_NAME,
                "component_source_sha256": "1" * 64,
                "dependency_lock_sha256": "2" * 64,
                "supply_chain_policy_sha256": "3" * 64,
                "dnf_releasever": DNF_RELEASEVER,
                "python3_boto3_nevra": BOTO3_NEVRA,
                "python3_botocore_nevra": BOTOCORE_NEVRA,
            },
        )

    def test_public_baseline_requires_exact_two_peer_quorum(self):
        for peer_count in (0, 1):
            with self.subTest(peer_count=peer_count):
                manifest, explorer, ebs = evidence()
                explorer["readback"]["checks"]["explorer"][
                    "peer_count"
                ] = peer_count
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertIn(
                    "public_endpoints.explorer_check:invalid",
                    decision["failures"],
                )

    def test_public_baseline_rejects_stale_finalized_head(self):
        manifest, explorer, ebs = evidence()
        explorer["readback"]["finalized_head"]["timestamp"] = hex(
            FINALIZED_TIMESTAMP - 121
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertFalse(decision["accepted"])
        self.assertIn(
            "public_endpoints.finalized_head:stale_or_future",
            decision["failures"],
        )

    def test_ami_supply_chain_provenance_is_fail_closed(self):
        replacements = {
            "RequestSchema": "junca-validator-ami-build-request/v1",
            "ImageBuilderArn": "",
            "ParentAMIId": "ami-invalid",
            "ParentAMIOwnerId": "000000000000",
            "ParentAMIName": "latest",
            "ComponentSourceSHA256": "invalid",
            "DependencyLockSHA256": "invalid",
            "SupplyChainPolicySHA256": "invalid",
            "DnfReleasever": "latest",
            "Boto3NEVRA": "python3-boto3",
            "BotocoreNEVRA": "python3-botocore",
        }
        for field, value in replacements.items():
            with self.subTest(field=field):
                manifest, explorer, ebs = evidence()
                manifest["ami_provenance"][field] = value
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertTrue(
                    any(
                        f"manifest.ami_provenance.{field}" in failure
                        for failure in decision["failures"]
                    ),
                    decision["failures"],
                )

    def test_unknown_security_semantics_fail_closed(self):
        mutations = (
            (
                "manifest",
                lambda manifest, explorer, ebs:
                    manifest.__setitem__("transaction_submission_enabled", True),
                "manifest.keys:not_exact",
            ),
            (
                "explorer",
                lambda manifest, explorer, ebs:
                    explorer.__setitem__("unknown_policy", {"unsafe": True}),
                "explorer.keys:not_exact",
            ),
            (
                "ebs",
                lambda manifest, explorer, ebs:
                    ebs.__setitem__("mainnet_changed", True),
                "ebs.keys:not_exact",
            ),
            (
                "release_boundary",
                lambda manifest, explorer, ebs:
                    manifest["release_boundary"].__setitem__(
                        "transaction_submission_enabled", True
                    ),
                "manifest.release_boundary.keys:not_exact",
            ),
            (
                "ami_provenance",
                lambda manifest, explorer, ebs:
                    manifest["ami_provenance"].__setitem__(
                        "UnknownPolicy", "allow"
                    ),
                "manifest.ami_provenance.keys:not_exact",
            ),
            (
                "signer",
                lambda manifest, explorer, ebs:
                    manifest["signer_bindings"][0].__setitem__(
                        "fallback_signer", True
                    ),
                "manifest.signer_binding.keys:not_exact",
            ),
            (
                "volume",
                lambda manifest, explorer, ebs:
                    ebs["validator_volumes"][0].__setitem__(
                        "replacement_allowed", True
                    ),
                "ebs.validator_volume.keys:not_exact",
            ),
        )
        for label, mutate, expected in mutations:
            manifest, explorer, ebs = evidence()
            mutate(manifest, explorer, ebs)
            with self.subTest(label=label):
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertIn(expected, decision["failures"])

    def test_security_relevant_values_fail_closed_when_tampered(self):
        mutations = (
            (
                "public_head",
                lambda manifest, explorer, ebs:
                    explorer["readback"]["finalized_head"].__setitem__(
                        "height", 0
                    ),
                "public_endpoints.finalized_head:invalid",
            ),
            (
                "public_health",
                lambda manifest, explorer, ebs:
                    explorer["readback"]["checks"].__setitem__(
                        "health", "FAIL"
                    ),
                "public_endpoints.health:not_pass",
            ),
            (
                "public_observed_at",
                lambda manifest, explorer, ebs:
                    explorer["readback"].__setitem__(
                        "observed_at", "not-a-time"
                    ),
                "public_endpoints.readback:invalid",
            ),
            (
                "observed_runtime",
                lambda manifest, explorer, ebs:
                    explorer["observed_runtime"].__setitem__(
                        "ami_id", "ami-22222222222222222"
                    ),
                "explorer.observed_runtime:mismatch",
            ),
            (
                "migration_repository",
                lambda manifest, explorer, ebs:
                    ebs["migration_execution_binding"].__setitem__(
                        "repository", "attacker/repository"
                    ),
                "ebs.migration_execution_binding:invalid",
            ),
            (
                "migration_run_type",
                lambda manifest, explorer, ebs:
                    ebs["migration_execution_binding"].__setitem__(
                        "run_id", 1
                    ),
                "ebs.migration_execution_binding:invalid",
            ),
            (
                "migration_head",
                lambda manifest, explorer, ebs:
                    ebs["migration_finalized_head"].__setitem__(
                        "certificate_hash", "invalid"
                    ),
                "ebs.migration_finalized_head:invalid",
            ),
            (
                "activation_pending",
                lambda manifest, explorer, ebs:
                    ebs.__setitem__(
                        "immutable_runtime_certificate_activation_pending",
                        False,
                    ),
                (
                    "ebs.immutable_runtime_certificate_activation_pending:"
                    "not_true"
                ),
            ),
            (
                "candidate_preexisting",
                lambda manifest, explorer, ebs: [
                    item.__setitem__("candidate_ami_preexisting", True)
                    for item in (manifest, explorer, ebs)
                ],
                "drift.candidate_ami_preexisting:not_false",
            ),
            (
                "runtime_candidate",
                lambda manifest, explorer, ebs: [
                    item["observed_validator_runtimes"][0].__setitem__(
                        "candidate_ami", True
                    )
                    for item in (manifest, explorer, ebs)
                ],
                "drift.observed_validator_runtimes:invalid",
            ),
            (
                "terraform_approved_relation",
                lambda manifest, explorer, ebs: [
                    (
                        item["observed_validator_runtimes"][0].__setitem__(
                            "terraform_approved_ami", False
                        ),
                        item.__setitem__(
                            "runtime_ami_drift_detected", True
                        ),
                    )
                    for item in (manifest, explorer, ebs)
                ],
                "drift.observed_validator_runtimes:invalid",
            ),
            (
                "retained_state",
                lambda manifest, explorer, ebs: [
                    item["migration_retained_state_volume_ids"].__setitem__(
                        0, "vol-99999999999999999"
                    )
                    for item in (manifest, explorer, ebs)
                ],
                "lineage.retained_state_volume_ids:mismatch",
            ),
            (
                "rotation_derivation",
                lambda manifest, explorer, ebs: [
                    item.__setitem__(
                        "migration_instance_rotation_detected", True
                    )
                    for item in (manifest, explorer, ebs)
                ],
                "lineage.instance_rotation:mismatch",
            ),
        )
        for label, mutate, expected in mutations:
            manifest, explorer, ebs = evidence()
            mutate(manifest, explorer, ebs)
            with self.subTest(label=label):
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertIn(expected, decision["failures"])

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
                "readback": private_ssm_readback(),
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertTrue(decision["accepted"], decision["failures"])

    def test_private_ssm_baseline_rejects_identity_head_and_quorum_drift(self):
        manifest, explorer, ebs = evidence()
        manifest["baseline_mode"] = "private_ssm"
        manifest["public_services_enabled"] = False
        manifest["public_endpoint_acceptance"] = False
        readback = private_ssm_readback()
        readback["validators"][1]["instance_id"] = (
            readback["validators"][0]["instance_id"]
        )
        readback["finalized_head"]["height"] = 0
        readback["finalized_head"]["hash"] = "bad"
        readback["finalized_head"]["certificate_hash"] = "bad"
        readback["quorum"]["signed_power"] = 2
        readback["quorum"]["validator_ids"] = [
            "validator-01",
            "validator-02",
        ]
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": readback,
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

    def test_private_ssm_rejects_signer_digest_not_bound_to_manifest(self):
        manifest, explorer, ebs = evidence()
        manifest["baseline_mode"] = "private_ssm"
        manifest["public_services_enabled"] = False
        manifest["public_endpoint_acceptance"] = False
        readback = private_ssm_readback()
        readback["validators"][1]["signer_resource_digest"] = "f" * 64
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": readback,
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertIn(
            "private_ssm.validators.signer_resource_digest:mismatch",
            decision["failures"],
        )

    def test_private_ssm_rejects_non_quorum_peer_counts(self):
        for peer_count in (0, 1, 3, True, None):
            with self.subTest(peer_count=peer_count):
                manifest, explorer, ebs = evidence()
                manifest["baseline_mode"] = "private_ssm"
                manifest["public_services_enabled"] = False
                manifest["public_endpoint_acceptance"] = False
                readback = private_ssm_readback()
                readback["validators"][0]["peer_count"] = peer_count
                explorer.update(
                    {
                        "schema_version":
                            "junca-private-ssm-pre-rollout-baseline/v1",
                        "baseline_mode": "private_ssm",
                        "public_services_enabled": False,
                        "public_endpoint_acceptance": False,
                        "unsafe_rpc_rejection":
                            "NOT_APPLICABLE_PRIVATE_SSM",
                        "readback": readback,
                    }
                )
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertIn(
                    "private_ssm.peer_count:not_exact_two",
                    decision["failures"],
                )

    def test_private_ssm_rejects_stale_or_future_finalized_head(self):
        for timestamp in (2_000_000_000 - 121, 2_000_000_000 + 61):
            with self.subTest(timestamp=timestamp):
                manifest, explorer, ebs = evidence()
                manifest["baseline_mode"] = "private_ssm"
                manifest["public_services_enabled"] = False
                manifest["public_endpoint_acceptance"] = False
                readback = private_ssm_readback(timestamp=timestamp)
                explorer.update(
                    {
                        "schema_version":
                            "junca-private-ssm-pre-rollout-baseline/v1",
                        "baseline_mode": "private_ssm",
                        "public_services_enabled": False,
                        "public_endpoint_acceptance": False,
                        "unsafe_rpc_rejection":
                            "NOT_APPLICABLE_PRIVATE_SSM",
                        "readback": readback,
                    }
                )
                decision = evaluate(manifest, explorer, ebs)
                self.assertFalse(decision["accepted"])
                self.assertIn(
                    "private_ssm.finalized_head:stale_or_future",
                    decision["failures"],
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
                "readback": private_ssm_readback(),
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
        explorer.update(
            {
                "schema_version":
                    "junca-private-ssm-pre-rollout-baseline/v1",
                "baseline_mode": "private_ssm",
                "public_services_enabled": False,
                "public_endpoint_acceptance": False,
                "unsafe_rpc_rejection": "NOT_APPLICABLE_PRIVATE_SSM",
                "readback": private_ssm_readback(
                    timestamp_state="LEGACY_NOT_PERSISTED",
                    timestamp=None,
                ),
            }
        )
        decision = evaluate(manifest, explorer, ebs)
        self.assertFalse(decision["accepted"])
        self.assertIn(
            "private_ssm.finalized_head:freshness_unverifiable",
            decision["failures"],
        )

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
        self.assertIn("ref: ${{ inputs.source_commit }}", workflow)
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
        self.assertIn(
            "Verify exact child run binding before manifest output",
            workflow,
        )
        self.assertIn(
            '"repos/${GITHUB_REPOSITORY}/actions/runs/${EVIDENCE_RUN_ID}"',
            workflow,
        )
        for required in (
            '.status == "completed"',
            '.conclusion == "success"',
            '.name == "JUNCA Runtime Release Evidence Collector"',
            '.path == ".github/workflows/junca-runtime-release-evidence-collector-v2.yml"',
            '.event == "workflow_dispatch"',
            ".head_branch == $execution_ref",
            ".head_sha == $source_commit",
            ".repository.full_name == $repository",
            ".head_repository.full_name == $repository",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn(
            ".github/workflows/junca-runtime-release-evidence-collector.yml",
            workflow,
        )
        self.assertEqual(
            workflow.count(
                "uses: actions/download-artifact@"
                "d3f86a106a0bac45b974a628896c90dbdf5c8093"
            ),
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
        self.assertIn("Prove isolated evidence path is absent", workflow)
        self.assertIn("test ! -e downloaded-release-evidence", workflow)
        self.assertIn("test ! -L downloaded-release-evidence", workflow)
        self.assertIn("path: downloaded-release-evidence", workflow)
        self.assertNotIn("\n          path: evidence\n", workflow)
        self.assertNotIn("gh run download", workflow)
        self.assertNotIn("pattern:", workflow)
        self.assertNotIn("artifact-ids:", workflow)
        self.assertNotIn("merge-multiple:", workflow)
        self.assertIn(
            "find downloaded-release-evidence \\\n"
            "              -mindepth 1 -maxdepth 1",
            workflow,
        )
        self.assertIn(
            "sha256sum junca-runtime-release-manifest-decision.json",
            workflow,
        )
        for evidence_file in (
            "junca-runtime-pre-rollout-baseline.json",
            "junca-public-explorer-pre-rollout-baseline.json",
            "junca-validator-ebs-pre-rollout-baseline.json",
        ):
            isolated_path = f"downloaded-release-evidence/{evidence_file}"
            self.assertIn(f"test -f {isolated_path}", workflow)
            self.assertIn(f"test ! -L {isolated_path}", workflow)
            self.assertNotIn(f" evidence/{evidence_file}", workflow)
            self.assertIn(isolated_path, workflow)

    def test_workflow_contains_no_deployment_or_apply_command(self):
        workflow = WORKFLOW.read_text(encoding="utf-8").lower()
        self.assertNotIn("terraform apply", workflow)
        self.assertNotIn("aws ec2 run-instances", workflow)
        self.assertNotIn("aws autoscaling", workflow)
        self.assertNotIn("aws imagebuilder create-image", workflow)


if __name__ == "__main__":
    unittest.main()
