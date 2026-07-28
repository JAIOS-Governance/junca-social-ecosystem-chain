# JUNCA Social Ecosystem Chain — Mainnet Candidate State Transition v1

## Status

- Classification: Mainnet Candidate protocol implementation
- Activation: not authorized
- Mainnet Changed: false
- Assets Moved: false
- Bridge Activated: false
- Public Testnet role: integration, recovery, performance and upgrade verification

## Purpose

This specification defines a deterministic, atomic state-transition and
snapshot boundary for JUNCA Social Ecosystem Chain Mainnet Candidate
development. It is an implementation primitive, not a Mainnet activation or an
asset issuance mechanism.

## Chain identity binding

Every transaction and snapshot is bound to:

- positive `chain_id`;
- exact 32-byte `genesis_hash`;
- semantic `protocol_version`;
- canonical schema version.

A transaction for another chain, genesis or protocol version is rejected before
any state mutation.

## State model

State is module-scoped under a canonical `namespace:key` identifier.

Each transaction contains an ordered tuple of conditional writes. A write
commits to:

- namespace and key;
- expected prior value hash;
- new value hash or deletion marker;
- new value size.

Duplicate writes to the same key within one transaction are prohibited.

## Atomicity

Transaction processing follows a fail-closed sequence:

1. validate chain and protocol domain;
2. reject prior transaction replay;
3. require the sender's exact next nonce;
4. require an explicit cryptographic verifier and accept only literal `True`;
5. enforce deterministic transaction resource limits;
6. validate every state precondition;
7. apply all writes;
8. advance the sender nonce;
9. create deterministic receipt evidence.

Any error restores state, nonce and replay bookkeeping to the pre-transaction
snapshot.

Block processing is also atomic. Transactions are applied in order against the
candidate state. A failed transaction or block resource overflow restores the
entire pre-block state. Successful blocks require exact height progression,
monotonic timestamps and an exact parent-state-root match.

## State commitment

The state root is a domain-separated SHA-256 commitment over:

- chain and genesis identity;
- protocol and schema version;
- sorted state-key value hashes and sizes;
- sorted account nonces.

The commitment is deterministic and independent of input mapping order.

## Receipts

Transaction receipts commit to:

- transaction hash;
- sender and nonce;
- resource units used;
- pre-state and post-state roots;
- ordered write-set hash;
- applied status.

Block receipts commit to:

- height and timestamp;
- parent and resulting state roots;
- ordered transaction hashes;
- ordered transaction-receipt hashes;
- aggregate resource units.

## Persistence and recovery

Canonical snapshots contain:

- chain identity and protocol version;
- finalized height and timestamp;
- exact state root;
- state values encoded as validated Base64;
- sender nonces;
- explicit activation safety flags.

The snapshot envelope includes a domain-separated digest. Restore rejects
malformed data, duplicate keys or nonces, digest mismatch, state-root mismatch,
schema mismatch or altered safety boundaries.

## Security properties implemented

- chain/genesis/protocol replay separation;
- exact sender nonce progression;
- deterministic transaction and write-set commitments;
- explicit fail-closed signature-verifier boundary;
- conditional writes preventing lost updates;
- atomic transaction and block rollback;
- bounded state value, operation, transaction-resource and block-resource size;
- deterministic snapshot integrity verification;
- no implicit Mainnet, asset or bridge activation.

## Integration residual

This primitive remains to be integrated with:

- production transaction signature recovery;
- the Mainnet mempool candidate;
- execution-module adapters and receipt/event production;
- consensus block proposal and certified finality;
- authenticated storage/database implementation;
- snapshot distribution and restore governance;
- runtime upgrade/migration rehearsal;
- Explorer/Indexer ingestion;
- Mainnet QA, Security and Production Acceptance.

No integration residual may be represented as completed until corresponding
code, CI and runtime evidence exist.
