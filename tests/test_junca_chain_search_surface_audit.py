import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "junca_chain_search_surface_audit.py"
)
SPEC = importlib.util.spec_from_file_location("search_surface_audit", SCRIPT_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class SearchSurfaceAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.locations = [
            f"{AUDIT.BRAND_ORIGIN}{route}" for route in AUDIT.BRAND_ROUTES
        ]
        urlset = "".join(f"<url><loc>{url}</loc></url>" for url in self.locations)
        self.responses = {
            f"{AUDIT.BRAND_ORIGIN}/": AUDIT.Response(
                f"{AUDIT.BRAND_ORIGIN}/",
                200,
                "text/html",
                (
                    "<html><head>"
                    f"<title>{AUDIT.EXPECTED_TITLE}</title>"
                    '<meta name="robots" content="index, follow">'
                    f'<meta name="description" content="{AUDIT.OFFICIAL_NAME} public testnet">'
                    f'<meta property="og:title" content="{AUDIT.OFFICIAL_NAME}">'
                    '<meta property="og:description" '
                    'content="Public Testnet / No Monetary Value.">'
                    f'<meta property="og:url" content="{AUDIT.BRAND_ORIGIN}">'
                    f'<meta property="og:image" content="{AUDIT.EXPECTED_SOCIAL_IMAGE}">'
                    '<meta name="twitter:card" content="summary_large_image">'
                    f'<meta name="twitter:title" content="{AUDIT.OFFICIAL_NAME}">'
                    '<meta name="twitter:description" '
                    'content="Public Testnet / No Monetary Value.">'
                    f'<meta name="twitter:image" content="{AUDIT.EXPECTED_SOCIAL_IMAGE}">'
                    '<link rel="canonical" '
                    f'href="{AUDIT.BRAND_ORIGIN}/">'
                    '<script type="application/ld+json">'
                    "{"
                    f'"name":"{AUDIT.OFFICIAL_NAME}",'
                    f'"url":"{AUDIT.BRAND_ORIGIN}/",'
                    f'"publisher":{{"name":"{AUDIT.OPERATOR_NAME}"}}'
                    "}"
                    "</script>"
                    "</head><body>"
                    f'<a href="{AUDIT.DOCS_ORIGIN}/">Technical reference</a>'
                    "</body></html>"
                ),
            ),
            AUDIT.EXPECTED_SOCIAL_IMAGE: AUDIT.Response(
                AUDIT.EXPECTED_SOCIAL_IMAGE,
                200,
                "image/png",
                "",
            ),
            f"{AUDIT.BRAND_ORIGIN}/robots.txt": AUDIT.Response(
                f"{AUDIT.BRAND_ORIGIN}/robots.txt",
                200,
                "text/plain",
                (
                    "User-agent: *\nAllow: /\n"
                    f"Sitemap: {AUDIT.BRAND_ORIGIN}/sitemap.xml\n"
                ),
            ),
            f"{AUDIT.BRAND_ORIGIN}/sitemap.xml": AUDIT.Response(
                f"{AUDIT.BRAND_ORIGIN}/sitemap.xml",
                200,
                "application/xml",
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urlset}</urlset>',
            ),
            f"{AUDIT.DOCS_ORIGIN}/": AUDIT.Response(
                f"{AUDIT.DOCS_ORIGIN}/", 200, "text/html", "<html></html>"
            ),
            f"{AUDIT.DOCS_ORIGIN}/sitemap.xml": AUDIT.Response(
                f"{AUDIT.DOCS_ORIGIN}/sitemap.xml",
                200,
                "application/xml",
                (
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    f"<url><loc>{AUDIT.DOCS_ORIGIN}/</loc></url></urlset>"
                ),
            ),
        }
        for location in self.locations:
            self.responses.setdefault(
                location, AUDIT.Response(location, 200, "text/html", "<html></html>")
            )

    def fetch(self, url: str) -> AUDIT.Response:
        return self.responses[url]

    def test_complete_search_surface_passes(self) -> None:
        result = AUDIT.audit(self.fetch)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])

    def test_missing_brand_robots_fails_closed(self) -> None:
        url = f"{AUDIT.BRAND_ORIGIN}/robots.txt"
        self.responses[url] = AUDIT.Response(url, 404, "text/html", "Not found")

        result = AUDIT.audit(self.fetch)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any("brand_robots_http" in failure for failure in result["failures"])
        )

    def test_cross_origin_sitemap_is_rejected(self) -> None:
        sitemap_url = f"{AUDIT.BRAND_ORIGIN}/sitemap.xml"
        self.responses[sitemap_url] = AUDIT.Response(
            sitemap_url,
            200,
            "application/xml",
            (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{AUDIT.DOCS_ORIGIN}/</loc></url></urlset>"
            ),
        )

        result = AUDIT.audit(self.fetch)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any("brand_sitemap_origin" in failure for failure in result["failures"])
        )

    def test_social_metadata_drift_fails_closed(self) -> None:
        root_url = f"{AUDIT.BRAND_ORIGIN}/"
        root = self.responses[root_url]
        self.responses[root_url] = AUDIT.Response(
            root.url,
            root.status,
            root.content_type,
            root.body.replace(
                'content="summary_large_image"',
                'content="summary"',
            ),
        )

        result = AUDIT.audit(self.fetch)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any("brand_social_metadata" in failure for failure in result["failures"])
        )

    def test_legacy_current_name_fails_closed(self) -> None:
        root_url = f"{AUDIT.BRAND_ORIGIN}/"
        root = self.responses[root_url]
        self.responses[root_url] = AUDIT.Response(
            root.url,
            root.status,
            root.content_type,
            root.body.replace(
                "</body>",
                f"<p>{AUDIT.LEGACY_NAME}</p></body>",
            ),
        )

        result = AUDIT.audit(self.fetch)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(
            any("brand_legacy_name_absent" in failure for failure in result["failures"])
        )


if __name__ == "__main__":
    unittest.main()
