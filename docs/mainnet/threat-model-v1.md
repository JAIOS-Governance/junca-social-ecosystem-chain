# JUNCA Social Ecosystem Chain Mainnet Threat Model v1

Status: **CANDIDATE / SECURITY ACCEPTANCE PENDING**

Authority: **JAIOS Institutional Governance**

## Protected assets

- canonical chain and genesis identity;
- finalized state and block history;
- validator signing authority;
- validator-set and governance transitions;
- immutable runtime artifacts and release manifests;
- RPC and P2P availability;
- snapshots, backups and recovery anchors;
- application, asset and interoperability extension boundaries.

## Trust boundaries

1. Validator signer boundary — KMS/HSM reference only; no private key material in runtime or repository.
2. Consensus network boundary — authenticated validator messages, strict validator-set membership and replay-domain binding.
3. Public P2P boundary — untrusted peers, bounded resources, scoring and rate controls.
4. Public RPC boundary — read/query and transaction interfaces separated from validator/admin RPC.
5. Build/release boundary — source SHA, dependency lock, SBOM, artifact digest, genesis digest and signed manifest.
6. Governance boundary — proposal, security review, release approval, infrastructure operation and evidence custody remain independently attributable.
7. Interoperability boundary — external finality and relayer attestations are untrusted until verified under an approved adapter policy.

## Consensus threats and controls

### Equivocation and double-signing

Controls:

- persistent one-choice-per-validator-height-round signing journal;
- monotonic signing watermarks;
- canonical signing payload verification on startup;
- exact pending-proposal reuse during recovery;
- conflicting vote and proposal rejection;
- independent signer-resource binding.

### Replay and cross-network substitution

Controls:

- chain ID, genesis hash, protocol version and network-profile domain separation;
- sender nonce progression and validity windows;
- validator-set hash binding in consensus proofs;
- duplicate transaction and vote detection;
- rejection below finalized and signing watermarks.

### Byzantine validator behavior

Required tests:

- conflicting votes;
- invalid signatures;
- stale/future rounds;
- proposer failure;
- quorum withholding;
- validator-set mismatch;
- network partition and delayed delivery;
- coordinated minority faults;
- recovery without unsafe finalization.

### Long-range and state-substitution attacks

Controls:

- independently anchored finalized checkpoints;
- trusted genesis and validator-set history;
- certificate reconstruction from signed votes;
- archive/evidence retention;
- checkpoint restore requiring multiple trusted anchors.

## Network threats

- eclipse and peer isolation;
- connection floods and oversized messages;
- transaction spam and mempool exhaustion;
- slowloris and bandwidth amplification;
- malformed gossip and state-range responses;
- time/clock manipulation;
- DNS/TLS and endpoint substitution.

Required controls include peer diversity, bounded queues, per-peer quotas, canonical message limits, rate limiting, authenticated validator channels, clock-drift alarms and fail-closed endpoint identity verification.

## Key compromise

Required response path:

1. detect and isolate signer reference;
2. prevent further signing by policy/IAM;
3. preserve audit evidence;
4. submit governed validator/key rotation candidate;
5. verify new signer binding and recovery state;
6. rehearse rollback and validator re-entry;
7. publish sanitized incident evidence.

Emergency authority may pause unsafe interfaces but may not rewrite finalized history, expose secrets or bypass governance audit.

## Supply-chain threats

Controls:

- exact source SHA and reproducible build;
- dependency lock and vulnerability audit;
- SPDX SBOM;
- artifact and container digest;
- immutable AMI/image provenance;
- signed release manifest;
- protected workflows and environment approvals;
- no historical CI reuse for a new candidate.

## State and infrastructure threats

- storage corruption;
- disk exhaustion;
- snapshot tampering;
- destructive Terraform replacement;
- regional outage;
- backup loss;
- monitoring blind spots;
- rollback failure.

Acceptance requires integrity checks, retained state volumes, snapshot digests, no-destroy plan guard, multi-region topology, tested restore, immutable rollback points and disaster-recovery exercises.

## Application and interoperability threats

- unsafe module capability escalation;
- incompatible runtime upgrade;
- event/log ambiguity;
- bridge replay and finality substitution;
- relayer collusion;
- asset-limit bypass;
- unauthorized activation.

All extension modules and bridges remain capability-scoped, versioned, paused by default and governed. Bridge activation and asset movement remain false until separate acceptance and CEO approval.

## Acceptance status

This document defines the threat model baseline. Penetration testing, Byzantine testing, infrastructure review, key ceremony and disaster-recovery acceptance remain required.

- Mainnet Changed = false
- Assets Moved = false
- Bridge Activated = false
