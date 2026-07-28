from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jaios.social_ecosystem_chain.mainnet_gap_matrix import (
    MainnetGapMatrixError,
    REQUIRED_DOMAINS,
    load_mainnet_gap_matrix,
)


MATRIX = Path("config/mainnet-development-gap-matrix.json")


class MainnetGapMatrixTests(unittest.TestCase):
    def test_canonical_matrix_contains_every_domain(self) -> None:
        matrix = load_mainnet_gap_matrix(MATRIX)

        self.assertEqual(
            tuple(item.domain for item in matrix.entries),
            REQUIRED_DOMAINS,
        )
        self.assertFalse(matrix.completion_allowed)
        self.assertIn("protocol", matrix.active_domains)
        self.assertIn("production-acceptance", matrix.pending_domains)

    def test_evidence_preserves_activation_boundary(self) -> None:
        evidence = load_mainnet_gap_matrix(MATRIX).as_evidence()

        self.assertFalse(evidence["completion_allowed"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])

    def test_missing_domain_fails_closed(self) -> None:
        raw = json.loads(MATRIX.read_text(encoding="utf-8"))
        raw["domains"] = raw["domains"][:-1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(MainnetGapMatrixError, "every required"):
                load_mainnet_gap_matrix(path)

    def test_not_implemented_domain_cannot_claim_evidence(self) -> None:
        raw = json.loads(MATRIX.read_text(encoding="utf-8"))
        raw["domains"][0]["status"] = "NOT_IMPLEMENTED"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(MainnetGapMatrixError, "cannot claim"):
                load_mainnet_gap_matrix(path)


if __name__ == "__main__":
    unittest.main()
