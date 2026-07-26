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
OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
OPERATOR_NAME = "JAIOS Institutional Governance"
LEGACY_NAME = "JUNCA Global Chain"
EXPECTED_TITLE = f"{OFFICIAL_NAME} | {OPERATOR_NAME}"
EXPECTED_SOCIAL_IMAGE = f"{BRAND_ORIGIN}/icon-512.png"
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


class PublicSurfaceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonical_urls: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.json_ld: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = values.get("property") or values.get("name")
            if key:
                self.meta[key.lower()] = values.get("content", "").strip()
        elif tag == "link":
            rel_tokens = values.get("rel", "").lower().split()
            if "canonical" in rel_tokens and values.get("href"):
                self.canonical_urls.append(values["href"])
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif (
            tag == "script"
            and values.get("type", "").lower() == "application/ld+json"
        ):
            self._in_json_ld = True
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._json_ld_parts).strip())
            self._in_json_ld = False
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_json_ld:
            self._json_ld_parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()


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


def _public_surface(html: str) -> PublicSurfaceParser:
    parser = PublicSurfaceParser()
    parser.feed(html)
    return parser


def _json_ld_values(value: object) -> list[object]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_json_ld_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_json_ld_values(child))
    return values


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

    surface = _public_surface(root.body) if root.status == 200 else PublicSurfaceParser()
    canonical_urls = surface.canonical_urls
    record(
        "brand_root_canonical",
        canonical_urls == [root_url],
        f"observed={canonical_urls!r}",
    )
    record(
        "brand_identity_title",
        surface.title == EXPECTED_TITLE,
        f"observed={surface.title!r}",
    )

    robots_tokens = {
        token.strip().lower()
        for token in surface.meta.get("robots", "").split(",")
        if token.strip()
    }
    record(
        "brand_meta_robots",
        {"index", "follow"}.issubset(robots_tokens)
        and "noindex" not in robots_tokens
        and "nofollow" not in robots_tokens,
        f"observed={sorted(robots_tokens)!r}",
    )
    record(
        "brand_meta_description",
        OFFICIAL_NAME.lower() in surface.meta.get("description", "").lower()
        and "public testnet" in surface.meta.get("description", "").lower(),
        f"observed={surface.meta.get('description', '')!r}",
    )

    social_expectations = {
        "og:title": OFFICIAL_NAME,
        "og:url": BRAND_ORIGIN,
        "og:image": EXPECTED_SOCIAL_IMAGE,
        "twitter:card": "summary_large_image",
        "twitter:title": OFFICIAL_NAME,
        "twitter:image": EXPECTED_SOCIAL_IMAGE,
    }
    social_mismatches = {
        key: surface.meta.get(key, "")
        for key, expected in social_expectations.items()
        if surface.meta.get(key, "").rstrip("/") != expected.rstrip("/")
    }
    social_boundary = "public testnet / no monetary value"
    social_descriptions = (
        surface.meta.get("og:description", ""),
        surface.meta.get("twitter:description", ""),
    )
    record(
        "brand_social_metadata",
        not social_mismatches
        and all(
            social_boundary in description.lower()
            for description in social_descriptions
        ),
        f"mismatches={social_mismatches!r}",
    )

    social_image = fetcher(EXPECTED_SOCIAL_IMAGE)
    record(
        "brand_social_image_http",
        social_image.status == 200
        and social_image.content_type.lower().startswith("image/"),
        f"HTTP {social_image.status}; content-type={social_image.content_type!r}",
    )

    json_ld_documents: list[object] = []
    json_ld_errors: list[str] = []
    for raw_document in surface.json_ld:
        try:
            json_ld_documents.append(json.loads(raw_document))
        except json.JSONDecodeError as error:
            json_ld_errors.append(str(error))
    json_ld_flat = [
        item
        for document in json_ld_documents
        for item in _json_ld_values(document)
    ]
    record(
        "brand_json_ld_identity",
        not json_ld_errors
        and OFFICIAL_NAME in json_ld_flat
        and OPERATOR_NAME in json_ld_flat
        and any(
            isinstance(item, str)
            and item.rstrip("/") == BRAND_ORIGIN
            for item in json_ld_flat
        ),
        f"documents={len(json_ld_documents)}; errors={json_ld_errors!r}",
    )
    record(
        "brand_docs_link",
        any(
            href.rstrip("/") == DOCS_ORIGIN
            or href.startswith(f"{DOCS_ORIGIN}/")
            for href in surface.links
        ),
        f"docs links={sum(DOCS_ORIGIN in href for href in surface.links)}",
    )
    record(
        "brand_legacy_name_absent",
        LEGACY_NAME.lower() not in root.body.lower(),
        f"prohibited current-name occurrence={root.body.lower().count(LEGACY_NAME.lower())}",
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
