from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "aws_binding_readback.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aws_binding_readback", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    returncode = 0
    stderr = ""

    def __init__(self, payload: dict):
        self.stdout = json.dumps(payload)


def aws_response(command: list[str], **_: object) -> Result:
    service, action = command[1], command[2]
    if (service, action) == ("sts", "get-caller-identity"):
        return Result({"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/junca-public-testnet/github"})
    if (service, action) == ("organizations", "describe-organization"):
        return Result({"Organization": {"Id": "o-example"}})
    if (service, action) == ("ec2", "describe-availability-zones"):
        return Result({"AvailabilityZones": [
            {"ZoneName": "ap-northeast-1a", "State": "available"},
            {"ZoneName": "ap-northeast-1c", "State": "available"},
            {"ZoneName": "ap-northeast-1d", "State": "available"},
        ]})
    if (service, action) == ("route53", "list-hosted-zones-by-name"):
        return Result({"HostedZones": [{"Id": "/hostedzone/ZCANONICAL", "Name": "jaios-governance.org.", "Config": {"PrivateZone": False}}]})
    if (service, action) == ("route53", "get-hosted-zone"):
        return Result({"DelegationSet": {"NameServers": ["ns-4.example.net", "ns-1.example.org"]}})
    if (service, action) == ("iam", "get-role"):
        return Result({"Role": {"Arn": "arn:aws:iam::123456789012:role/junca-public-testnet"}})
    if (service, action) == ("kms", "describe-key"):
        key_id = command[command.index("--key-id") + 1].rsplit("/", 1)[-1]
        return Result({"KeyMetadata": {"KeyId": key_id, "Enabled": True, "KeyState": "Enabled", "KeyManager": "CUSTOMER", "Origin": "AWS_KMS"}})
    raise AssertionError(f"Unexpected AWS command: {command}")


class AwsBindingReadbackTest(unittest.TestCase):
    def test_generates_redacted_verified_evidence(self) -> None:
        module = load_module()
        role = "arn:aws:iam::123456789012:role/junca-public-testnet"
        signers = [f"arn:aws:kms:ap-northeast-1:123456789012:key/signer-{i}" for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            argv = ["aws_binding_readback.py", "--deployment-role-arn", role, "--output", str(output)]
            for signer in signers:
                argv.extend(["--signer-arn", signer])
            with patch.object(sys, "argv", argv), patch.object(module.subprocess, "run", side_effect=aws_response):
                self.assertEqual(module.main(), 0)

            evidence = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(evidence["status"], "AWS_BINDING_READBACK_VERIFIED")
            self.assertEqual(evidence["governance"], "JAIOS Institutional Governance")
            self.assertEqual(evidence["network_label"], "Public Testnet / No Monetary Value")
            self.assertEqual(len(evidence["aws"]["failure_domains"]), 3)
            self.assertEqual(len(evidence["validator_signers"]), 3)
            self.assertFalse(evidence["release_boundary"]["mainnet_changed"])
            self.assertFalse(evidence["release_boundary"]["assets_moved"])
            self.assertFalse(evidence["release_boundary"]["bridge_activated"])
            self.assertFalse(evidence["secrets_included"])
            self.assertNotIn("secret", output.read_text(encoding="utf-8").lower())
            self.assertTrue(Path(f"{output}.sha256").exists())

    def test_fails_closed_without_three_failure_domains(self) -> None:
        module = load_module()

        def insufficient_zones(command: list[str], **kwargs: object) -> Result:
            if command[1:3] == ["ec2", "describe-availability-zones"]:
                return Result({"AvailabilityZones": [{"ZoneName": "ap-northeast-1a", "State": "available"}]})
            return aws_response(command, **kwargs)

        with patch.object(sys, "argv", ["aws_binding_readback.py"]), patch.object(module.subprocess, "run", side_effect=insufficient_zones):
            with self.assertRaisesRegex(RuntimeError, "Fewer than three"):
                module.main()

    def test_fails_closed_for_duplicate_signers(self) -> None:
        module = load_module()
        role = "arn:aws:iam::123456789012:role/junca-public-testnet"
        signer = "arn:aws:kms:ap-northeast-1:123456789012:key/duplicate"
        argv = ["aws_binding_readback.py", "--deployment-role-arn", role]
        for _ in range(3):
            argv.extend(["--signer-arn", signer])
        with patch.object(sys, "argv", argv), patch.object(module.subprocess, "run", side_effect=aws_response):
            with self.assertRaisesRegex(RuntimeError, "three distinct signer"):
                module.main()


if __name__ == "__main__":
    unittest.main()
