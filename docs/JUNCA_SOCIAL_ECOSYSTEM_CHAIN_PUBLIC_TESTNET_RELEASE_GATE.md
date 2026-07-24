# Public Testnet Release Decision Contract

## Institutional boundary

- Official chain name: JUNCA Social Ecosystem Chain
- Governance: JAIOS Institutional Governance
- Network: Public Testnet / No Monetary Value
- Mainnet Changed=false
- Assets Moved=false
- Bridge Activated=false
- Bridge Route=PAUSED

The release decision controller does not deploy infrastructure or activate a bridge. It combines independently generated binding, runtime, and rollback evidence into one deterministic decision.

## Evidence inputs

### AWS binding evidence

Must prove:

- authenticated AWS identity and deployment role;
- exactly three failure domains;
- exactly three distinct signer resource references;
- canonical chain ID and genesis hash;
- `AWS_BINDING_READBACK_VERIFIED` status.

### Runtime acceptance evidence

Must prove HTTPS/TLS/DNS, chain identity, advancing and finalized heads, 3/3 validator quorum, peer connectivity, JSON-RPC envelope, unsafe RPC rejection, rate limiting, explorer parity, health, monitoring, restart recovery, and rollback readiness.

Canonical public endpoints are limited to:

- `https://rpc.jaios-governance.org`
- `https://explorer.jaios-governance.org`
- `https://health.jaios-governance.org`

### Rollback acceptance evidence

Must prove endpoint withdrawal, bridge pause, logs and audit preservation, checkpoint availability, binary/genesis/snapshot restore, quorum recovery, read-only endpoint recovery, and explorer parity recovery.

## Decision behavior

The controller returns `PUBLIC_TESTNET_ACCEPTED` only when every required fact is present and consistent. Missing, false, mismatched, non-canonical, or unsafe evidence produces `PUBLIC_TESTNET_REJECTED` with a stable list of failure codes.

The controller writes:

- `public-testnet-release-decision.json`
- `public-testnet-release-decision.json.sha256`

`PUBLIC TESTNET DEPLOYMENT COMPLETE` must not be used until the accepted decision is generated from live evidence and independently read back.

## Command

```bash
python scripts/public_testnet_release_gate.py \
  --binding aws-binding-readback.json \
  --runtime runtime-acceptance.json \
  --rollback rollback-acceptance.json
```
