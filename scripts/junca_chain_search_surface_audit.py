#!/usr/bin/env python3
"""Audit the JUNCA Chain public search surface without changing production."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree


BRAND_ORIGIN = "https://chain.jaios-governance.org"
DOCS_ORIGIN = "https://docs.jaios-governance.org"
BRAND_ROUTES = (
    "/",
    "/context",
    "/foundation",
    "/build",
    "/possibilities",
    "/ecosystem",
    "/experience",
    "/governance",
    "/evidence",
    "/contact",
)


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content_type: str
    body: str


class CanonicalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonical_urls: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        rel_tokens = values.get("rel", "").lower().split()
        if "canonical" in rel_tokens and values.get("href"):
            self.canonical_urls.append(values["href"])


def fetch_url(url: str) -> Response:
    request = Request(
        url,
        headers={
            "User-Agent": "JAIOS-Search-Surface-Audit/1.0",
            "Accept": "text/html,application/xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=30) as result:
            return Response(
                url=result.geturl(),
                status=result.status,
                content_type=result.headers.get("Content-Type", ""),
                body=result.read().decode("utf-8", errors="replace"),
            )
    except HTTPError as error:
        return Response(
            url=error.geturl(),
            status=error.code,
            content_type=error.headers.get("Content-Type", ""),
            body=error.read().decode("utf-8", errors="replace"),
        )
    except URLError as error:
        return Response(
            url=url,
            status=0,
            content_type="",
            body=f"{type(error.reason).__name__}: {error.reason}",
        )


def _canonical_urls(html: str) -> list[str]:
    parser = CanonicalParser()
    parser.feed(html)
    return parser.canonical_urls


def _sitemap_locations(xml_text: str) -> list[str]:
    root = ElementTree.fromstring(xml_text)
    return [
        element.text.strip()
        for element in root.findall(".//{*}loc")
        if element.text and element.text.strip()
    ]


def audit(
    fetcher: Callable[[str], Response] = fetch_url,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    failures: list[str] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")

    root_url = f"{BRAND_ORIGIN}/"
    root = fetcher(root_url)
    record("brand_root_http", root.status == 200, f"HTTP {root.status}")

    canonical_urls = _canonical_urls(root.body) if root.status == 200 else []
    record(
        "brand_root_canonical",
        canonical_urls == [root_url],
        f"observed={canonical_urls!r}",
    )

    robots_url = f"{BRAND_ORIGIN}/robots.txt"
    robots = fetcher(robots_url)
    record("brand_robots_http", robots.status == 200, f"HTTP {robots.status}")
    robots_lines = {
        line.strip().lower()
        for line in robots.body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    record(
        "brand_robots_allow",
        "user-agent: *" in robots_lines
        and "allow: /" in robots_lines
        and "disallow: /" not in robots_lines,
        "crawler policy must explicitly allow the public site",
    )

    sitemap_url = f"{BRAND_ORIGIN}/sitemap.xml"
    record(
        "brand_robots_sitemap",
        f"sitemap: {sitemap_url}".lower() in robots_lines,
        f"expected Sitemap: {sitemap_url}",
    )

    sitemap = fetcher(sitemap_url)
    record("brand_sitemap_http", sitemap.status == 200, f"HTTP {sitemap.status}")
    try:
        sitemap_locations = _sitemap_locations(sitemap.body)
        sitemap_parse_error = ""
    except ElementTree.ParseError as error:
        sitemap_locations = []
        sitemap_parse_error = str(error)
    record(
        "brand_sitemap_xml",
        not sitemap_parse_error and bool(sitemap_locations),
        sitemap_parse_error or f"{len(sitemap_locations)} URLs",
    )

    expected_locations = [f"{BRAND_ORIGIN}{route}" for route in BRAND_ROUTES]
    record(
        "brand_sitemap_routes",
        sitemap_locations == expected_locations,
        f"observed={sitemap_locations!r}",
    )
    record(
        "brand_sitemap_origin",
        bool(sitemap_locations)
        and all(
            location == BRAND_ORIGIN or location.startswith(f"{BRAND_ORIGIN}/")
            for location in sitemap_locations
        )
        and all(not location.startswith(DOCS_ORIGIN) for location in sitemap_locations),
        "all sitemap URLs must remain on the chain origin",
    )

    route_results: dict[str, int] = {}
    for location in sitemap_locations:
        response = fetcher(location)
        route_results[location] = response.status
    record(
        "brand_sitemap_route_http",
        bool(route_results) and all(status == 200 for status in route_results.values()),
        json.dumps(route_results, sort_keys=True),
    )

    docs_root = fetcher(f"{DOCS_ORIGIN}/")
    docs_sitemap = fetcher(f"{DOCS_ORIGIN}/sitemap.xml")
    record("docs_root_http", docs_root.status == 200, f"HTTP {docs_root.status}")
    record(
        "docs_sitemap_independent",
        docs_sitemap.status == 200 and BRAND_ORIGIN not in docs_sitemap.body,
        f"HTTP {docs_sitemap.status}; chain origin excluded",
    )

    return {
        "operator": "JAIOS Institutional Governance",
        "brand_origin": BRAND_ORIGIN,
        "technical_reference_origin": DOCS_ORIGIN,
        "release_boundary": {
            "network_status": "Public Testnet / No Monetary Value",
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    result = audit()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    output_path = os.environ.get("JAIOS_AUDIT_OUTPUT")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
