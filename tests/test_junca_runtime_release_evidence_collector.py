from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
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
                        "JuncaFinalityCertificateRecovered": "true",
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
    }


def private_health(values):
    instance_ids = values["public"]["validator_instance_ids"]["value"]
    signer_arns = values["bootstrap"]["validator_signer_arns"]["value"]
    head_hash = "0x" + "1" * 64
    certificate_hash = "0x" + "2" * 64
    certificate = {
        "finality_status": "FINALIZED",
        "height": 100,
        "block_hash": head_hash,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": [
            "validator-01",
            "validator-02",
            "validator-03",
        ],
    }
    validators = []
    for index, (instance_id, signer_arn) in enumerate(
        zip(instance_ids, signer_arns, strict=True), start=1
    ):
        validator_id = f"validator-0{index}"
        validators.append(
            {
                "validator_id": validator_id,
                "instance_id": instance_id,
                "health": {
                    "status": "healthy",
                    "network": "Public Testnet / No Monetary Value",
                    "chain_id": 8453,
                    "validator_id": validator_id,
                    "head_height": 100,
                    "head_hash": head_hash,
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
                        "chain_id": 8453,
                        "head_height": 100,
                        "required_vote_count": 3,
                        "last_certificate_hash": certificate_hash,
                        "last_certificate": dict(certificate),
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
            collector.EvidenceError, "certificate:invalid"
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
        self.assertIn("--private-validator-health", workflow)
        self.assertIn("test \"$(find evidence/release -type f | wc -l)\" = 3", workflow)
        self.assertIn("path: evidence/release/", workflow)


if __name__ == "__main__":
    unittest.main()
