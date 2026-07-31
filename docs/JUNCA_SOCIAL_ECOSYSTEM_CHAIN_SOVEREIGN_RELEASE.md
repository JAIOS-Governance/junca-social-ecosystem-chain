# JUNCA Social Ecosystem Chain — Institutional Release Standard

Status: PRODUCTION POLICY IMPLEMENTED / PUBLIC TESTNET RUNTIME PENDING

Public governance entity: **JAIOS Institutional Governance**

Operating model: JAIOS-governed automation / separation of duties / former-team dependency prohibited

Testnet label: **Public Testnet / No Monetary Value**

## Brand architecture / ブランド体系

| Layer | Canonical name | Role |
|---|---|---|
| Founding principle | ONE CORE | JUNCAの全事業と社会実装を貫く不変軸 |
| Superordinate ecosystem | JUNCA Intelligence Ecosystem | 人間知、社会、自然、産業、デジタル知性を統合する全体構造 |
| Distributed trust layer | JUNCA Social Ecosystem Chain | 参加、Identity、信頼、価値循環を接続する分散型基盤 |

Official name: `JUNCA Social Ecosystem Chain`

Display name: `JUNCA SOCIAL ECOSYSTEM CHAIN`

Short reference after first use: `JUNCA Chain`

Japanese descriptor: `社会・経済・地域・文化・産業をつなぐ分散型価値循環基盤`

The former public name `JUNCA Global Chain` is restricted to legacy history, compatibility, and migration records. `ONE CORE` and `JUNCA Intelligence Ecosystem` remain superordinate names and must not be reduced to the chain product name. `JSEC` is not an approved public abbreviation.

## Institutional relaunch / 組織統制型再リリース

JUNCA Social Ecosystem Chainは、旧開発チームの運用、秘密鍵、アカウント、非公開手順を前提にしない。JAIOSが統制するリポジトリ、クラウド、ドメイン、鍵管理、Validator、CI/CD、監査証跡によって再構築する。

Existing public code and binaries are evidence inputs, not trusted production dependencies. No legacy private key, mnemonic, credential, signer, service account, or undocumented infrastructure binding is reused.

既存の公開コードとバイナリは監査対象として利用するが、本番依存先にはしない。旧秘密鍵、ニーモニック、認証情報、Signer、サービスアカウント、未記録のインフラ設定は再利用しない。

The relaunch generation is `institutional-v2`, not a capacity-equivalent restoration of the legacy network. The legacy protocol is retained only as an auditable compatibility reference.

再リリース世代は旧版同等復旧ではなく `institutional-v2` とする。旧プロトコルは監査可能な互換性参照に限定する。

## Public representation / 公開表示

Issuance management, release control, treasury custody, protocol continuity, and auditable decision records are publicly attributed to **JAIOS Institutional Governance**. Public materials do not identify an individual officeholder as issuer, manager, controller, or protocol owner.

発行管理、リリース統制、Treasury管理、プロトコル継続、監査可能な意思決定記録の公開上の主体は、**JAIOS Institutional Governance**とする。個人の役職者を発行者、管理者、統制者またはプロトコル所有者として表示しない。

This standard does not authorize unsupported decentralization claims. Responsibility, separation of duties, auditability, evidence, and policy controls must be described accurately.

本基準は、実態のない分散化の表示を認めない。組織責任、職務分離、監査可能性、証跡および方針統制を正確に記載する。

## Asset treatment / 資産区分

| Asset | Treatment |
|---|---|
| Former brand and product identity | Migration reference only |
| Current brand and product identity | JUNCA Social Ecosystem Chain |
| Public source history | Audit reference |
| Published protocol documentation | Specification reference |
| Legacy genesis and chain IDs | Fingerprint and continuity audit |
| Legacy binaries | Reproducibility comparison only |
| Legacy keys and credentials | Prohibited |
| Repository and CI/CD | JAIOS-governed rebuild |
| Validator and bootnode infrastructure | New deployment |
| Operational evidence | New canonical record |

## Network sequence / 実装順序

