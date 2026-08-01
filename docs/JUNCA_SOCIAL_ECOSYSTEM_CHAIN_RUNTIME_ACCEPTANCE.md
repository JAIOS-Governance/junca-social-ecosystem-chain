# JUNCA Social Ecosystem Chain — Runtime Acceptance

Status: Public Testnet release control  
Governance: JAIOS Institutional Governance  
Network notice: Public Testnet / Protocol Validation Environment

Runtime acceptance is a fail-closed, machine-readable gate. It does not claim that infrastructure exists merely because configuration is present.

## Required evidence

- Expected Chain ID is returned by the public HTTPS RPC.
- Two or more independently timestamped head samples prove block progression.
- The observed signer set exactly matches three custody-bound validator addresses.
- At least two peers are visible, supporting a 3/3 validator topology.
- Administrative, personal, mining and debug RPC methods are rejected.
- Explorer head equals the last independently collected RPC head.
- Public metadata displays JAIOS Institutional Governance.
- Public metadata displays Public Testnet / Protocol Validation Environment.

## Evidence lifecycle

1. Replace the placeholder-only validator bindings in the policy with fresh, custody-attested addresses.
2. Collect runtime observations without private keys, credentials, query tokens or internal endpoints.
3. Run the acceptance CLI and preserve its SHA-256 evidence digest.
4. Obtain independent readback from a separate network path.
5. Link the accepted evidence to the deployment preflight, build digest, genesis digest and rollback bundle.

A missing or failed gate produces BLOCKED. Mainnet is outside this acceptance policy and remains a separate release decision.
