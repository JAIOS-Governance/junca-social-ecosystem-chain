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
finalized persistence boundary for JUNCA Social Ecosystem Chain Mainnet
Candidate development. It is an implementation primitive, not a Mainnet
activation or an asset issuance mechanism.

## Chain identity binding

Every transaction, snapshot and persistent store is bound to:

- positive `chain_id`;
- exact 32-byte `genesis_hash`;
- semantic `protocol_version`;
- canonical state and storage schema versions.

A transaction or persistent store for another chain, genesis or protocol
version is rejected before any state mutation.

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

## Snapshot persistence and recovery

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

## Finalized SQLite WAL ledger

`FinalizedStateStore` provides a transactional persistence foundation for
finalized snapshots.

The store:

- uses SQLite WAL mode, `synchronous=FULL`, foreign-key enforcement and a bounded busy timeout;
- binds immutable metadata to chain ID, genesis hash, protocol version and schema versions;
- requires a canonical genesis snapshot before finalized blocks are persisted;
- requires contiguous finalized height and increasing timestamps;
- binds every persisted block to the previous state root, current state root,
  block receipt hash, snapshot digest and raw snapshot SHA-256;
- accepts only an exact duplicate as idempotent and rejects a conflicting record
  for an existing height;
- executes writes inside `BEGIN IMMEDIATE` transactions with rollback on error;
- validates snapshot byte integrity, snapshot digest, state root and chain binding
  during restore;
- exposes database integrity, WAL mode and finalized-head evidence without
  representing the Candidate as activated.

This is a finalized snapshot ledger foundation. Production scale storage,
incremental authenticated trees, pruning and multi-node snapshot distribution
remain separate acceptance work.

## Security properties implemented

- chain/genesis/protocol replay separation;
- exact sender nonce progression;
- deterministic transaction and write-set commitments;
- explicit fail-closed signature-verifier boundary;
- conditional writes preventing lost updates;
- atomic transaction and block rollback;
- bounded state value, operation, transaction-resource and block-resource size;
- deterministic snapshot integrity verification;
- transactional finalized-height continuity;
- persistent receipt and snapshot provenance binding;
- store metadata mismatch rejection;
- no implicit Mainnet, asset or bridge activation.

## Integration residual

This primitive remains to be integrated with:

- production transaction signature recovery;
- the Mainnet mempool candidate;
- execution-module adapters and receipt/event production;
- consensus block proposal and certified finality;
- incremental authenticated state-tree storage and pruning;
- snapshot distribution, restore authorization and recovery governance;
- runtime upgrade/migration rehearsal;
- Explorer/Indexer ingestion;
- Mainnet QA, Security, Performance and Production Acceptance.

No integration residual may be represented as completed until corresponding
code, CI and runtime evidence exist.
