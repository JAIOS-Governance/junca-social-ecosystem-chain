from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import LegacyFingerprintError, fingerprint_legacy_source
from jaios.social_ecosystem_chain.legacy import LEGACY_FILES


COMMIT = "a3e47b6a96c36378606764c35cfcdb2de97cb685"


class JuncaSocialEcosystemChainLegacyFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic_and_redacted(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._source_tree(Path(directory))

            first = fingerprint_legacy_source(
                root,
                source_repository="https://github.com/juncachain/juncachain",
                source_commit=COMMIT,
                source_tag="v0.2.8",
            ).as_evidence()
            second = fingerprint_legacy_source(
                root,
                source_repository="https://github.com/juncachain/juncachain",
                source_commit=COMMIT,
                source_tag="v0.2.8",
            ).as_evidence()

        self.assertEqual(first, second)
        self.assertEqual(first["classification"], "audit-reference-only")
        self.assertEqual(first["genesis"][0]["chain_id"], 668)
        self.assertEqual(first["genesis"][1]["chain_id"], 669)
        self.assertFalse(first["custody"]["legacy_keys_accepted"])
        self.assertNotIn("private_key", json.dumps(first))

    def test_wrong_legacy_chain_id_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._source_tree(Path(directory))
            path = root / "genesis/mainnet.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["config"]["chainId"] = 669
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(LegacyFingerprintError, "mainnet chain ID"):
                fingerprint_legacy_source(
                    root,
                    source_repository="https://github.com/juncachain/juncachain",
                    source_commit=COMMIT,
                    source_tag="v0.2.8",
                )

    def test_symlinked_audit_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._source_tree(Path(directory))
            target = root / "outside"
            target.write_text("replacement", encoding="utf-8")
            dockerfile = root / "Dockerfile"
            dockerfile.unlink()
            dockerfile.symlink_to(target)

            with self.assertRaisesRegex(LegacyFingerprintError, "symlink"):
                fingerprint_legacy_source(
                    root,
                    source_repository="https://github.com/juncachain/juncachain",
                    source_commit=COMMIT,
                    source_tag="v0.2.8",
                )

    @staticmethod
    def _source_tree(root: Path) -> Path:
        for relative in LEGACY_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.startswith("genesis/"):
                chain_id = 668 if "mainnet" in relative else 669
                path.write_text(
                    json.dumps(
                        {
                            "config": {
                                "chainId": chain_id,
                                "posv": {
                                    "period": 2,
                                    "epoch": 900,
                                    "minStaked": "0x00",
                                    "reward": "0x00",
                                    "totalReward": "0x00",
                                    "foundation": "0x" + ("1" * 40),
                                    "juncaswapAdmin": "0x" + ("2" * 40),
                                },
                            },
                            "timestamp": "0x01",
                            "extraData": "0x00",
                            "gasLimit": "0x01",
                            "difficulty": "0x01",
                            "alloc": {},
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                path.write_text(f"fixture:{relative}\n", encoding="utf-8")
        return root


if __name__ == "__main__":
    unittest.main()
