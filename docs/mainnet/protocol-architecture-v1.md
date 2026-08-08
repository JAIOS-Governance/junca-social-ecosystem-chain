# JUNCA Social Ecosystem Chain Mainnet Protocol Architecture v1

Status: **CANDIDATE / NOT ACTIVATED**

Authority: **JAIOS Institutional Governance**

## 1. Architecture boundary

JUNCA Social Ecosystem Chain Mainnet is defined as a governed, deterministic state machine replicated by a Byzantine-fault-tolerant validator network. Public Testnet is the verification environment for Mainnet candidates and is not the completion target.

The consensus-critical boundary consists of:

1. canonical genesis identity;
2. canonical block and transaction encoding;
3. deterministic state transition;
4. validator-set and consensus-round commitments;
5. certified finality;
6. persistent finalized state and recovery;
7. versioned execution and upgrade rules;
8. cryptographic transaction and validator authentication;
9. governed release and activation evidence.

## 2. Node roles

- **Validator Node** — proposes, verifies, signs and finalizes blocks under the active validator set.
- **Full Node** — verifies canonical blocks and maintains current executable state without signing consensus votes.
- **Read Node** — serves policy-limited query/RPC traffic from verified finalized state.
- **Archive Node** — retains full historical blocks, receipts, events and state-access evidence.
- **Indexer Node** — builds finalized-only search surfaces for blocks, transactions, addresses and events.

Node-role separation is mandatory. Public RPC must not share validator administration or signer privileges.

## 3. Block model

The versioned canonical header commits to:

- protocol version and network profile;
- chain ID, height, round and timestamp;
- parent hash and proposer identity;
- state root;
- transaction and receipt roots;
- validator-set hash;
- gas/resource fields.

The block body contains a canonical ordered transaction sequence and execution receipts. Transaction and receipt roots are separately domain-separated.

## 4. Transaction and execution model

Transactions are domain-separated by chain ID, genesis hash, protocol version and network profile. Admission requires:

- cryptographic signature verification;
- exact sender nonce progression;
- replay-domain verification;
- validity window;
- resource-limit and fee-policy compliance;
- transaction-type capability support.

Execution is versioned behind an adapter boundary. Business/application modules must not be coupled directly to consensus logic. Module descriptors are deterministic, capability-based and reviewed before activation.

## 5. State and persistence

State transition is atomic and deterministic. Every finalized block binds a state root and certificate. Mainnet storage must support:

- write-ahead durability;
- snapshot/export and independently anchored restore;
- pruning for full nodes;
- isolated archive tier;
- online schema migration;
- state-growth limits and observability;
- disaster-recovery rehearsals.

The current SQLite implementation is a deterministic reference and test foundation, not the final Mainnet storage engine.

## 6. Consensus and finality

Mainnet consensus uses a deterministic validator-set-bound leader schedule, round timeouts and strict Byzantine quorum. Finality certificates must bind:

- chain ID;
- height and round;
- block hash;
- active validator-set hash;
- signed and total voting power;
- canonical validator identities and vote hashes.

Persistent anti-double-signing watermarks and exact proposal reuse are mandatory. Round changes preserve valid lock state and may not change chain or validator-set identity.

## 7. Validator lifecycle

Validator admission, removal, rotation, voting-power change and signer rotation are governed transitions. Initial production policy targets at least nine validators, at least three regions, at least five failure domains and a quorum greater than 75 percent. No single validator may exceed the configured concentration boundary.

## 8. Networking and RPC

P2P protocol families are independently versioned for handshake, peer status, transactions, proposals, votes, finality proofs, block ranges and snapshots. Mainnet networking requires peer scoring, bounded queues, backpressure, anti-eclipse controls, rate limiting and authenticated validator channels.

Transaction RPC is not enabled until signature, replay, mempool, abuse-control and node-role acceptance are complete.

## 9. Governance and upgrade

Protocol changes move through proposal, independent review, security review, release approval, immutable artifact production, rehearsal, activation scheduling and post-activation evidence. Emergency governance may pause unsafe interfaces but may not silently alter finalized state or bypass audit trails.

## 10. Extensibility

Required extension boundaries:

- execution client;
- consensus engine;
- precompile/module registry;
- bridge adapter;
- indexer sink;
- RPC policy;
- fee/resource policy;
- governance adapter.

API compatibility uses semantic versioning plus capability negotiation. Migration rules must be deterministic and replayable.

## 11. Mainnet release boundary

Mainnet Release Candidate requires Protocol, Consensus, Validator, Execution, State, P2P/RPC, Security, Governance, Performance, Infrastructure, Recovery, Explorer, SDK and Application Integration acceptance.

Until controlled activation:

- Mainnet Changed = false
- Assets Moved = false
- Bridge Activated = false
