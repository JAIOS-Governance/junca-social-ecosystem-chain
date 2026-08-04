# Public Status Language Policy

Status: ACTIVE / MANDATORY
Effective: 2026-08-04 JST
Authority: JAIOS Institutional Governance

The JUNCA Social Ecosystem Chain technical reference applies the latest CEO-approved public display vocabulary across every canonical route.

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
- `保留中`

## Approved status families

- `Implemented / CI Verified`
- `Verification in Progress`
- `Not Yet Published`
- `Not Activated`
- `Read-only Evidence Available`
- `Active`

The build normalizes legacy variants, audits visible text for every route, emits `status-language-audit.json`, binds the result into `release-manifest.json`, and fails closed when any prohibited display label remains.

Production acceptance requires successful deployment, CloudFront invalidation, HTTP 200 on all eight routes, public Audit/Manifest parity, and independent post-deployment readback evidence.

Safety boundaries remain unchanged:

- Mainnet Changed: false
- Assets Moved: false
- Bridge Activated: false
