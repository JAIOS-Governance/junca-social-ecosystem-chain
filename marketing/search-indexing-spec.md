# Search Indexing Specification

Target: **https://chain.jaios-governance.org/**

Issuer / Operator: **JAIOS Institutional Governance**

## Observed baseline

- Root page: HTTP 200
- Canonical URL: present and self-referencing
- Robots meta: `index, follow`
- Description metadata: present
- Open Graph metadata: present
- Twitter metadata: present
- JSON-LD: present
- `/robots.txt`: HTTP 404 at audit time
- `/sitemap.xml`: HTTP 404 at audit time
- Public search checks: no confirmed indexed result for the target queries at audit time

## Required production files

### robots.txt

```text
User-agent: *
Allow: /

Sitemap: https://chain.jaios-governance.org/sitemap.xml
```

### sitemap.xml

Minimum single-route form:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://chain.jaios-governance.org/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
```

When additional canonical routes are released, include only HTTP 200, indexable, self-canonical pages. Exclude redirects, duplicates, authenticated routes, review routes, parameter variants, and unverified content.

## Page-level requirements

1. Exactly one self-referencing canonical URL per indexable page.
2. Stable English and Japanese title/description parity.
3. One clear H1 using the approved product name.
4. `Organization` and `WebSite` JSON-LD naming `JAIOS Institutional Governance` as the publisher/operator.
5. Direct visible links to the technical reference and canonical repository.
6. No legacy name in title, description, H1, Open Graph, Twitter, or structured data except a labeled history page.
7. No claims that exceed the current release boundary.
8. Accessible link labels; no hidden keyword stuffing or doorway content.

## Canonical entity graph

The brand site should link to:

- https://docs.jaios-governance.org/
- https://github.com/JAIOS-Governance/junca-social-ecosystem-chain

The technical reference and repository should link back to:

- https://chain.jaios-governance.org/

Official social profiles, partner references, press notes, and directory profiles should use the same product name, operator, primary URL, technical URL, and release wording.

## Search Console execution

After owner authentication:

1. Verify the `jaios-governance.org` domain property.
2. Submit `https://chain.jaios-governance.org/sitemap.xml`.
3. Inspect `https://chain.jaios-governance.org/`.
4. Confirm the live test reports HTTP 200, indexable status, selected canonical matching the declared canonical, and no rendering-blocking error.
5. Request indexing.
6. Save the submission date, sitemap status, URL Inspection result, and selected canonical as evidence.
7. Recheck coverage after discovery; do not report indexing until Google shows the URL as indexed.

## Query coverage

Primary entity queries:

- `JUNCA Social Ecosystem Chain`
- `JUNCA Chain`
- `JAIOS Institutional Governance`
- `JAIOS Governance`

Purpose queries:

- `social ecosystem chain governance`
- `institutional blockchain governance`
- `identity participation value circulation blockchain`
- Japanese equivalents centered on 制度設計, 参加構造, 価値循環, and ガバナンス

Queries are editorial topics, not instructions to repeat keywords unnaturally. Each page must answer a distinct reader need with evidence.

## Backlink and distribution controls

Priority links should come from official and directly relevant properties:

1. canonical technical documentation;
2. canonical GitHub repository and release notes;
3. official organization and product profiles;
4. approved partner or ecosystem pages;
5. verified professional-network posts and media references.

Do not buy links, automate low-quality directory submissions, create duplicate microsites, publish spun articles, or use unrelated forum promotion.

## Monitoring

Record separately:

- discoverability: sitemap accepted, crawler access, referring links;
- indexation: indexed URL and Google-selected canonical;
- presentation: title, description, sitelinks, image result;
- engagement: organic landing sessions and meaningful outbound actions;
- integrity: legacy-name sightings, incorrect operator attribution, unsupported claims, duplicate canonicals.

## Acceptance criteria

- Root, robots, and sitemap return HTTP 200.
- Sitemap contains only canonical indexable URLs.
- Brand site, technical reference, repository, and official social profiles form a consistent bidirectional entity graph.
- Search Console property and sitemap are verified.
- URL Inspection evidence is saved.
- Public search result is observed before status is marked indexed.
- No Critical CI, naming, governance, or release-boundary violation remains.
