from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_jsec_native_token_genesis import CONFIG, ready_plan


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jsec_native_genesis_candidate_pipeline.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NativeGenesisCandidatePipelineTests(unittest.TestCase):
    def run_pipeline(
        self,
        plan: Path,
        output_dir: Path,
        expected_state: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "--plan",
                str(plan),
                "--output-dir",
                str(output_dir),
                "--expect-state",
                expected_state,
            ),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_canonical_unapproved_plan_emits_only_blocked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "pipeline"
            candidate = output_dir / "native-genesis-candidate.json"
            verification = output_dir / "native-genesis-candidate-verification.json"
            output_dir.mkdir(parents=True)
            candidate.write_text("stale\n", encoding="utf-8")
            verification.write_text("stale\n", encoding="utf-8")

            result = self.run_pipeline(CONFIG, output_dir, "BLOCKED")

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "pipeline-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["state"], "BLOCKED")
            self.assertIn("native-token-definition", manifest["blockers"])
            self.assertIsNone(manifest["candidate"])
            self.assertIsNone(manifest["verification"])
            self.assertFalse(candidate.exists())
            self.assertFalse(verification.exists())
            self.assertFalse(manifest["safety"]["mainnet_changed"])
            self.assertFalse(manifest["safety"]["assets_moved"])
            self.assertFalse(manifest["safety"]["bridge_activated"])

    def test_ready_plan_compiles_verifies_and_seals_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "approved-plan.json"
            output_dir = root / "pipeline"
            plan_path.write_text(
                json.dumps(ready_plan(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = self.run_pipeline(
                plan_path,
                output_dir,
                "VERIFIED_NON_ACTIVATED_CANDIDATE",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            candidate_path = output_dir / "native-genesis-candidate.json"
            verification_path = (
                output_dir / "native-genesis-candidate-verification.json"
            )
            manifest = json.loads(
                (output_dir / "pipeline-manifest.json").read_text(encoding="utf-8")
            )
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["state"], "VERIFIED_NON_ACTIVATED_CANDIDATE"
            )
            self.assertEqual(manifest["blockers"], [])
            self.assertEqual(manifest["candidate"]["file_sha256"], sha256(candidate_path))
            self.assertEqual(
                manifest["verification"]["file_sha256"], sha256(verification_path)
            )
            self.assertEqual(
                manifest["candidate"]["canonical_sha256"],
                verification["candidate_sha256"],
            )
            self.assertTrue(manifest["verification"]["source_plan_bound"])
            self.assertFalse(manifest["safety"]["genesis_applied"])
            self.assertFalse(manifest["safety"]["mainnet_activation_authorized"])

    def test_expected_state_mismatch_fails_after_evidence_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "pipeline"
            result = self.run_pipeline(
                CONFIG,
                output_dir,
                "VERIFIED_NON_ACTIVATED_CANDIDATE",
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("state mismatch", result.stderr)
            manifest = json.loads(
                (output_dir / "pipeline-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["state"], "BLOCKED")

    def test_invalid_plan_clears_stale_artifacts_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "invalid-plan.json"
            output_dir = root / "pipeline"
            plan_path.write_text("{not-json}\n", encoding="utf-8")
            output_dir.mkdir(parents=True)
            stale_paths = (
                output_dir / "pipeline-manifest.json",
                output_dir / "native-genesis-candidate.json",
                output_dir / "native-genesis-candidate-verification.json",
            )
            for path in stale_paths:
                path.write_text("stale\n", encoding="utf-8")

            result = self.run_pipeline(plan_path, output_dir, "BLOCKED")

            self.assertEqual(result.returncode, 2)
            self.assertIn("pipeline failed", result.stderr)
            for path in stale_paths:
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
