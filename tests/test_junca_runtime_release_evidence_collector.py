from __future__ import annotations

import importlib.util
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
    state_volumes = [
        {
            "validator_id": f"validator-0{index}",
            "volume_id": volume_ids[index - 1],
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
                    }
                ]
            }
            for instance_id in instance_ids
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
            for snapshot_id in snapshot_ids
        ]
    }
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
    return {
        "candidate": candidate,
        "bootstrap": bootstrap,
        "public": public,
        "images": images,
        "instances": instances,
        "volumes": volumes,
        "snapshots": snapshots,
        "endpoints": endpoints,
    }


class EvidenceCollectorTests(unittest.TestCase):
    def collect(self, values):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "release"
        paths = collector.collect(
            **values,
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
        self.assertEqual(manifest["previous_runtime"]["ami_id"], CURRENT_AMI)
        self.assertEqual(explorer["observed_runtime"]["ami_id"], CURRENT_AMI)

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
            "aws ssm send-command",
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
        self.assertIn("test \"$(find evidence/release -type f | wc -l)\" = 3", workflow)
        self.assertIn("path: evidence/release/", workflow)


if __name__ == "__main__":
    unittest.main()
