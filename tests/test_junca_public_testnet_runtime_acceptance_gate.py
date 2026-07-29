from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "junca_public_testnet_runtime_acceptance_gate.py"
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "junca-public-testnet-runtime-acceptance-gate.yml"
)
SPEC = importlib.util.spec_from_file_location("runtime_acceptance_gate", SCRIPT)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

BOUNDARY = {
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
CANDIDATE = {
    "source_commit": "a" * 40,
    "node_artifact_sha256": "b" * 64,
    "genesis_sha256": "c" * 64,
    "ami_id": "ami-0123456789abcdef0",
    "request_sha256": "d" * 64,
}


def evidence():
    soak = {
        "schema_version": "junca-public-testnet-live-soak/v1",
        "status": "PASS",
        "accepted": True,
        "duration_seconds": 86_400,
        "segments_completed": 6,
        "continuous_observation": True,
        "head_advanced": True,
        "candidate_binding": dict(CANDIDATE),
        "provenance": {
            "foundation_run_id": "123",
            "public_release_run_id": "456",
            "final_runtime_readback_sha256": "e" * 64,
        },
        "release_boundary": dict(BOUNDARY),
    }
    final_readback = {
        "schema_version": "junca-public-testnet-final-runtime-readback/v1",
        "status": "PASS",
        "candidate_binding": dict(CANDIDATE),
        "instance_ids": ["i-1", "i-2", "i-3"],
        **BOUNDARY,
    }
    foundation_outputs = {
        "approved_node_ami_readback": {
            "value": {
                "id": CANDIDATE["ami_id"],
                "source_commit": CANDIDATE["source_commit"],
                "node_sha256": CANDIDATE["node_artifact_sha256"],
                "genesis_sha256": CANDIDATE["genesis_sha256"],
            }
        }
    }
    foundation_acceptance = {
        "schema_version": "junca-public-testnet-runtime-acceptance/v1",
        "result": "PASS",
        "observations": {"head_advanced": True},
    }
    publication = {
        "schema_version": "junca-public-testnet-publication/v1",
        "result": "PASS",
        "candidate_binding": dict(CANDIDATE),
        "foundation_run_id": "123",
        **BOUNDARY,
    }
    return (
        soak,
        final_readback,
        foundation_outputs,
        foundation_acceptance,
        publication,
    )


class RuntimeAcceptanceGateTests(unittest.TestCase):
    def test_exact_request_bound_candidate_passes(self):
        decision = gate.evaluate(
            *evidence(),
            final_readback_sha256="e" * 64,
        )
        self.assertTrue(decision["accepted"], decision["failures"])

    def test_missing_request_digest_fails_closed(self):
        values = list(evidence())
        values[0]["candidate_binding"].pop("request_sha256")
        decision = gate.evaluate(
            *values,
            final_readback_sha256="e" * 64,
        )
        self.assertFalse(decision["accepted"])
        self.assertIn(
            "soak.candidate_binding.request_sha256:invalid",
            decision["failures"],
        )

    def test_workflow_hardcodes_producer_paths_events_and_artifacts(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for value in (
            ".github/workflows/junca-public-testnet-live-soak.yml",
            ".github/workflows/junca-validator-foundation-release.yml",
            ".github/workflows/junca-public-testnet-release.yml",
            "junca-public-testnet-live-soak-${soak_run_id}",
            "junca-validator-foundation-release-${foundation_run_id}",
            "junca-public-testnet-release-${public_release_run_id}",
            "workflow_dispatch",
            "workflow_run",
            ".candidate_binding.source_commit",
            '.head_branch == ("release-candidate/" + $source_commit)',
            ".head_sha == $source_commit",
            '.event == "workflow_dispatch"',
        ):
            self.assertIn(value, workflow)
        job_prefix = workflow.split("  accept:", 1)[1].split(
            "    runs-on:", 1
        )[0]
        self.assertNotIn("if:", job_prefix)
        self.assertIn("Authorize exact acceptance trigger", workflow)
        self.assertIn(
            'test "$GITHUB_REF" = "refs/heads/main"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
