#!/usr/bin/env python3
"""Bounded R39 mobile-cache remediation using exact current-source boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "20260807-r39-mobile-cache-recovery"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    snapshot = ROOT / "docs/technical-reference/snapshot"

    release = {
        "schema": "jsec-docs-client-release/v1",
        "delivery_revision": "R39",
        "token": TOKEN,
        "canonical_url": f"https://docs.jaios-governance.org/?release={TOKEN}",
        "required_visible_terms": [
            "Public Testnet",
            "Governed Read-only Operations",
            "Protocol Validation Environment",
        ],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    write(snapshot / "current-release.json", json.dumps(release, indent=2) + "\n")

    manifest_path = snapshot / "manifest.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["id"] = "/"
    manifest["scope"] = "/"
    manifest["start_url"] = f"/?release={TOKEN}"
    manifest["description"] = (
        "Institutional technical reference with governed mobile cache recovery "
        "issued by JAIOS Institutional Governance."
    )
    write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    guard = dedent(
        r'''
        ;(() => {
          const endpoint = "/current-release.json";
          const stale = /RUNTIME\s+DEPLOYMENT\s+IN\s+PROGRESS|NO\s+MONETARY\s+VALUE|\bNO\s+ACTIVE\b|\bNOT\s+ACTIVATED\b|\bNOT\s+YET\s+PUBLISHED\b/i;
          let navigating = false;
          const bodyText = () => document.body?.innerText ?? "";
          const verify = async () => {
            if (navigating) return;
            try {
              const response = await fetch(`${endpoint}?readback=${Date.now()}`, {
                cache: "no-store",
                headers: { Accept: "application/json", "Cache-Control": "no-cache, no-store, max-age=0", Pragma: "no-cache" },
              });
              if (!response.ok) return;
              const current = await response.json();
              const body = bodyText();
              const required = current.required_visible_terms.every((term) => body.includes(term));
              if (!stale.test(body) && required) return;
              const key = `jsec-docs-release-refresh:${current.token}`;
              if (sessionStorage.getItem(key) === "1") return;
              sessionStorage.setItem(key, "1");
              navigating = true;
              const target = new URL(current.canonical_url || "/", location.origin);
              target.searchParams.set("release", current.token);
              target.searchParams.set("refresh", String(Date.now()));
              location.replace(target.toString());
            } catch {
              // Preserve the last rendered page when the release endpoint is unavailable.
            }
          };
          addEventListener("pageshow", verify);
          addEventListener("focus", verify);
          addEventListener("online", verify);
          document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") void verify();
          });
          void verify();
        })();
        '''
    ).lstrip()
    legacy_path = snapshot / "official-brand-lockup-r29.js"
    legacy = legacy_path.read_text(encoding="utf-8")
    if "jsec-docs-release-refresh:" not in legacy:
        legacy = legacy.rstrip() + "\n\n" + guard
    write(legacy_path, legacy)

    build_path = ROOT / "docs/technical-reference/scripts/build.mjs"
    build = build_path.read_text(encoding="utf-8")
    build = replace_once(
        build,
        'await rm(join(dist, "official-brand-lockup-r29.js"));',
        "// R39: retain the legacy R29 script path so stale installed pages self-recover.",
        "legacy script retention",
    )
    write(build_path, build)

    production_path = ROOT / ".github/workflows/junca-chain-docs-production.yml"
    production = production_path.read_text(encoding="utf-8")
    old_immutable = (
        '            --exclude "*.html" \\\n'
        '            --exclude "*.webmanifest" \\\n'
        '            --exclude "robots.txt" \\\n'
        '            --exclude "sitemap.xml" \\\n'
        '            --cache-control "public,max-age=31536000,immutable"'
    )
    new_immutable = (
        '            --exclude "*.html" \\\n'
        '            --exclude "*.webmanifest" \\\n'
        '            --exclude "*.json" \\\n'
        '            --exclude "official-brand-lockup-r29.js" \\\n'
        '            --exclude "robots.txt" \\\n'
        '            --exclude "sitemap.xml" \\\n'
        '            --cache-control "public,max-age=31536000,immutable"'
    )
    production = replace_once(production, old_immutable, new_immutable, "immutable cache block")

    old_dynamic = (
        '            --include "*.html" \\\n'
        '            --include "*.webmanifest" \\\n'
        '            --include "robots.txt" \\\n'
        '            --include "sitemap.xml" \\\n'
        '            --cache-control "public,max-age=0,must-revalidate"'
    )
    new_dynamic = (
        '            --include "*.html" \\\n'
        '            --include "*.webmanifest" \\\n'
        '            --include "*.json" \\\n'
        '            --include "official-brand-lockup-r29.js" \\\n'
        '            --include "robots.txt" \\\n'
        '            --include "sitemap.xml" \\\n'
        '            --cache-control "no-store,no-cache,must-revalidate,max-age=0"'
    )
    production = replace_once(production, old_dynamic, new_dynamic, "dynamic cache block")

    production = replace_once(
        production,
        "for asset in favicon.ico favicon.svg icon-192.png icon-512.png icon-maskable-512.png apple-touch-icon.png manifest.webmanifest official-junca-symbol.png; do",
        "for asset in favicon.ico favicon.svg icon-192.png icon-512.png icon-maskable-512.png apple-touch-icon.png manifest.webmanifest official-junca-symbol.png current-release.json official-brand-lockup-r29.js; do",
        "compatibility asset readback list",
    )
    production = replace_once(
        production,
        "grep -i '^cache-control: public,max-age=0,must-revalidate' <<< \"${manifest_headers}\"",
        "grep -i '^cache-control: .*no-store' <<< \"${manifest_headers}\"",
        "manifest no-store assertion",
    )

    readback = dedent(
        '''\
                  grep -F 'Public Testnet' /tmp/home.html
                  grep -F 'Governed Read-only Operations' /tmp/home.html
                  grep -F 'Protocol Validation Environment' /tmp/home.html
                  ! grep -Fqi 'RUNTIME DEPLOYMENT IN PROGRESS' /tmp/home.html
                  ! grep -Fqi 'NO MONETARY VALUE' /tmp/home.html

                  mobile_url="https://docs.jaios-governance.org/?release=20260807-r39-mobile-cache-recovery"
                  curl --fail --silent --show-error --location --retry 5 --retry-delay 5 \\
                    --user-agent 'Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/151 Mobile Safari/537.36' \\
                    --header 'Cache-Control: no-cache, no-store, max-age=0' \\
                    --output /tmp/mobile-home.html "${mobile_url}"
                  grep -F 'Governed Read-only Operations' /tmp/mobile-home.html
                  grep -F 'Protocol Validation Environment' /tmp/mobile-home.html
                  ! grep -Fqi 'RUNTIME DEPLOYMENT IN PROGRESS' /tmp/mobile-home.html
                  ! grep -Fqi 'NO MONETARY VALUE' /tmp/mobile-home.html

                  root_headers="$(curl --fail --silent --show-error --head https://docs.jaios-governance.org/)"
                  grep -i '^cache-control: .*no-store' <<< "${root_headers}"
                  release_headers="$(curl --fail --silent --show-error --head https://docs.jaios-governance.org/current-release.json)"
                  grep -i '^cache-control: .*no-store' <<< "${release_headers}"
                  curl --fail --silent --show-error --location --output /tmp/current-release.json \\
                    https://docs.jaios-governance.org/current-release.json
                  jq -e '.delivery_revision == "R39" and .token == "20260807-r39-mobile-cache-recovery"' \\
                    /tmp/current-release.json >/dev/null
                  curl --fail --silent --show-error --location --output /tmp/legacy-r29.js \\
                    'https://docs.jaios-governance.org/official-brand-lockup-r29.js?v=20260727-r29'
                  grep -F 'jsec-docs-release-refresh:' /tmp/legacy-r29.js
        '''
    )
    production = replace_once(
        production,
        "          grep -F 'Public Testnet' /tmp/home.html\n",
        readback,
        "mobile production readback insertion",
    )
    write(production_path, production)

    write(
        ROOT / "docs/technical-reference/MOBILE_CACHE_RECOVERY_R39.md",
        dedent(
            f'''\
            # JSEC Docs Mobile Cache Recovery R39

            - Public HTML, Web App Manifest and current-state JSON use `no-store` delivery.
            - Installed-app launch is release-bound to `{TOKEN}`.
            - The historical `official-brand-lockup-r29.js` path is retained as a compatibility refresh controller.
            - Stale installed pages redirect to the canonical current release.
            - Mainnet Changed: false
            - Assets Moved: false
            - Bridge Activated: false
            '''
        ),
    )

    for path in (
        ROOT / ".github/workflows/jsec-docs-mobile-cache-r39-remediation.yml",
        ROOT / "scripts/ops/jsec_docs_mobile_cache_r39_remediation.py",
        ROOT / "scripts/ops/jsec_docs_mobile_cache_r39_remediation_v2.py",
    ):
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()
