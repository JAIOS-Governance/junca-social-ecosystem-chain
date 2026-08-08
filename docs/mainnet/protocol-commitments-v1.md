# Mainnet Candidate Protocol Commitments v1

Status: **IMPLEMENTATION CANDIDATE / NOT ACTIVATED**

Authority: **JAIOS Institutional Governance**

## Purpose

This specification introduces versioned, deterministic commitment primitives for a future JUNCA Social Ecosystem Chain Mainnet block format. It does not activate Mainnet and does not modify the current Public Testnet runtime.

## Canonical body commitments

A block body commits separately to the ordered transaction-hash sequence and the ordered receipt-hash sequence.

- Every input is a normalized 32-byte hexadecimal hash.
- Transaction and receipt counts must match.
- Empty sequences have an explicit domain-separated root.
- Leaves and internal nodes use different domain prefixes.
- Odd tree levels duplicate the final node.
- Transaction and receipt roots use different domains and cannot be substituted.

## Canonical header commitments

The candidate header commits to:

- protocol version;
- network profile;
- chain ID;
- height and consensus round;
- timestamp;
- parent hash;
- state root;
- transaction root;
- receipt root;
- validator-set hash;
- proposer identity;
- gas limit, gas used and base fee.

The block hash is SHA-256 over a domain-separated canonical JSON payload. Field names, lowercase hash normalization, sort order and separators are consensus-critical.

## Safety boundary

This module produces candidate evidence only.

- `activation_status=CANDIDATE_NOT_ACTIVATED`
- `mainnet_changed=false`
- `assets_moved=false`
- `bridge_activated=false`

Runtime integration requires a separate protected PR, deterministic cross-language vectors, migration rules, security review and Mainnet governance approval.

## Required follow-on work

1. Bind execution output to transaction and receipt hashes.
2. Add protocol-version compatibility and migration rules.
3. Bind proposer selection and validator-set activation to consensus rounds.
4. Produce cross-language golden vectors for SDK and node implementations.
5. Integrate the candidate header into Public Testnet as a Mainnet-candidate validation profile without changing the activation boundary.
