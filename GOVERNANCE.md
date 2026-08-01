# Protocol Governance

## Institutional responsibility

JUNCA Social Ecosystem Chain is managed under **JAIOS Institutional
Governance**. JUNCA companies are ecosystem participants and contributors, not
the represented owners of the protocol.

## Separation of duties

No production release or network-state change may be completed by a sole
personal authority. The repository requires independently attributable roles:

1. **Protocol Maintainer** — prepares protocol and network changes.
2. **Security Reviewer** — reviews security boundary and negative tests.
3. **Release Approver** — approves signed release evidence.
4. **Infrastructure Operator** — deploys only an approved immutable release.
5. **Evidence Custodian** — records acceptance and rollback readback.

A person may not approve their own protected production change. Exact GitHub
teams and identities are binding configuration and must be read back before
protected deployment.

## Mainnet delivery cell / Mainnet開発セル

Effective 2026-08-01, the former **JSEC Native Genesis Release Cell** is
disqualified from continuing Mainnet delivery because repeated monitoring and
evidence-only runs did not produce source implementation progress.

2026-08-01付で、監視・証跡のみの反復によりソース実装が前進しなかった
**JSEC Native Genesis Release Cell** はMainnet開発の継続不適合とする。

The active replacement is **JSEC Mainnet Native Release Engineering Cell**.
Its accountable position is **Mainnet Protocol Delivery & Release Lead** and
the fixed release target remains **2026-10-01**.

新担当は **JSEC Mainnet Native Release Engineering Cell**、責任者
ポジションは **Mainnet Protocol Delivery & Release Lead** とし、固定の
リリース目標日は **2026-10-01** のまま変更しない。

The mandatory delivery sequence is:

1. development;
2. repair and refinement;
3. audit;
4. activation under separate authorization;
5. monitoring;
6. post-activation repair and refinement;
7. stabilization.

Monitoring evidence alone is not implementation progress. A monitoring-only
Mainnet delivery claim is a material governance violation. When monitoring
detects a fault it must identify one reproducible cause and lead directly to a
repair action. Public Testnet continuity remains mandatory and must not be
stopped by Mainnet development activity.

監視証跡だけを実装進捗として扱うことを禁止する。Mainnet開発における
監視のみの進捗申告は重大なガバナンス違反とする。監視で障害を検出した
場合は、再現可能な原因を一意に特定し、直ちに修繕アクションへ接続する。
Mainnet開発を理由としたPublic Testnetの停止は認めない。

## Protected changes

The following require protected review, successful CI and immutable evidence:

- protocol or consensus changes;
- genesis, chain ID or network specification changes;
- validator topology or signer reference changes;
- RPC exposure and unsafe-method policy changes;
- bridge route activation;
- release workflow or governance policy changes;
- Mainnet or real-asset changes.

## Public representation

Required:

- `JAIOS Institutional Governance`
- `Public Testnet / Protocol Validation Environment` while the network is a testnet

Prohibited:

- CEO-controlled or CEO-managed
- founder-controlled
- sole personal authority
- corporate-owned chain
- unsupported claims of decentralization or independent external governance

## Current release boundary

- Mainnet changed: false
- Assets moved: false
- Bridge activated: false
- Cloud binding: pending / fail-closed
- Runtime deployment: pending
