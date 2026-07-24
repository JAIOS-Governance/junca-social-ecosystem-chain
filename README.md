# JUNCA Social Ecosystem Chain

Canonical protocol source for **JUNCA Social Ecosystem Chain**.

| Field | Canonical value |
|---|---|
| Governance | JAIOS Institutional Governance |
| Network status | Public Testnet / No Monetary Value |
| Repository role | Protocol, node, network specification, interoperability and release evidence |
| Corporate ownership | None represented |

This repository is governed as an institutional protocol boundary. JUNCA
companies may contribute to and use the network, but no company, executive or
individual is represented as the owner or sole controller of the chain.

## Repository boundary

Included:

- protocol, runtime and node implementation;
- genesis and network specifications;
- validator, RPC and explorer infrastructure contracts;
- chain SDKs, interoperability and bridge safety controls;
- security, release, acceptance and rollback evidence.

Excluded:

- corporate websites and marketing applications;
- company administration and unrelated JAIOS business systems;
- product-specific application code that consumes the chain;
- private keys, seed phrases and signer secret values.

The machine-verifiable boundary is defined in
[`governance/repository-boundary.json`](governance/repository-boundary.json).

## Public-testnet safety

Infrastructure remains fail-closed until canonical cloud binding, three
independent signer resources, validator quorum, TLS/DNS, read-only RPC,
monitoring, runtime acceptance and rollback readback are verified.

Mainnet changed: **false**  
Assets moved: **false**  
Bridge activated: **false**

## Governance

Public materials must use **JAIOS Institutional Governance** for issuance,
protocol, operational and release management. They must not imply CEO,
founder, company or individual control. This requirement does not authorize a
false claim of decentralization; actual responsibilities and separation of
duties must remain auditable.

See [`GOVERNANCE.md`](GOVERNANCE.md) and [`SECURITY.md`](SECURITY.md).