1. Freeze and fingerprint legacy source, binaries, genesis files, contract addresses, and public documentation.
2. Produce a reproducible client build from the audited source.
3. Create a new-genesis institutional Testnet using newly generated keys and newly provisioned nodes.
4. Validate consensus, quorum loss, node replacement, RPC boundaries, Explorer parity, Governance readback, and rollback.
5. Snapshot-audit the legacy Mainnet state: balances, contracts, token supply, validators, governance state, and unresolved obligations.
6. Select Mainnet continuity only after the audit: preserve verified legacy state with controlled recovery, or migrate verified state into a new institutional genesis.
7. Publish source, binary digest, genesis digest, validator policy, public endpoints, rollback record, and independent readback.

The legacy Chain IDs `668` and `669` remain references until the continuity decision. They are not silently reused for a reset network.

## Institutional governance boundary / 組織統制境界

JAIOS Institutional Governance manages issuance, release control, treasury custody, protocol continuity, and auditable decision records. Routine engineering, build, test, deployment, monitoring, evidence generation, failover, and rollback are automated under separation of duties.

発行管理、リリース統制、Treasury管理、プロトコル継続、監査可能な意思決定記録はJAIOS Institutional Governanceが担う。通常の開発、Build、Test、Deployment、監視、証跡生成、Failover、Rollbackは職務分離の下で自動化する。

## Current gates / 現在のゲート

| Gate | State |
|---|---|
| JAIOS institutional governance policy | EXECUTED |
| Former-team dependency removal | EXECUTED in policy |
| Policy and architecture negative tests | VERIFIED by CI |
| Legacy source fingerprint implementation | VERIFIED by CI |
| Reproducible node build | VERIFIED by CI / runtime binding pending |
| New-genesis public Testnet configuration | EXECUTED / deployment PENDING |
| New-key custody attestation | PENDING |
| Validator quorum and RPC boundary | PENDING runtime evidence |
| Explorer and governance readback | PENDING runtime evidence |
| Rollback and independent readback | PENDING runtime evidence |
| Mainnet snapshot audit and continuity decision | PENDING |

No public relaunch is classified as complete until runtime evidence, independent readback, and rollback evidence all pass.

## Mainnet controlled-activation authorization evidence

`scripts/junca_mainnet_release_authorization_gate.py` validates a short-lived,
domain-separated authorization envelope before any Mainnet activation controller
may become eligible to run. Validation is intentionally separate from execution:
a successful result records `authorization_evidence_valid=true` and
`activation_executed=false`.

The envelope must bind the exact repository, source commit and tree, release
manifest, immutable artifact, SBOM, genesis, release request, Creative
Constitution revision and Constitution digest. Two unique independent approvals
must review that same commit and tree before the verified Founder / Chairman /
CEO identity records final approval. Authorization windows are limited to 15
minutes; final approval may be at most 24 hours old and reviews at most 72 hours
old.

An append-only consumed-evidence ledger rejects reuse of the authorization ID,
authorization digest, request digest, or release-manifest digest. Any mismatch,
duplicate reviewer, stale or future window, altered digest, or unsafe boundary
fails closed. Evidence cannot set `Mainnet Changed`, `Assets Moved`, `Bridge
Activated`, or `Mainnet Activation Authorized` to true. This gate performs no
merge, workflow dispatch, deployment, AWS mutation, asset movement, bridge
activation, or Mainnet activation.

## Scalable architecture baseline / 拡張基準

| Area | Initial baseline |
|---|---|
| Validators / quorum | 9 / 7 target after testnet validation |
| Bootnodes | 5 target |
| Public/private RPC nodes | 6 target |
| Indexers / archive nodes | 3 / 2 target |
| Failure domains | 5 target |
| Sustained / burst throughput | 2,000 / 5,000 TPS target; benchmark required |
| Finality | p95 ≤ 6 seconds target; benchmark required |
| RPC read latency | p95 ≤ 250 ms target; benchmark required |
| Availability | 99.95% target; runtime evidence required |

Execution client, consensus engine, precompile registry, bridge adapter, indexer sink, RPC policy, fee policy, and governance adapter are explicit versioned extension boundaries. Business logic must not be coupled directly to consensus.

The private-bootstrap Chain ID candidate is `20260723`. It is not authorized for public use until collision review and registration evidence pass. The legacy IDs `668` and `669` remain audit references.
