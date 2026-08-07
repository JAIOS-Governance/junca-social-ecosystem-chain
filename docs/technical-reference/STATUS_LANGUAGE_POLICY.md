# Public Status Language Policy

Status: ACTIVE / MANDATORY
Effective: 2026-08-07 JST
Authority: Latest CEO directive, Creative Constitution and JAIOS Institutional Governance
Source revision: R38.3 / Canonical Runtime Corroboration Repair

The JUNCA Social Ecosystem Chain technical reference applies evidence-first, governance-accurate public vocabulary across every canonical route.

## Canonical routes

- `/`
- `/protocol`
- `/assets`
- `/interoperability`
- `/implementation`
- `/governance`
- `/evidence`
- `/glossary`

## Prohibited public labels

- `PENDING`
- `BLOCKED`
- `No Monetary Value`
- `No Active`
- `Not Activated`
- `Not Yet Published`
- `NOT CURRENTLY PUBLISHED`
- `EVIDENCE REFRESHING`
- `Not Launched`
- `not-activated`
- `保留中`

## Approved status families

- `Implemented / CI Verified`
- `Verification in Progress`
- `Registry-Controlled Disclosure`
- `Governance-Controlled Activation`
- `Evidence-bound Read-only Access`
- `Finality Certificate Observed`
- `Separate Governance Release`
- `Boundary Unchanged`
- `Active / Active Advancing`

## Runtime connection authority

- Canonical Explorer evidence: `https://explorer.jaios-governance.org/explorer.json`
- Operational API corroboration: `https://chain.jaios-governance.org/api/operational`
- Same-origin continuity proxy: `https://docs.jaios-governance.org/explorer.json`
- Canonical network identity: Chain ID `20260723`
- Acceptance boundary: schema `junca-public-explorer/v4`, read-only, finalized-only, quorum `3/3`, authenticated peers `2/2`

Browser and build readback attempt the canonical Explorer endpoint first with bounded retries. The same-origin route is retained only as a verified continuity fallback. The canonical Explorer remains the rendered-state authority. The Operational API independently corroborates chain identity, quorum, runtime provenance and safety boundaries without imposing a race-prone exact cross-endpoint snapshot lock. No endpoint may update the page unless its assigned validation boundary passes.

The build normalizes legacy variants, audits visible text for every route, emits `status-language-audit.json`, binds the result into `release-manifest.json`, and fails closed when any prohibited display label remains.

Production acceptance requires successful deployment, CloudFront invalidation, HTTP 200 on all eight routes, public Audit/Manifest parity, canonical endpoint readback and independent post-deployment verification.

Safety boundaries remain machine-verifiable and are presented publicly with affirmative governance language:

- Mainnet State: `UNCHANGED`
- Production Asset Boundary: `UNCHANGED`
- Bridge State: `GOVERNANCE-CONTROLLED`
- Mainnet Release: `SEPARATE AUTHORIZATION`
