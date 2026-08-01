# Brand Search Surface — Production Handoff

Target: `https://chain.jaios-governance.org/`

Operator: `JAIOS Institutional Governance`

## Purpose

This package contains the exact crawler, sitemap and structured-data corrections required by the production search-surface audit. It is a deployment input for the existing brand Site, not a replacement site.

## Production boundary

- Preserve the existing custom-domain DNS, design, content, access mode and version lineage.
- Deploy only through the verified existing brand-site project in the authorized Sites workspace.
- Do not create a substitute Sites project and do not change DNS.
- If the existing project cannot be read back, keep Deployment pending while retaining this completed Production package.

## Production changes

1. Publish `robots.txt` at the public root as `/robots.txt`.
2. Publish `sitemap.xml` at the public root as `/sitemap.xml`.
3. Replace the current root `WebSite` JSON-LD object with `website.jsonld`, or apply its missing canonical `url` fields without changing the approved name or operator.
4. Do not publish `website.jsonld` as a standalone public page; it is the exact source fragment for the root `<script type="application/ld+json">` element.

## Verified route inventory

The following routes returned HTTP 200 on 2026-07-27 JST and are the only routes included in this handoff sitemap:

- `https://chain.jaios-governance.org/`
- `https://chain.jaios-governance.org/context`
- `https://chain.jaios-governance.org/foundation`
- `https://chain.jaios-governance.org/build`
- `https://chain.jaios-governance.org/possibilities`
- `https://chain.jaios-governance.org/ecosystem`
- `https://chain.jaios-governance.org/experience`
- `https://chain.jaios-governance.org/governance`
- `https://chain.jaios-governance.org/evidence`
- `https://chain.jaios-governance.org/contact`

`https://docs.jaios-governance.org/` remains an independent technical-reference origin and must not appear in the brand sitemap.

## Acceptance sequence

1. Read back the exact existing Sites project and current production version.
2. Apply only the three changes described above.
3. Save a new version and deploy through the existing project.
4. Verify HTTP 200 for root, all sitemap URLs, `/robots.txt` and `/sitemap.xml`.
5. Run `python scripts/junca_chain_search_surface_audit.py` and require `PASS`.
6. Confirm canonical, Open Graph, Twitter metadata, social image, JSON-LD, operator name and legacy-name exclusion remain green.
7. Submit `https://chain.jaios-governance.org/sitemap.xml` in the verified `jaios-governance.org` Search Console property.
8. Inspect and request indexing for `https://chain.jaios-governance.org/`.
9. Preserve Search Console submission and URL Inspection evidence.

## Release boundary

- Mainnet Changed: `false`
- Assets Moved: `false`
- Bridge Activated: `false`
- Network wording: `Public Testnet / Protocol Validation Environment`
