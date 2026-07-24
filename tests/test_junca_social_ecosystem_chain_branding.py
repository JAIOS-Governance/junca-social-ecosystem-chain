from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jaios.social_ecosystem_chain import (
    BRAND_HIERARCHY,
    OFFICIAL_NAME,
    ChainBrandError,
    load_brand_contract,
)


BRAND_PATH = Path("config/junca_social_ecosystem_chain_brand.json")


class JuncaSocialEcosystemChainBrandingTests(unittest.TestCase):
    def test_canonical_brand_contract(self) -> None:
        brand = load_brand_contract(BRAND_PATH)

        self.assertEqual(brand.official_name, OFFICIAL_NAME)
        self.assertEqual(brand.brand_hierarchy, BRAND_HIERARCHY)
        self.assertEqual(brand.short_reference, "JUNCA Chain")
        self.assertEqual(brand.as_evidence()["brand_status"], "canonical")

    def test_former_name_is_legacy_reference_only(self) -> None:
        brand = load_brand_contract(BRAND_PATH)

        self.assertEqual(brand.former_public_name, "JUNCA Global Chain")
        self.assertEqual(
            brand.former_name_usage,
            "legacy-history-and-migration-reference-only",
        )

    def test_superordinate_hierarchy_cannot_be_collapsed(self) -> None:
        raw = json.loads(BRAND_PATH.read_text(encoding="utf-8"))
        raw["brand_hierarchy"] = [
            "JUNCA Social Ecosystem Chain",
            "JUNCA Intelligence Ecosystem",
        ]

        with self.assertRaisesRegex(ChainBrandError, "brand_hierarchy"):
            self._load(raw)

    def test_unapproved_primary_name_is_rejected(self) -> None:
        raw = json.loads(BRAND_PATH.read_text(encoding="utf-8"))
        raw["official_name"] = "JUNCA Global Chain"

        with self.assertRaisesRegex(ChainBrandError, "official_name"):
            self._load(raw)

    @staticmethod
    def _load(raw: dict[str, object]):
        with TemporaryDirectory() as directory:
            path = Path(directory, "brand.json")
            path.write_text(json.dumps(raw), encoding="utf-8")
            return load_brand_contract(path)


if __name__ == "__main__":
    unittest.main()
