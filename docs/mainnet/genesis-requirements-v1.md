# Mainnet Genesis Candidate Requirements v1

Status: **REQUIREMENTS CANDIDATE / NO GENESIS ACTIVATION**

Authority: **JAIOS Institutional Governance**

## Canonical identity

A Mainnet Genesis Candidate must commit to the complete network identity:

- genesis schema and protocol version;
- unique Mainnet chain ID;
- network profile `mainnet`;
- governance authority and constitutional compatibility reference;
- genesis timestamp and activation policy;
- initial validator-set hash;
- execution configuration and resource limits;
- initial state root;
- upgrade-policy hash;
- release-manifest digest.

Every field is included in the canonical genesis digest. Unknown fields, missing fields and non-canonical encodings fail closed.

## Validator candidate

The initial validator set must satisfy the governed Mainnet production policy:

- at least nine validators;
- quorum greater than 75 percent;
- at least three geographic regions;
- at least five independent failure domains;
- distinct validator identity and signer-resource binding;
- voting-power concentration within policy;
- completed key ceremony and key-compromise recovery evidence;
- independent admission approvals.

Raw private keys, seed phrases and signer secret values are prohibited from the genesis document, repository, artifact and logs.

## Initial state

Initial state must be deterministic and independently reproducible. The candidate may define accounts, modules and permissions as specifications, but no asset issuance, movement or bridge activation occurs without separate governance and CEO approval.

Required commitments:

- ordered allocation/module manifest;
- initial account/state root;
- initial module-registry hash;
- fee/resource-policy hash;
- permission/governance-role hash;
- zero or explicitly approved supply semantics;
- explicit `assets_moved=false` before activation.

## Execution configuration

The genesis candidate binds:

- supported transaction types;
- execution adapter version;
- block gas/resource limits;
- fee-policy parameters;
- maximum transaction data size;
- event/log schema version;
- state storage and migration schema version.

## Governance and upgrades

The genesis candidate includes immutable references to:

- protocol amendment workflow;
- independent review requirements;
- emergency authority boundary;
- validator lifecycle policy;
- upgrade activation-delay policy;
- rollback and disaster-recovery policy;
- audit/evidence custody requirements.

## Evidence package

Acceptance requires:

1. canonical genesis JSON;
2. genesis SHA-256 and signed release manifest;
3. deterministic generation command and independent reproduction;
4. validator-set and key-ceremony evidence;
5. state-root vectors;
6. protocol and execution configuration digests;
7. security review;
8. disaster-recovery rehearsal;
9. Public Testnet Mainnet-Candidate rehearsal;
10. CEO Final Approval for controlled activation.

## Activation boundary

This requirements document does not create or activate a Mainnet genesis.

- Mainnet Changed = false
- Assets Moved = false
- Bridge Activated = false
