# JUNCA Social Ecosystem Chain Operations

Status: IMPLEMENTED CONTROL PLANE / NETWORK RECOVERY REQUIRED

Applied date: 2026-07-23 UTC

Authority: JAIOS Institutional Governance, Creative Constitution, Drive masters, official Juncachain documentation

Release authority model: JAIOS Institutional Governance. Former-team operational dependency is prohibited. See `docs/JUNCA_SOCIAL_ECOSYSTEM_CHAIN_SOVEREIGN_RELEASE.md`.

Canonical public identity: `JUNCA Social Ecosystem Chain`. The former name `JUNCA Global Chain` may appear only in legacy history and migration evidence.

## Purpose / 目的

Operate JUNCA Social Ecosystem Chain through evidence-backed health readback, bounded recovery, and independently reviewable release records. The control plane separates network condition from implementation completion and does not label an unreachable chain as healthy.

JUNCA Social Ecosystem Chainを、証跡に基づく稼働確認、限定的な復旧、独立検証可能なリリース記録によって運営する。ネットワーク状態と実装完了を分離し、到達不能なチェーンを正常とは判定しない。

## Canonical network contract / 公式ネットワーク契約

| Network | Chain ID | Public RPC | WebSocket | Explorer | Governance |
|---|---:|---|---|---|---|
| Mainnet | 668 (`0x29c`) | `https://rpc.juncachain.com` | `wss://ws.juncachain.com` | `https://scan.juncachain.com` | `https://master.juncachain.com` |
| Testnet | 669 (`0x29d`) | `https://rpc-testnet.juncachain.com` | `wss://ws-testnet.juncachain.com` | `https://scan-testnet.juncachain.com` | `https://master-testnet.juncachain.com` |

Consensus: PoSV. Official client repository: `juncachain/juncachain`. Latest published client observed during intake: `v0.2.8`.

## Implemented / 実装済み

- Sovereign v2 scale and extension architecture contract
- Private-bootstrap topology: 9 validators, quorum 7, 5 bootnodes, 6 RPC nodes
- Legacy source fingerprint with raw and canonical genesis digests
- Pinned legacy source commit and reproducible-build contract
- Public-use denial for unregistered candidate Chain ID
- Modular boundaries for execution, consensus, precompile, bridge, indexer, RPC, fee, and governance components
- Exact chain-ID validation before accepting any other RPC evidence
- Latest block number and timestamp readback
- Head-staleness rejection after 300 seconds
- Peer connectivity readback
- Client-version readback
- Endpoint credential/query/fragment rejection
- URL and error redaction in evidence
- Deterministic health states: `healthy`, `degraded`, `unhealthy`
- JAIOS Health Dashboard adapter
- Atomic JSON evidence output
- Unit, negative, fail-closed, and redaction tests

## Run / 実行

```bash
python scripts/junca_social_ecosystem_chain_bootstrap.py

python scripts/junca_social_ecosystem_chain_readiness.py \\
  --expect-state blocked \\
  --output artifacts/junca-social-ecosystem-chain-readiness.json

python scripts/junca_social_ecosystem_chain_fingerprint.py \
  --source-root ../chain-repo \
  --output artifacts/junca-social-ecosystem-chain-legacy-fingerprint.json

python scripts/junca_social_ecosystem_chain_probe.py \
  --config config/junca_social_ecosystem_chain_networks.json \
  --output artifacts/junca-social-ecosystem-chain-health.json
```

The throughput, finality, latency, and availability values in the scale profile are test targets, not public performance claims. Public SLO claims remain fail-closed until load, chaos, state-growth, upgrade-rehearsal, and bridge-security gates pass.

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | All selected networks healthy |
| 2 | No healthy endpoint; at least one endpoint degraded |
| 3 | One or more selected networks unhealthy |

The evidence file contains public endpoint names and operational metrics only. It must not contain private keys, signer material, service-account values, private project identifiers, or unpublished infrastructure bindings.

## Recovery order / 復旧順序

1. Preserve genesis files and `v0.2.8` as the last published baseline.
2. Restore at least three geographically separated bootnodes for each network.
3. Start non-signing full nodes and verify genesis hash, Chain ID, peer count, and head convergence.
4. Restore private RPC upstreams; expose only `eth`, `net`, and `web3` to the public gateway.
5. Keep `admin`, `debug`, `miner`, `personal`, and `txpool` unavailable on public HTTP/WS.
6. Restore public RPC behind health-checked failover and bounded rate limits.
7. Restore Explorer indexers after RPC head convergence.
8. Restore Governance dApp read-only mode before enabling any transaction action.
9. Validate Mainnet and Testnet independently; do not infer one from the other.
10. Record commit SHA, binary SHA-256, genesis SHA-256, node count, head, peer count, and rollback route before production classification.

## Current network evidence / 現在のネットワーク証跡

Readback on 2026-07-23 returned HTTP 502 connection-refused responses and timeouts from the documented Mainnet and Testnet RPC endpoints. Explorer, Governance, and Testnet Faucet endpoints were also unreachable from the independent probe route. Therefore:

- Control plane implementation: `EXECUTED`
- Unit and negative QA: local PASS / GitHub CI PENDING
- Mainnet/Testnet public serving: `UNHEALTHY`
- Block production and validator quorum: `UNVERIFIED`
- Cloud infrastructure binding and signer custody: `PENDING / OWNER-GATED`

## Release gate / リリースゲート

Production classification requires all of the following:

- exact Chain ID and genesis hash
- advancing head observed across independent nodes
- non-zero peers and quorum evidence
- public RPC negative-method checks
- Explorer head parity
- Governance read-only smoke
- binary digest and source commit identity
- rollback package
- no secrets in logs or artifacts
- independent readback after promotion

No validator key, treasury key, deployer key, RPC credential, or private infrastructure value may be committed to GitHub or written into the evidence artifact.

## Machine-enforced readiness / 機械判定リリース準備

The readiness controller rejects promotion unless every required gate is explicitly verified. Missing, extra, non-boolean, or renamed gates invalidate the evidence. The current private-Testnet candidate remains `blocked` until reproducible build, new-key custody, validator quorum, RPC boundary, Explorer parity, Governance readback, rollback, and independent readback evidence pass.

Readiness evidence contains no secret values. It records only the release target, source commit, boolean gate results, missing gate names, and deterministic state.
