# Protocol Governance

## Institutional responsibility

JUNCA Social Ecosystem Chain is managed under **JAIOS Institutional
Governance**. JUNCA companies are ecosystem participants and contributors, not
the represented owners of the protocol.

## Separation of duties

No production release or network-state change may be completed by a sole
personal authority. The repository requires independently attributable roles:

1. **Protocol Maintainer** — prepares protocol and network changes.
2. **Security Reviewer** — reviews security boundary and negative tests.
3. **Release Approver** — approves signed release evidence.
4. **Infrastructure Operator** — deploys only an approved immutable release.
5. **Evidence Custodian** — records acceptance and rollback readback.

A person may not approve their own protected production change. Exact GitHub
teams and identities are binding configuration and must be read back before
protected deployment.

## Protected changes

The following require protected review, successful CI and immutable evidence:

- protocol or consensus changes;
- genesis, chain ID or network specification changes;
- validator topology or signer reference changes;
- RPC exposure and unsafe-method policy changes;
- bridge route activation;
- release workflow or governance policy changes;
- Mainnet or real-asset changes.

## Public representation

Required:

- `JAIOS Institutional Governance`
- `Public Testnet / Protocol Validation Environment` while the network is a testnet

Prohibited:

- CEO-controlled or CEO-managed
- founder-controlled
- sole personal authority
- corporate-owned chain
- unsupported claims of decentralization or independent external governance

## Current release boundary

- Mainnet changed: false
- Assets moved: false
- Bridge activated: false
- Cloud binding: pending / fail-closed
- Runtime deployment: pending
