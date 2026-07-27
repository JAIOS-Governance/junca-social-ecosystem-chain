from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "junca_runtime_release_evidence_collector.py"
GATE_SCRIPT = ROOT / "scripts" / "junca_runtime_release_manifest_gate.py"
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "junca-runtime-release-evidence-collector.yml"
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load("runtime_release_evidence_collector", SCRIPT)
gate = load("runtime_release_manifest_gate_for_collector", GATE_SCRIPT)

COMMIT = "a" * 40
NODE = "b" * 64
GENESIS = "c" * 64
CANDIDATE_AMI = "ami-0123456789abcdef0"
CURRENT_AMI = "ami-11111111111111111"
CURRENT_COMMIT = "d" * 40
CURRENT_NODE = "e" * 64
CURRENT_GENESIS = "f" * 64
REQUEST = "9" * 64
MIGRATION_RUN_ID = "123456789"
MIGRATION_HEAD = "8" * 40
MIGRATION_REQUEST = "7" * 64
CHAIN_ID = 20260723
FINALIZED_HEIGHT = 100
FINALIZED_HASH = "0x" + "1" * 64


def finality_certificate():
    vote_hashes = ["0x" + str(index) * 64 for index in range(3, 6)]
    body = {
        "block_hash": FINALIZED_HASH,
        "chain_id": CHAIN_ID,
        "height": FINALIZED_HEIGHT,
        "round": 0,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": [
            "validator-01",
            "validator-02",
            "validator-03",
        ],
        "vote_hashes": vote_hashes,
    }
    certificate_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(
            body, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "junca-finality-certificate/v1",
        **body,
        "certificate_hash": certificate_hash,
        "finality_status": "FINALIZED",
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def aws_tags(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in values.items()]


def fixture():
    candidate = {
        "schema_version": "junca-validator-ami-build/v1",
        "state": "AMI_VERIFIED",
        "network": "Public Testnet",
        "notice": "Public Testnet / No Monetary Value",
        "ami_id": CANDIDATE_AMI,
        "source_commit": COMMIT,
        "node_artifact_sha256": NODE,
        "genesis_sha256": GENESIS,
        "request_sha256": REQUEST,
        "terraform_state_changed": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    signers = [
        f"arn:aws:kms:us-east-1:595710543956:key/signer-{index}"
        for index in range(1, 4)
    ]
    bootstrap = {
        "aws_account_id": {"value": "595710543956"},
        "aws_region": {"value": "us-east-1"},
        "validator_signer_arns": {"value": signers},
    }
    instance_ids = [f"i-{index:017x}" for index in range(1, 4)]
    volume_ids = [f"vol-{index:017x}" for index in range(1, 4)]
    snapshot_ids = [f"snap-{index:017x}" for index in range(1, 4)]
    root_volume_ids = [f"vol-{index + 100:017x}" for index in range(1, 4)]
    state_volumes = [
        {
            "validator_id": f"validator-0{index}",
            "volume_id": volume_ids[index - 1],
            "rollback_snapshot_id": snapshot_ids[index - 1],
            "migration_required": False,
            "migration_accepted": True,
        }
        for index in range(1, 4)
    ]
    public = {
        "aws_account_id": {"value": "595710543956"},
        "region": {"value": "us-east-1"},
        "runtime_boundary": {
            "value": {
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            }
        },
        "approved_node_ami_readback": {
            "value": {
                "id": CURRENT_AMI,
                "owner_id": "595710543956",
                "source_commit": CURRENT_COMMIT,
                "node_sha256": CURRENT_NODE,
                "genesis_sha256": CURRENT_GENESIS,
            }
        },
        "validator_instance_ids": {"value": instance_ids},
        "validator_state_volume_readback": {"value": state_volumes},
        "public_services_acceptance_readback": {
            "value": {"enabled": True}
        },
    }
    images = {
        "Images": [
            {
                "ImageId": CANDIDATE_AMI,
                "OwnerId": "595710543956",
                "State": "available",
                "Tags": aws_tags(
                    {
                        "Network": "Public Testnet",
                        "Governance": "JAIOS Institutional Governance",
                        "SourceCommit": COMMIT,
                        "NodeArtifactSHA256": NODE,
                        "GenesisSHA256": GENESIS,
                        "RequestDigest": REQUEST,
                        "MainnetChanged": "false",
                        "AssetsMoved": "false",
                        "BridgeActivated": "false",
                    }
                ),
            }
        ]
    }
    instances = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": instance_id,
                        "ImageId": CURRENT_AMI,
                        "State": {"Name": "running"},
                        "RootDeviceName": "/dev/xvda",
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/xvda",
                                "Ebs": {
                                    "VolumeId": root_volume_ids[index]
                                },
                            }
                        ],
                    }
                ]
            }
            for index, instance_id in enumerate(instance_ids)
        ]
    }
    volumes = {
        "Volumes": [
            {
                "VolumeId": volume_id,
                "Encrypted": True,
                "VolumeType": "gp3",
                "Attachments": [
                    {"InstanceId": instance_id, "State": "attached"}
                ],
                "Tags": aws_tags(
                    {
                        "StatePath": "/var/lib/junca",
                        "MigrationRequired": "false",
                        "JuncaMigrationState": "VERIFIED_PASS",
                        "JuncaFilesystemVerified": "true",
                        "JuncaStateStoreIntegrity": "true",
                        "JuncaFinalityCertificateBackfilled": "true",
                        "JuncaRollbackSnapshotId": snapshot_id,
                        "PublicTestnetOnly": "true",
                    }
                ),
            }
            for volume_id, instance_id, snapshot_id in zip(
                volume_ids, instance_ids, snapshot_ids, strict=True
            )
        ]
    }
    snapshots = {
        "Snapshots": [
            {
                "SnapshotId": snapshot_id,
                "State": "completed",
                "OwnerId": "595710543956",
                "Encrypted": True,
            }
            for snapshot_id, root_volume_id in zip(
                snapshot_ids, root_volume_ids, strict=True
            )
        ]
    }
    for snapshot, root_volume_id in zip(
        snapshots["Snapshots"], root_volume_ids, strict=True
    ):
        snapshot["VolumeId"] = root_volume_id
    endpoints = {
        "status": "PASS",
        "scope": "Public Testnet Runtime Acceptance / Read-only",
        "observed_at": "2026-07-27T00:00:00+00:00",
        "finalized_head": {"height": 100, "hash": "0xabc"},
        "checks": {
            "health": "PASS",
            "explorer": {
                "result": "PASS",
                "signed_power": 3,
                "total_power": 3,
            },
            "safe_rpc": {"result": "PASS"},
            "unsafe_rpc_rejection": {"result": "PASS"},
        },
    }
    values = {
        "candidate": candidate,
        "bootstrap": bootstrap,
        "public": public,
        "images": images,
        "instances": instances,
        "volumes": volumes,
        "snapshots": snapshots,
        "endpoints": endpoints,
        "private_validator_health": None,
    }
    values["migration_evidence"] = migration_evidence(values)
    return values


