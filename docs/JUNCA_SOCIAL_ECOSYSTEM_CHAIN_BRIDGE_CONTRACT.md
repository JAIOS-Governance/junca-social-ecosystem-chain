# JUNCA Social Ecosystem Chain — Testnet Bridge Contract

**Public Testnet / Protocol Validation Environment**

Governance: **JAIOS Institutional Governance**

## Implemented boundary

`JuncaTestnetBridge.sol` is a self-contained destination-chain execution
contract for controlled testnet interoperability. It is designed for deployment
on an EVM-compatible test network after independent review. TRON TVM
compatibility must be confirmed with the selected compiler and Shasta
deployment toolchain before any TRON deployment.

The contract implements:

- paused-by-default activation;
- an institutional-governance address and separate emergency guardian;
- guardian pause permission without guardian unpause permission;
- two-step institutional-governance transfer;
- immutable route and asset-adapter bindings;
- at least three relayers and a signature threshold of at least two;
- Ethereum signed-message recovery with low-`s` malleability rejection;
- duplicate-signer rejection;
- message, source-transaction and source-nonce replay protection;
- execution deadline;
- per-transaction and daily limits;
- reentrancy protection;
- checks-effects-interactions ordering;
- an independently auditable asset-adapter boundary.

`JuncaBridgeAssetAdapter.sol` adds a second fail-closed boundary between the
bridge and mintable assets:

- only the immutable bridge address may request mint execution;
- the adapter and every asset start disabled or paused;
- institutional governance explicitly allowlists each ERC-20 or ERC-721 asset;
- bytes32 address encodings with non-zero high bits are rejected;
- fungible and NFT value semantics are validated separately;
- the guardian can pause but cannot unpause;
- governance transfer uses a two-step acceptance flow;
- no arbitrary call, delegatecall or upgrade proxy is exposed.

## Relayer operational journal

`relayer_journal.py` provides a crash-recoverable SQLite reference queue with:

- unique message digest, source transaction and source nonce constraints;
- WAL-backed persistence;
- expiring worker leases and recovery by another worker;
- strict lease ownership on acknowledgement;
- bounded retries and dead-letter isolation;
- append-only SHA-256 chained audit records;
- deterministic audit-chain verification.

This journal stores operational metadata only. It does not store private keys or
perform signing.

## Release boundary

The repository addition is source implementation, compile input and static
evidence only. It is not a deployment, security audit, custody binding or claim
that a bridge is operational.

The current source compiles successfully with pinned Solidity `0.8.24` and the
optimizer enabled. CI regenerates the ABI, bytecode and static-control evidence
for every relevant pull-request change.

Before a Public Testnet deployment:

1. compile with the pinned Solidity compiler;
2. run contract-level unit, fuzz and invariant tests;
3. implement and audit the chain-specific asset adapter;
4. bind institutional multisig, guardian and KMS/HSM relayer keys;
5. conduct an independent security review;
6. deploy paused;
7. verify source code on the target explorer;
8. run zero-value/non-monetary acceptance scenarios;
9. approve unpause through the institutional release process.
