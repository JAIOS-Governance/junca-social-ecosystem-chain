# JUNCA Social Ecosystem Chain — Authenticated State Tree v1

## Status

- Mainnet Candidate implementation
- Activation not authorized
- Mainnet Changed: false
- Assets Moved: false
- Bridge Activated: false

## Objective

Define a deterministic authenticated commitment and proof layer for Mainnet
Candidate state. The component authenticates state values after execution; it
does not authorize transactions or replace consensus finality.

## Construction

- 256-level binary sparse Merkle tree;
- storage keys are `namespace:key` and are hashed under the
  `JUNCA_STATE_KEY_V1` domain;
- leaves commit to key hash and value hash under a dedicated leaf domain;
- internal nodes use ordered left/right domain-separated hashing;
- precomputed empty hashes define the canonical empty tree;
- root construction is independent of input insertion order.

## Proofs

Every proof contains:

- exact 32-byte key hash;
- value hash for inclusion, or `null` for non-inclusion;
- exactly 256 ordered sibling hashes.

Verification derives the path from the key hash and reconstructs the root. A
changed value, key, sibling, order or root fails verification.

## Mutation boundary

- values are bounded to 1 MiB;
- batch writes reject duplicate state keys before commit;
- a failed batch preserves the prior root;
- deletion restores the canonical empty branch where applicable.

## Integration residual

Integration remains required with:

- PR #233 state-transition write sets and finalized persistence;
- protocol block-header state-root commitments;
- snapshot generation and restore;
- Explorer/Indexer state proofs;
- pruning, incremental persistence and production performance tests;
- consensus, security and Mainnet Production Acceptance.

This implementation does not activate Mainnet, assets or bridge functionality.
