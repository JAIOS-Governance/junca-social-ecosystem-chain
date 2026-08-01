# JUNCA Social Ecosystem Chain — Deployment Recovery

**Governance:** JAIOS Institutional Governance  
**Network:** Public Testnet / Protocol Validation Environment

## Current release boundary

PR #166 is integrated at main commit
`8ee00768536aa54df6d83f47283dd6d5fd7ddcc6`. The deterministic topology,
three-validator failure-domain contract, private validator RPC boundary,
replicated read-only public RPC gateway, Explorer, monitoring and rollback plan
are source-verified.

Actual cloud resource creation remains fail-closed until the authoritative
provider, account scope, project, region, network, DNS zone, failure domains,
state backend, deployment principal and three external signer resources are
read back from the official account. Values must not be inferred from another
JUNCA or JAIOS project.

## Recovery gates

The canonical binding evaluator:

- requires exact institutional governance and no-value testnet notice;
- refuses Mainnet, asset movement and bridge activation;
- requires three distinct failure domains and three external signer resources;
- rejects secret-material fields;
- records a deterministic binding fingerprint;
- emits only redacted presence evidence.

Runtime acceptance v2 covers HTTPS, TLS, DNS, chain ID, genesis identity,
advancing and finalized heads, validator quorum, peer count, JSON-RPC response
identity and envelope, unsafe-method rejection, rate limiting, Explorer parity,
health, monitoring, restart recovery and rollback readiness.

The unsafe set includes administrative, debug, personal, mining and transaction
broadcast methods, including `eth_sendRawTransaction` and
`eth_sendTransaction`.

Rollback acceptance requires endpoint withdrawal, bridge pause preservation,
logs and audit preservation, finalized checkpoint preservation, verified
binary/genesis restore, quorum recovery, read-only endpoint restoration and
Explorer parity in a non-production rehearsal.

## Promotion rule

`PUBLIC TESTNET DEPLOYMENT COMPLETE` and `ACCEPTED` are prohibited until real
cloud binding, deployment, live runtime acceptance, rollback readback and
independent evidence all pass. Mainnet remains unchanged, no assets are moved,
and bridge routes remain paused.
