# JUNCA Social Ecosystem Chain — Bridge Incident Runbook

**Public Testnet / No Monetary Value**

Governance: **JAIOS Institutional Governance**

## Immediate containment

1. Pause the Bridge contract.
2. Pause the Asset Adapter.
3. Keep Mintable ERC-20 and ERC-721 contracts paused.
4. Stop relayer execution workers while preserving the journal and event index.
5. Record the last finalized source block, destination block, message digest,
   source transaction, execution transaction and active configuration digest.

The guardian may pause but may not unpause. Unpause remains an institutional
governance release action.

## Evidence preservation

- preserve SQLite WAL files and chained audit records;
- export the dead-letter queue without rewriting records;
- retain RPC responses, block hashes and confirmation counts;
- retain compiler, ABI, bytecode, SBOM and deployment bundle digests;
- do not expose relayer key material;
- classify every message as unobserved, finality-pending, attested,
  execution-ready, executed or rejected.

## Recovery decision

Recovery is blocked when:

- a reorganization crosses a finalized checkpoint;
- message, source-transaction or source-nonce replay is detected;
- relayer quorum cannot be independently verified;
- contract bytecode differs from the approved build evidence;
- governance, guardian, adapter or asset bindings differ from the manifest;
- daily or per-transaction limits were exceeded;
- source and destination ledgers cannot be reconciled.

## Controlled restoration

1. reproduce the incident against immutable evidence;
2. reconcile source and destination state;
3. rotate affected relayer keys through KMS/HSM procedures;
4. deploy a replacement only when the immutable adapter or route requires it;
5. run contract, property, reorg and runtime acceptance tests;
6. verify explorer source and bytecode;
7. restore relayers before unpausing contracts;
8. unpause in dependency order: token, adapter, bridge;
9. execute a non-monetary testnet acceptance message;
10. publish an institutional incident record without personal-control language.
