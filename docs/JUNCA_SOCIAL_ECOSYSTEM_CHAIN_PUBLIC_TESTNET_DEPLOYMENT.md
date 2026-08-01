# JUNCA Social Ecosystem Chain — Public Testnet Deployment

**Governance:** JAIOS Institutional Governance  
**Network notice:** Public Testnet / Protocol Validation Environment

## Deployment topology

The Public Testnet uses three validator nodes placed in distinct failure domains. Validator JSON-RPC binds to loopback and is never exposed directly. Public traffic terminates at a replicated TLS gateway that permits read-only methods, applies rate limits, and rejects transaction broadcast and administrative namespaces.

The Explorer reads finalized indexed state through a separate read-only boundary. Monitoring observes validator quorum, RPC head lag, disk capacity, and public health independently from the validator hosts.

## Controlled rollout

1. Verify binary, genesis, source and configuration digests.
2. Bind external Secret Manager or HSM signer resources.
3. Deploy validators sequentially across three failure domains.
4. Verify validator quorum and advancing finalized head.
5. Deploy the read-only TLS RPC gateway.
6. Run live RPC acceptance and unsafe-method rejection.
7. Deploy the Explorer and verify head parity.
8. Enable independent monitoring.
9. Publish Public Testnet endpoints only after all gates are accepted.

## Rollback

Public endpoints are withdrawn before validator recovery. Bridge routes remain paused. Logs, audit evidence and the last finalized checkpoint are preserved. The last verified binary and genesis are restored, quorum is re-established, and read-only endpoints return only after acceptance passes again.

## Release boundary

This deployment plan does not create infrastructure, bind secrets, activate bridge routes, move assets, or modify Mainnet. Actual resource creation and endpoint publication require the accepted deployment binding evidence and independent readback.
