#!/usr/bin/env python3
"""One-time bounded remediation for stale installed JSEC Docs pages."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "20260807-r39-mobile-cache-recovery"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    current_release = {
        "schema": "jsec-docs-client-release/v1",
        "delivery_revision": "R39",
        "token": TOKEN,
        "canonical_url": f"https://docs.jaios-governance.org/?release={TOKEN}",
        "required_visible_terms": [
            "Public Testnet",
            "Governed Read-only Operations",
            "Protocol Validation Environment",
        ],
        "stale_visible_terms": [
            "Runtime Deployment in Progress",
            "No Monetary Value",
            "No Active",
            "Not Activated",
            "Not Yet Published",
        ],
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    write(
        ROOT / "docs/technical-reference/snapshot/current-release.json",
        json.dumps(current_release, indent=2, ensure_ascii=False) + "\n",
    )

    guard = dedent(
        r'''
        ;(() => {
          const releaseEndpoint = "/current-release.json";
          const stalePattern = /RUNTIME\s+DEPLOYMENT\s+IN\s+PROGRESS|NO\s+MONETARY\s+VALUE|\bNO\s+ACTIVE\b|\bNOT\s+ACTIVATED\b|\bNOT\s+YET\s+PUBLISHED\b/i;
          let navigating = false;

          const visibleText = () => document.body?.innerText ?? "";
          const verifyRelease = async () => {
            if (navigating) return;
            try {
              const response = await fetch(`${releaseEndpoint}?readback=${Date.now()}`, {
                cache: "no-store",
                headers: {
                  Accept: "application/json",
                  "Cache-Control": "no-cache, no-store, max-age=0",
                  Pragma: "no-cache",
                },
              });
              if (!response.ok) return;
              const current = await response.json();
              const body = visibleText();
              const stale = stalePattern.test(body);
              const required = Array.isArray(current.required_visible_terms)
                ? current.required_visible_terms.every((term) => body.includes(term))
                : true;
              if (!stale && required) return;

              const sessionKey = `jsec-docs-release-refresh:${current.token}`;
              if (window.sessionStorage.getItem(sessionKey) === "1") return;
              window.sessionStorage.setItem(sessionKey, "1");
              navigating = true;
              const target = new URL(current.canonical_url || "/", window.location.origin);
              target.searchParams.set("release", current.token);
              target.searchParams.set("refresh", String(Date.now()));
              window.location.replace(target.toString());
            } catch {
              // Keep the last rendered page if the release control endpoint is unavailable.
            }
          };

          window.addEventListener("pageshow", verifyRelease);
          window.addEventListener("focus", verifyRelease);
          window.addEventListener("online", verifyRelease);
          document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") void verifyRelease();
          });
          void verifyRelease();
        })();
        '''
    ).lstrip()

    legacy_path = ROOT / "docs/technical-reference/snapshot/official-brand-lockup-r29.js"
    legacy = legacy_path.read_text(encoding="utf-8")
    if "jsec-docs-release-refresh:" not in legacy:
        legacy = legacy.rstrip() + "\n\n" + guard
    write(legacy_path, legacy)

    manifest_path = ROOT / "docs/technical-reference/snapshot/manifest.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "id": "/",
            "scope": "/",
            "start_url": f"/?release={TOKEN}",
            "description": (
                "Institutional technical reference with governed mobile cache "
                "recovery issued by JAIOS Institutional Governance."
            ),
        }
    )
    write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    build_path = ROOT / "docs/technical-reference/scripts/build.mjs"
    build = build_path.read_text(encoding="utf-8")
    build = replace_once(
        build,
        'await rm(join(dist, "official-brand-lockup-r29.js"));',
        "// R39 compatibility: retain the legacy R29 script path so stale installed pages self-recover.",
        "build legacy asset retention",
    )
    write(build_path, build)

    production_path = ROOT / ".github/workflows/junca-chain-docs-production.yml"
    production = production_path.read_text(encoding="utf-8")
    production = replace_once(
        production,
        dedent(
            '''
                        --exclude "*.html" \\
                        --exclude "*.webmanifest" \\
                        --exclude "robots.txt" \\
                        --exclude "sitemap.xml" \\
                        --cache-control "public,max-age=31536000,immutable"'''
        ).strip("\n"),
        dedent(
            '''
                        --exclude "*.html" \\
                        --exclude "*.webmanifest" \\
                        --exclude "*.json" \\
                        --exclude "official-brand-lockup-r29.js" \\
                        --exclude "robots.txt" \\
                        --exclude "sitemap.xml" \\
                        --cache-control "public,max-age=31536000,immutable"'''
        ).strip("\n"),
        "production immutable cache policy",
    )
    production = replace_once(
        production,
        dedent(
            '''
                        --include "*.html" \\
                        --include "*.webmanifest" \\
                        --include "robots.txt" \\
                        --include "sitemap.xml" \\
                        --cache-control "public,max-age=0,must-revalidate"'''
        ).strip("\n"),
        dedent(
            '''
                        --include "*.html" \\
                        --include "*.webmanifest" \\
                        --include "*.json" \\
                        --include "official-brand-lockup-r29.js" \\
                        --include "robots.txt" \\
                        --include "sitemap.xml" \\
                        --cache-control "no-store,no-cache,must-revalidate,max-age=0"'''
        ).strip("\n"),
        "production dynamic cache policy",
    )
    production = replace_once(
        production,
        "for asset in favicon.ico favicon.svg icon-192.png icon-512.png icon-maskable-512.png apple-touch-icon.png manifest.webmanifest official-junca-symbol.png; do",
        "for asset in favicon.ico favicon.svg icon-192.png icon-512.png icon-maskable-512.png apple-touch-icon.png manifest.webmanifest official-junca-symbol.png current-release.json official-brand-lockup-r29.js; do",
        "production compatibility asset readback",
    )
    production = replace_once(
        production,
        "grep -i '^cache-control: public,max-age=0,must-revalidate' <<< \"${manifest_headers}\"",
        "grep -i '^cache-control: .*no-store' <<< \"${manifest_headers}\"",
        "manifest no-store assertion",
    )
    insertion = dedent(
        '''
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
                  curl --fail --silent --show-error --location \\
                    --output /tmp/current-release.json https://docs.jaios-governance.org/current-release.json
                  jq -e '.delivery_revision == "R39" and .token == "20260807-r39-mobile-cache-recovery"' /tmp/current-release.json >/dev/null
                  curl --fail --silent --show-error --location \\
                    --output /tmp/legacy-r29.js 'https://docs.jaios-governance.org/official-brand-lockup-r29.js?v=20260727-r29'
                  grep -F 'jsec-docs-release-refresh:' /tmp/legacy-r29.js
        '''
    ).strip("\n") + "\n"
    production = replace_once(
        production,
        "          grep -F 'Public Testnet' /tmp/home.html\n",
        insertion,
        "mobile and stale-language production readback",
    )
    write(production_path, production)

    readback_path = ROOT / ".github/workflows/docs-status-language-production-readback.yml"
    readback = readback_path.read_text(encoding="utf-8")
    readback = replace_once(
        readback,
        "              'No Monetary Value': re.compile(r'No Monetary Value', re.I),\n              '保留中': re.compile(r'保留中'),",
        "              'No Monetary Value': re.compile(r'No Monetary Value', re.I),\n              'Runtime Deployment in Progress': re.compile(r'Runtime Deployment in Progress', re.I),\n              'No Active': re.compile(r'\\bNo Active\\b', re.I),\n              'Not Activated': re.compile(r'\\bNot Activated\\b', re.I),\n              '保留中': re.compile(r'保留中'),",
        "independent readback prohibited language",
    )
    persist_anchor = dedent(
        '''
              - name: Persist immutable production acceptance evidence
                env:
                  SOURCE_SHA: ${{ github.event.workflow_run.head_sha }}
                  SOURCE_RUN_ID: ${{ github.event.workflow_run.id }}
                  SOURCE_RUN_URL: ${{ github.event.workflow_run.html_url }}
                  AUDIT_SHA256: ${{ steps.readback.outputs.audit_sha256 }}
                  MANIFEST_SHA256: ${{ steps.readback.outputs.manifest_sha256 }}
                shell: bash
                run: |
                  set -euo pipefail
                  mkdir -p evidence/production'''
    ).strip("\n")
    persist_replacement = persist_anchor.replace(
        "          set -euo pipefail\n          mkdir -p evidence/production",
        "          set -euo pipefail\n          git config user.name \"github-actions[bot]\"\n          git config user.email \"41898282+github-actions[bot]@users.noreply.github.com\"\n          git pull --rebase origin main\n          mkdir -p evidence/production",
    )
    readback = replace_once(
        readback,
        persist_anchor,
        persist_replacement,
        "independent readback pull-before-write ordering",
    )
    readback = replace_once(
        readback,
        dedent(
            '''
                      git config user.name "github-actions[bot]"
                      git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
                      git pull --rebase origin main
                      git add evidence/production/docs-status-language-production-acceptance-latest.json \\
            '''
        ).strip("\n"),
        "          git add evidence/production/docs-status-language-production-acceptance-latest.json \\",
        "remove late dirty-tree pull",
    )
    readback = replace_once(
        readback,
        'prohibited_public_terms: ["PENDING", "BLOCKED", "No Monetary Value", "保留中"],',
        'prohibited_public_terms: ["PENDING", "BLOCKED", "Runtime Deployment in Progress", "No Monetary Value", "No Active", "Not Activated", "保留中"],',
        "independent evidence language register",
    )
    write(readback_path, readback)

    write(
        ROOT / "docs/technical-reference/MOBILE_CACHE_RECOVERY_R39.md",
        dedent(
            f'''\
            # JSEC Docs Mobile Cache Recovery R39

            - Public HTML, Web App Manifest and current-state JSON use `no-store` delivery.
            - The installed-app start URL is release-bound to `{TOKEN}`.
            - The historical `official-brand-lockup-r29.js` path is retained as a compatibility refresh controller.
            - Stale pages containing `Runtime Deployment in Progress` or `No Monetary Value` redirect to the canonical current release.
            - Mainnet Changed: false
            - Assets Moved: false
            - Bridge Activated: false
            '''
        ),
    )

    controller = ROOT / ".github/workflows/jsec-docs-mobile-cache-r39-remediation.yml"
    if controller.exists():
        controller.unlink()


if __name__ == "__main__":
    main()