def migration_evidence(values):
    instance_ids = values["public"]["validator_instance_ids"]["value"]
    state_outputs = values["public"][
        "validator_state_volume_readback"
    ]["value"]
    signers = values["bootstrap"]["validator_signer_arns"]["value"]
    root_volume_ids = [
        reservation["Instances"][0]["BlockDeviceMappings"][0]["Ebs"][
            "VolumeId"
        ]
        for reservation in values["instances"]["Reservations"]
    ]
    mappings = [
        {
            "validator_id": f"validator-0{index}",
            "instance_id": instance_id,
            "signer_arn": signer,
            "state_volume_id": state_output["volume_id"],
            "rollback_snapshot_id": state_output["rollback_snapshot_id"],
            "root_volume_id": root_volume_id,
        }
        for index, (
            instance_id,
            signer,
            state_output,
            root_volume_id,
        ) in enumerate(
            zip(
                instance_ids,
                signers,
                state_outputs,
                root_volume_ids,
                strict=True,
            ),
            start=1,
        )
    ]
    return {
        "schema_version": "junca-validator-state-migration/v1",
        "state": "VERIFIED_PASS",
        "network": "Public Testnet",
        "migration_run_id": MIGRATION_RUN_ID,
        "migration_run_head_sha": MIGRATION_HEAD,
        "migration_request_sha256": MIGRATION_REQUEST,
        "execution_binding": {
            "repository":
                "JAIOS-Governance/junca-social-ecosystem-chain",
            "run_id": MIGRATION_RUN_ID,
            "run_attempt": 1,
            "head_sha": MIGRATION_HEAD,
            "migration_request_sha256": MIGRATION_REQUEST,
            "github_event_sha256": "6" * 64,
            "migration_token": f"{MIGRATION_RUN_ID}-1",
        },
        "instance_ids": list(instance_ids),
        "state_volume_ids": [
            item["volume_id"] for item in state_outputs
        ],
        "rollback_snapshot_ids": [
            item["rollback_snapshot_id"] for item in state_outputs
        ],
        "validator_mappings": mappings,
        "runtime_mount_verified": True,
        "immutable_runtime_mount_activation_pending": True,
        "immutable_runtime_certificate_activation_pending": True,
        "finalized_head": {
            "height": FINALIZED_HEIGHT,
            "hash": FINALIZED_HASH,
            "certificate_hash":
                finality_certificate()["certificate_hash"],
        },
        "bootstrap_changed": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


def private_health(values):
    instance_ids = values["public"]["validator_instance_ids"]["value"]
    signer_arns = values["bootstrap"]["validator_signer_arns"]["value"]
    certificate = finality_certificate()
    certificate_hash = certificate["certificate_hash"]
    validators = []
    for index, (instance_id, signer_arn) in enumerate(
        zip(instance_ids, signer_arns, strict=True), start=1
    ):
        validator_id = f"validator-0{index}"
        validators.append(
            {
                "validator_id": validator_id,
                "instance_id": instance_id,
                "durable_state": {
                    "quick_check": "ok",
                    "head": {
                        "height": FINALIZED_HEIGHT,
                        "block_hash": FINALIZED_HASH,
                        "finalized": 1,
                        "certificate_hash": certificate_hash,
                    },
                    "certificate": dict(certificate),
                },
                "health": {
                    "status": "healthy",
                    "network": "Public Testnet / No Monetary Value",
                    "chain_id": CHAIN_ID,
                    "validator_id": validator_id,
                    "head_height": FINALIZED_HEIGHT,
                    "head_hash": FINALIZED_HASH,
                    "head_timestamp": 2_000_000_000,
                    "signer_resource_digest": hashlib.sha256(
                        signer_arn.encode("utf-8")
                    ).hexdigest(),
                    "private_key_material_accepted": False,
                    "mainnet_changed": False,
                    "assets_moved": False,
                    "bridge_activated": False,
                    "consensus": {
                        "schema_version":
                            "junca-public-testnet-consensus-runtime/v1",
                        "chain_id": CHAIN_ID,
                        "head_height": FINALIZED_HEIGHT,
                        "required_vote_count": 3,
                        "last_certificate_hash": None,
                        "last_certificate": None,
                        "authenticated_vote_count": 0,
                        "private_key_material_accepted": False,
                        "mainnet_changed": False,
                        "assets_moved": False,
                        "bridge_activated": False,
                    },
                },
            }
        )
    return {
        "schema_version": "junca-private-ssm-validator-baseline/v1",
        "status": "PASS",
        "scope": "Public Testnet Runtime Acceptance / Private SSM Read-only",
        "validators": validators,
    }


class EvidenceCollectorTests(unittest.TestCase):
    def collect(self, values):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "release"
        paths = collector.collect(
            **values,
            migration_evidence_sha256="7" * 64,
            expected_migration_run_id=MIGRATION_RUN_ID,
            expected_migration_head_sha=MIGRATION_HEAD,
            expected_migration_request_sha256=MIGRATION_REQUEST,
            expected_source_commit=COMMIT,
            output_dir=output,
        )
        return output, paths

    def test_complete_readback_emits_exact_gate_compatible_evidence(self):
        output, paths = self.collect(fixture())
        self.assertEqual(
            {path.name for path in output.iterdir()},
            {
                "junca-runtime-pre-rollout-baseline.json",
                "junca-public-explorer-pre-rollout-baseline.json",
                "junca-validator-ebs-pre-rollout-baseline.json",
            },
        )
        manifest, explorer, ebs = (
            json.loads(path.read_text(encoding="utf-8")) for path in paths
        )
        decision = gate.evaluate(
            manifest,
            explorer,
            ebs,
            explorer_evidence_sha256=collector.digest(paths[1]),
            ebs_evidence_sha256=collector.digest(paths[2]),
            expected_source_commit=COMMIT,
            expected_artifact_sha256=NODE,
            expected_genesis_sha256=GENESIS,
        )
        self.assertTrue(decision["accepted"], decision["failures"])
        self.assertEqual(decision["decision"], "PROMOTION_GATE_PASS")
        self.assertEqual(decision["phase"], "PREDEPLOYMENT_READINESS")
        self.assertFalse(explorer["candidate_accepted"])
        self.assertEqual(explorer["baseline_mode"], "public_endpoints")
        self.assertEqual(manifest["baseline_mode"], "public_endpoints")
        self.assertEqual(manifest["previous_runtime"]["ami_id"], CURRENT_AMI)
        self.assertEqual(explorer["observed_runtime"]["ami_id"], CURRENT_AMI)
        self.assertEqual(
            ebs["migration_execution_binding"]["run_id"],
            MIGRATION_RUN_ID,
        )
        self.assertEqual(
            len(ebs["migration_validator_mappings"]),
            3,
        )

    def test_private_ssm_readback_replaces_public_endpoint_requirement(self):
        values = fixture()
        values["public"]["public_services_acceptance_readback"]["value"][
            "enabled"
        ] = False
        values["endpoints"] = None
        values["private_validator_health"] = private_health(values)
        output, paths = self.collect(values)
        manifest, runtime, ebs = (
            json.loads(path.read_text(encoding="utf-8")) for path in paths
        )
        self.assertEqual(manifest["baseline_mode"], "private_ssm")
        self.assertEqual(
            runtime["schema_version"],
            "junca-private-ssm-pre-rollout-baseline/v1",
        )
        self.assertEqual(runtime["readback"]["validator_count"], 3)
        self.assertEqual(runtime["readback"]["quorum"]["signed_power"], 3)
        self.assertEqual(
            runtime["readback"]["runtime_certificate_states"],
            ["ACTIVATION_PENDING"] * 3,
        )
        self.assertTrue(
            runtime["readback"][
                "immutable_runtime_certificate_activation_pending"
            ]
        )
        self.assertEqual(
            ebs["migration_finalized_head"],
            values["migration_evidence"]["finalized_head"],
        )
        decision = gate.evaluate(
            manifest,
            runtime,
            ebs,
            explorer_evidence_sha256=collector.digest(paths[1]),
            ebs_evidence_sha256=collector.digest(paths[2]),
            expected_source_commit=COMMIT,
            expected_artifact_sha256=NODE,
            expected_genesis_sha256=GENESIS,
        )
        self.assertTrue(decision["accepted"], decision["failures"])

    def test_private_ssm_readback_recovers_a_public_endpoint_outage(self):
        values = fixture()
        values["endpoints"] = {
            "status": "FAIL",
            "scope": "Public Testnet Runtime Acceptance / Read-only",
            "observed_at": "2026-07-27T20:21:32+00:00",
            "endpoints": {
                "health": "https://health.jaios-governance.org/health",
                "explorer": (
                    "https://explorer.jaios-governance.org/explorer.json"
                ),
                "rpc": "https://rpc.jaios-governance.org/",
            },
            "error": (
                "https://health.jaios-governance.org/health: "
                "endpoint unavailable"
            ),
        }
        values["private_validator_health"] = private_health(values)
        _, paths = self.collect(values)
        manifest, runtime, ebs = (
            json.loads(path.read_text(encoding="utf-8")) for path in paths
        )
        self.assertEqual(manifest["baseline_mode"], "private_ssm")
        self.assertEqual(runtime["baseline_mode"], "private_ssm")
        self.assertEqual(
            runtime["readback"]["public_endpoint_outage"]["status"],
            "FAIL",
        )
        self.assertEqual(
            runtime["readback"]["public_endpoint_outage"]["error"],
            values["endpoints"]["error"],
        )
        decision = gate.evaluate(
            manifest,
            runtime,
            ebs,
            explorer_evidence_sha256=collector.digest(paths[1]),
            ebs_evidence_sha256=collector.digest(paths[2]),
            expected_source_commit=COMMIT,
            expected_artifact_sha256=NODE,
            expected_genesis_sha256=GENESIS,
        )
        self.assertTrue(decision["accepted"], decision["failures"])

    def test_public_endpoint_outage_requires_private_ssm_readback(self):
        values = fixture()
        values["endpoints"] = {
            "status": "FAIL",
            "scope": "Public Testnet Runtime Acceptance / Read-only",
            "observed_at": "2026-07-27T20:21:32+00:00",
            "endpoints": {
                "health": "https://health.jaios-governance.org/health",
                "explorer": (
                    "https://explorer.jaios-governance.org/explorer.json"
                ),
                "rpc": "https://rpc.jaios-governance.org/",
            },
            "error": "health endpoint unavailable",
        }
        with self.assertRaisesRegex(
            collector.EvidenceError,
            "private_ssm:required_for_public_endpoint_outage",
        ):
            self.collect(values)

    def test_private_ssm_head_certificate_and_boundary_drift_fail_closed(self):
        values = fixture()
        values["public"]["public_services_acceptance_readback"]["value"][
            "enabled"
        ] = False
        values["endpoints"] = None
        values["private_validator_health"] = private_health(values)
        values["private_validator_health"]["validators"][1]["health"][
            "head_hash"
        ] = "0x" + "3" * 64
        with self.assertRaisesRegex(
            collector.EvidenceError, "migration_head:mismatch"
        ):
            self.collect(values)

        values = fixture()
        values["public"]["public_services_acceptance_readback"]["value"][
            "enabled"
        ] = False
        values["endpoints"] = None
        values["private_validator_health"] = private_health(values)
        values["private_validator_health"]["validators"][2]["health"][
            "bridge_activated"
        ] = True
        with self.assertRaisesRegex(
            collector.EvidenceError, "bridge_activated"
        ):
            self.collect(values)

    def test_null_live_certificate_requires_validated_activation_transition(self):
        mutations = (
            (
                "pending_false",
                lambda values: values["migration_evidence"].update(
                    {
                        "immutable_runtime_certificate_activation_pending":
                            False
                    }
                ),
                "activation_not_pending",
            ),
            (
                "pending_missing",
                lambda values: values["migration_evidence"].pop(
                    "immutable_runtime_certificate_activation_pending"
                ),
                "not_bool",
            ),
            (
                "partial_null_hash",
                lambda values: values["private_validator_health"][
                    "validators"
                ][0]["health"]["consensus"].update(
                    {
                        "last_certificate_hash":
                            finality_certificate()["certificate_hash"]
                    }
                ),
                "partial_null",
            ),
            (
                "partial_null_votes",
                lambda values: values["private_validator_health"][
                    "validators"
                ][1]["health"]["consensus"].update(
                    {"authenticated_vote_count": 3}
                ),
                "partial_null",
            ),
            (
                "boolean_vote_count",
                lambda values: values["private_validator_health"][
                    "validators"
                ][2]["health"]["consensus"].update(
                    {"authenticated_vote_count": False}
                ),
                "partial_null",
            ),
        )
        for name, mutate, error in mutations:
            with self.subTest(name=name):
                values = fixture()
                values["public"][
                    "public_services_acceptance_readback"
                ]["value"]["enabled"] = False
                values["endpoints"] = None
                values["private_validator_health"] = private_health(values)
                mutate(values)
                with self.assertRaisesRegex(
                    collector.EvidenceError, error
                ):
                    self.collect(values)

    def test_live_certificate_is_accepted_without_activation_pending(self):
        values = fixture()
        values["public"]["public_services_acceptance_readback"]["value"][
            "enabled"
        ] = False
        values["endpoints"] = None
        values["migration_evidence"][
            "immutable_runtime_certificate_activation_pending"
        ] = False
        values["private_validator_health"] = private_health(values)
        certificate = finality_certificate()
        for item in values["private_validator_health"]["validators"]:
            item["health"]["consensus"].update(
                {
                    "last_certificate_hash":
                        certificate["certificate_hash"],
                    "last_certificate": dict(certificate),
                    "authenticated_vote_count": 3,
                }
            )
        _, paths = self.collect(values)
        runtime = json.loads(paths[1].read_text(encoding="utf-8"))
        self.assertEqual(
            runtime["readback"]["runtime_certificate_states"],
            ["LIVE"] * 3,
        )
        self.assertFalse(
            runtime["readback"][
                "immutable_runtime_certificate_activation_pending"
            ]
        )

    def test_three_durable_certificate_bindings_must_match_migration(self):
        mutations = (
            (
                "missing",
                lambda values: values["private_validator_health"][
                    "validators"
                ][0].pop("durable_state"),
                "durable_state:invalid",
            ),
            (
                "quick_check",
                lambda values: values["private_validator_health"][
                    "validators"
                ][0]["durable_state"].update(
                    {"quick_check": "corrupt"}
                ),
                "durable_state:invalid",
            ),
            (
                "height",
                lambda values: values["private_validator_health"][
                    "validators"
                ][1]["durable_state"]["head"].update(
                    {"height": FINALIZED_HEIGHT - 1}
                ),
                "durable_head:mismatch",
            ),
            (
                "head_hash",
                lambda values: values["private_validator_health"][
                    "validators"
                ][2]["durable_state"]["head"].update(
                    {"block_hash": "0x" + "9" * 64}
                ),
                "durable_head:mismatch",
            ),
            (
                "certificate_hash",
                lambda values: values["private_validator_health"][
                    "validators"
                ][0]["durable_state"]["head"].update(
                    {"certificate_hash": "0x" + "9" * 64}
                ),
                "durable_head:mismatch",
            ),
            (
                "boolean_finalized",
                lambda values: values["private_validator_health"][
                    "validators"
                ][0]["durable_state"]["head"].update(
                    {"finalized": True}
                ),
                "durable_head:mismatch",
            ),
            (
                "certificate_body",
                lambda values: values["private_validator_health"][
                    "validators"
                ][1]["durable_state"]["certificate"].update(
                    {"round": 1}
                ),
                "certificate_hash:mismatch",
            ),
            (
                "certificate_boundary",
                lambda values: values["private_validator_health"][
                    "validators"
                ][2]["durable_state"]["certificate"].update(
                    {"bridge_activated": True}
                ),
                "bridge_activated:not_false",
            ),
        )
        for name, mutate, error in mutations:
            with self.subTest(name=name):
                values = fixture()
                values["public"][
                    "public_services_acceptance_readback"
                ]["value"]["enabled"] = False
                values["endpoints"] = None
                values["private_validator_health"] = private_health(values)
                mutate(values)
                with self.assertRaisesRegex(
                    collector.EvidenceError, error
                ):
                    self.collect(values)

    def test_migration_finalized_head_and_boundaries_fail_closed(self):
        mutations = (
            (
                "height",
                lambda evidence: evidence["finalized_head"].update(
                    {"height": 0}
                ),
                "finalized_head.height",
            ),
            (
                "hash",
                lambda evidence: evidence["finalized_head"].update(
                    {"hash": "0x123"}
                ),
                "finalized_head.hash",
            ),
            (
                "certificate_hash",
                lambda evidence: evidence["finalized_head"].update(
                    {"certificate_hash": "0x123"}
                ),
                "finalized_head.certificate_hash",
            ),
            (
                "extra_finalized_field",
                lambda evidence: evidence["finalized_head"].update(
                    {"untrusted": True}
                ),
                "finalized_head:invalid",
            ),
            (
                "mainnet",
                lambda evidence: evidence.update(
                    {"mainnet_changed": True}
                ),
                "mainnet_changed:not_false",
            ),
            (
                "assets",
                lambda evidence: evidence.update({"assets_moved": True}),
                "assets_moved:not_false",
            ),
            (
                "bridge",
                lambda evidence: evidence.update(
                    {"bridge_activated": True}
                ),
                "bridge_activated:not_false",
            ),
        )
        for name, mutate, error in mutations:
            with self.subTest(name=name):
                values = fixture()
                mutate(values["migration_evidence"])
                with self.assertRaisesRegex(
                    collector.EvidenceError, error
                ):
                    self.collect(values)

    def test_missing_migration_marker_fails_closed(self):
        values = fixture()
        values["volumes"]["Volumes"][0]["Tags"] = [
            item
            for item in values["volumes"]["Volumes"][0]["Tags"]
            if item["Key"] != "JuncaStateStoreIntegrity"
        ]
        with self.assertRaisesRegex(
            collector.EvidenceError,
            "JuncaStateStoreIntegrity",
        ):
            self.collect(values)

    def test_migration_execution_mapping_arrays_and_mount_flags_are_bound(self):
        mutations = (
            (
                "execution",
                lambda evidence: evidence["execution_binding"].update(
                    {"head_sha": "0" * 40}
                ),
                "execution_binding",
            ),
            (
                "mapping",
                lambda evidence: evidence["validator_mappings"][1].update(
                    {"root_volume_id": "vol-99999999999999999"}
                ),
                "validator_mappings.validator-02",
            ),
            (
                "array",
                lambda evidence: evidence["instance_ids"].reverse(),
                "instance_ids",
            ),
            (
                "runtime_mount",
                lambda evidence: evidence.update(
                    {"runtime_mount_verified": False}
                ),
                "runtime_mount_verified",
            ),
            (
                "immutable_activation",
                lambda evidence: evidence.update(
                    {
                        "immutable_runtime_mount_activation_pending":
                            False
                    }
                ),
                "immutable_runtime_mount_activation_pending",
            ),
        )
        for name, mutate, error in mutations:
            with self.subTest(name=name):
                values = fixture()
                mutate(values["migration_evidence"])
                with self.assertRaisesRegex(
                    collector.EvidenceError, error
                ):
                    self.collect(values)

        values = fixture()
        values["snapshots"]["Snapshots"][1]["VolumeId"] = (
            "vol-99999999999999999"
        )
        with self.assertRaisesRegex(
            collector.EvidenceError, "snapshot_root"
        ):
            self.collect(values)

    def test_stale_instance_or_boundary_drift_fails_closed(self):
        values = fixture()
        values["instances"]["Reservations"][1]["Instances"][0]["ImageId"] = (
            CANDIDATE_AMI
        )
        with self.assertRaisesRegex(
            collector.EvidenceError,
            "unexpected_current_ami",
        ):
            self.collect(values)

        values = fixture()
        values["public"]["runtime_boundary"]["value"]["bridge_activated"] = True
        with self.assertRaisesRegex(collector.EvidenceError, "bridge_activated"):
            self.collect(values)

    def test_workflow_is_read_only_and_uploads_only_three_release_files(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        forbidden = (
            "terraform plan",
            "terraform apply",
            "terraform import",
            "terraform state ",
            "aws ec2 create-",
            "aws ec2 modify-",
            "aws ec2 attach-",
            "aws ec2 detach-",
            "aws ec2 create-tags",
            "aws route53 change-",
        )
        for command in forbidden:
            self.assertNotIn(command, workflow)
        self.assertIn("terraform -chdir=infra/aws/bootstrap output -json", workflow)
        self.assertIn("terraform -chdir=infra/aws/public-testnet output -json", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertNotIn("ref: ${{ env.SOURCE_COMMIT }}", workflow)
        self.assertIn(
            '.path == ".github/workflows/junca-validator-ami-build.yml"',
            workflow,
        )
        self.assertIn(
            '.path == ".github/workflows/junca-validator-state-migration.yml"',
            workflow,
        )
        self.assertIn('.event == "push"', workflow)
        self.assertIn("MIGRATION_EVIDENCE_SHA256", workflow)
        self.assertIn(
            "junca-validator-state-migration-binding.json",
            workflow,
        )
        self.assertIn(
            ".migration_evidence_sha256 == $evidence",
            workflow,
        )
        self.assertIn(".runtime_mount_verified == true", workflow)
        self.assertIn(
            ".immutable_runtime_mount_activation_pending == true",
            workflow,
        )
        self.assertIn(
            ".immutable_runtime_certificate_activation_pending == true",
            workflow,
        )
        self.assertIn(
            '.certificate_hash\n'
            '                    | test("^0x[0-9a-f]{64}$")',
            workflow,
        )
        self.assertIn("--expected-migration-run-id", workflow)
        self.assertIn("--expected-migration-head-sha", workflow)
        self.assertIn(
            "--expected-migration-request-sha256", workflow
        )
        self.assertNotIn(
            '.event == "workflow_dispatch" and\n'
            "            .head_branch == \"main\" and\n"
            "            .head_sha == $head",
            workflow[
                workflow.find("migration_run_json=") :
                workflow.find("- uses: actions/checkout@v4")
            ],
        )
        self.assertIn(
            ".public_services_acceptance_readback.value.enabled", workflow
        )
        self.assertIn("aws ssm send-command", workflow)
        self.assertIn(
            "curl -fsS http://127.0.0.1:8545/health",
            workflow,
        )
        self.assertIn(
            '"file:/var/lib/junca/state.sqlite?mode=ro"',
            workflow,
        )
        self.assertIn(
            'connection.execute("PRAGMA query_only=ON")',
            workflow,
        )
        self.assertIn(
            'connection.execute("PRAGMA quick_check")',
            workflow,
        )
        self.assertIn(
            "FROM finality_certificates",
            workflow,
        )
        self.assertIn(
            "durable_state: $readback[0].durable_state",
            workflow,
        )
        self.assertNotIn(
            "sqlite3.connect(\"/var/lib/junca/state.sqlite\"",
            workflow,
        )
        self.assertIn("--private-validator-health", workflow)
        self.assertIn("test \"$(find evidence/release -type f | wc -l)\" = 3", workflow)
        self.assertIn("path: evidence/release/", workflow)

    def test_workflow_durable_reader_emits_health_head_and_certificate(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(
            r"base64 -w0 <<'PY'\n(?P<script>.*?)\n          PY",
            workflow,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        script = textwrap.dedent(match.group("script"))
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "state.sqlite"
            connection = sqlite3.connect(state_path)
            connection.executescript(
                """
                CREATE TABLE blocks(
                  height INTEGER PRIMARY KEY,
                  block_hash TEXT,
                  finalized INTEGER,
                  certificate_hash TEXT
                );
                CREATE TABLE finality_certificates(
                  height INTEGER PRIMARY KEY,
                  certificate_json TEXT NOT NULL
                );
                """
            )
            certificate = finality_certificate()
            connection.execute(
                "INSERT INTO blocks VALUES(?,?,?,?)",
                (
                    FINALIZED_HEIGHT,
                    FINALIZED_HASH,
                    1,
                    certificate["certificate_hash"],
                ),
            )
            connection.execute(
                "INSERT INTO finality_certificates VALUES(?,?)",
                (
                    FINALIZED_HEIGHT,
                    json.dumps(certificate),
                ),
            )
            connection.commit()
            connection.close()
            script = script.replace(
                "/var/lib/junca/state.sqlite",
                str(state_path),
            )
            environment = dict(os.environ)
            environment["JUNCA_HEALTH_JSON"] = json.dumps(
                {"status": "healthy"}
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
        readback = json.loads(result.stdout)
        self.assertEqual(readback["health"], {"status": "healthy"})
        self.assertEqual(
            readback["durable_state"]["head"],
            {
                "height": FINALIZED_HEIGHT,
                "block_hash": FINALIZED_HASH,
                "finalized": 1,
                "certificate_hash": certificate["certificate_hash"],
            },
        )
        self.assertEqual(
            readback["durable_state"]["certificate"],
            certificate,
        )
        self.assertEqual(
            readback["durable_state"]["quick_check"],
            "ok",
        )


if __name__ == "__main__":
    unittest.main()
