import importlib.util
import json
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "marketing" / "search-surface-production-handoff"
AUDIT_PATH = ROOT / "scripts" / "junca_chain_search_surface_audit.py"
SPEC = importlib.util.spec_from_file_location("search_surface_audit_handoff", AUDIT_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class SearchSurfaceProductionHandoffTest(unittest.TestCase):
    def test_robots_allows_crawling_and_points_to_canonical_sitemap(self) -> None:
        robots = (HANDOFF / "robots.txt").read_text(encoding="utf-8")
        lines = {
            line.strip().lower()
            for line in robots.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("user-agent: *", lines)
        self.assertIn("allow: /", lines)
        self.assertNotIn("disallow: /", lines)
        self.assertIn(
            f"sitemap: {AUDIT.BRAND_ORIGIN}/sitemap.xml".lower(),
            lines,
        )

    def test_sitemap_matches_the_verified_brand_route_inventory(self) -> None:
        root = ElementTree.parse(HANDOFF / "sitemap.xml").getroot()
        locations = [
            element.text.strip()
            for element in root.findall(".//{*}loc")
            if element.text and element.text.strip()
        ]
        expected = [f"{AUDIT.BRAND_ORIGIN}{route}" for route in AUDIT.BRAND_ROUTES]
        self.assertEqual(locations, expected)
        self.assertEqual(len(locations), len(set(locations)))
        self.assertFalse(any(AUDIT.DOCS_ORIGIN in url for url in locations))

    def test_json_ld_has_canonical_identity_and_operator(self) -> None:
        document = json.loads((HANDOFF / "website.jsonld").read_text(encoding="utf-8"))
        self.assertEqual(document["@context"], "https://schema.org")
        self.assertEqual(document["@type"], "WebSite")
        self.assertEqual(document["name"], AUDIT.OFFICIAL_NAME)
        self.assertEqual(document["url"], f"{AUDIT.BRAND_ORIGIN}/")
        self.assertEqual(document["publisher"]["name"], AUDIT.OPERATOR_NAME)
        self.assertEqual(document["publisher"]["url"], f"{AUDIT.BRAND_ORIGIN}/")
        self.assertEqual(
            document["accountablePerson"]["name"],
            AUDIT.OPERATOR_NAME,
        )
        serialized = json.dumps(document, ensure_ascii=False)
        self.assertNotIn(AUDIT.LEGACY_NAME, serialized)
        self.assertNotIn(AUDIT.DOCS_ORIGIN, serialized)


if __name__ == "__main__":
    unittest.main()
