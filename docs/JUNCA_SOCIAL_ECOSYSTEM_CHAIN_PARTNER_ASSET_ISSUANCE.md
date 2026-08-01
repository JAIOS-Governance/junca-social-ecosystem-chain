# JUNCA Social Ecosystem Chain — Partner Asset Issuance

Governance: JAIOS Institutional Governance  
Network: Public Testnet / Protocol Validation Environment

This control plane converts a partner token or NFT specification into deterministic, auditable deployment evidence. It does not deploy contracts and does not represent legal, economic or security approval.

## Supported initial profiles

- ERC-20 fungible-token issuance plan
- ERC-721 NFT collection issuance plan

Additional standards require a separate compatibility and security review.

## Mandatory controls

- Public Testnet chain ID binding
- Separated admin, treasury and pauser addresses
- Institutional multisig custody
- Fixed maximum supply
- No default upgradeability
- Partner authorization
- Legal review
- Security review
- Metadata rights confirmation
- Testnet-only attestation
- Deterministic specification digest and deployment salt

Incomplete attestations produce BLOCKED. Invalid or unsafe specifications are rejected. Placeholder addresses are examples only and must be replaced with independently verified custody-bound addresses.

## Release sequence

1. Partner use case and asset specification
2. Responsibility and custody binding
3. Legal and metadata-rights review
4. Contract implementation against the approved manifest
5. Unit, invariant and negative tests
6. Independent security review
7. Public Testnet deployment
8. Explorer verification and runtime readback
9. Partner acceptance
10. Separate Mainnet release decision

Mainnet deployment, bridge integration, liquidity, exchange listing and monetary-value claims are outside this control plane.
