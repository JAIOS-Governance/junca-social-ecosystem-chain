"use client";

import { useMemo, useState } from "react";

type Status = "READY" | "CONDITIONAL" | "BLOCKED" | "NOT APPLICABLE";

const capabilityRows = [
  ["Smart contract execution", "DApp and asset logic", "Enterprise / Developer", "Pending Verification", "Compatibility evidence required"],
  ["Fungible token issuance", "Utility, access, points", "Enterprise / Issuer", "Planned", "Token standard not yet verified"],
  ["NFT issuance", "Membership, certificate, provenance", "Brand / IP / Region", "Planned", "NFT standard not yet verified"],
  ["Wallet integration", "Signing and asset access", "Partner / User", "Pending Verification", "Candidate Chain ID only"],
  ["Public RPC / WebSocket", "Network connection", "Developer / Integrator", "Pending Deployment", "No public endpoint released"],
  ["Explorer verification", "Transaction and contract evidence", "All partners", "Pending Deployment", "Runtime parity gate required"],
  ["Faucet", "Test asset distribution", "Developer", "Pending Deployment", "Rate-limit acceptance required"],
  ["Ethereum / ERC interoperability", "ERC-20 and ERC-721 cross-network route", "Integrator / Custodian", "Planned · BLOCKED", "Target Ethereum network binding and contracts Pending Verification"],
  ["BSC Testnet interoperability", "ERC-20/BEP-20 and ERC-721 route control", "Integrator / Custodian", "Implemented · BLOCKED", "No deployed route or asset movement"],
  ["TRON Shasta interoperability", "ERC-20/TRC-20 and ERC-721/TRC-721 route control", "Integrator / Custodian", "Implemented · BLOCKED", "TVM and Shasta deployment verification required"],
  ["Scalability profile", "Capacity planning", "Institutional", "Target Only", "Load and chaos tests incomplete"],
];

const interoperabilityRoutes = [
  ["JUNCA ↔ Ethereum / ERC", "ERC-20 / ERC-721", "Target network binding Pending Verification", "lock / mint / burn / release", "BLOCKED"],
  ["JUNCA → BSC Testnet", "ERC-20 ↔ BEP-20", "BSC Chain ID 97", "lock / mint / burn / release", "BLOCKED"],
  ["JUNCA → BSC Testnet", "ERC-721 ↔ BSC-compatible ERC-721", "BSC Chain ID 97", "lock / mint / burn / release", "BLOCKED"],
  ["JUNCA ↔ TRON Shasta", "ERC-20 ↔ TRC-20", "Network ID tron-shasta", "lock / mint / burn / release", "BLOCKED"],
  ["JUNCA ↔ TRON Shasta", "ERC-721 ↔ TRC-721", "Network ID tron-shasta", "lock / mint / burn / release", "BLOCKED"],
];

const bridgeControls = [
  ["Paused by default", "A new route cannot execute until institutional release approval."],
  ["Relayer quorum", "At least three distinct relayers; threshold is two or more verified signatures."],
  ["Finality", "Execution readiness requires the configured confirmation depth."],
  ["Replay protection", "Message, source transaction and source nonce are independently rejected on reuse."],
  ["Custody & roles", "Institutional multisig, separate guardian and KMS/HSM-backed relayer keys are release prerequisites."],
  ["Limits & incident control", "Per-transaction and daily limits, emergency pause and an approved incident runbook."],
];

const adoptionSteps = [
  ["01", "Use-case definition", "Partner", "Purpose, participants, value flow", "Approved scope"],
  ["02", "Architecture review", "Partner + Technical team", "On/off-chain map, data classification", "Architecture decision"],
  ["03", "Governance & compliance", "Partner + JAIOS", "Role matrix, legal review, custody model", "Control acceptance"],
  ["04", "Testnet access", "JAIOS Institutional Governance", "Approved network configuration", "Access evidence"],
  ["05", "Contract development", "Development partner", "Source, tests, dependency record", "Review candidate"],
  ["06", "Security testing", "Independent reviewer", "Threat model, test evidence, findings", "Critical findings closed"],
  ["07", "Runtime acceptance", "JAIOS + Partner", "Advancing head, signer set, RPC boundary", "Machine decision"],
  ["08", "Operational readiness", "Partner operator", "Monitoring, incident, migration", "Readiness checklist"],
  ["09", "Mainnet release review", "Institutional governance", "Release packet and approvals", "Separate GO decision"],
  ["10", "Post-release monitoring", "Shared responsibility", "Telemetry, audit trail, incident evidence", "Continuous control"],
];

const responsibilities = [
  ["Protocol governance", "JAIOS Institutional Governance", "Evidence and release control", "Protocol acceptance record"],
  ["Network / validator operations", "Authorized network operators", "Keys, quorum, continuity", "Custody and health evidence"],
  ["Token or NFT administration", "External partner", "Supply, mint, pause, ownership", "Partner approval trail"],
  ["Treasury and wallet custody", "External partner / appointed custodian", "Signing policy and segregation", "Custody attestation"],
  ["Metadata administration", "External partner", "Rights, permanence, personal-data exclusion", "Schema and storage evidence"],
  ["Contract implementation", "Development partner", "Code, tests, deployment package", "Commit and test report"],
  ["Legal / regulatory position", "External partner with qualified advisers", "Classification and jurisdiction", "Recorded review"],
  ["Incident response", "Shared, by incident domain", "Containment, evidence, migration", "Incident and closure record"],
];

const risks = [
  ["Smart contract vulnerability", "Independent review, unit and negative tests", "Source SHA, test report, closure log"],
  ["Private or admin key compromise", "Multisig or institutional custody, separation of duties", "Custody attestation, signer register"],
  ["Upgrade and ownership risk", "Explicit upgrade policy, timelock where appropriate", "Admin matrix, upgrade test"],
  ["Metadata loss or mutation", "Storage selection, integrity hash, recovery copy", "URI, digest, retention plan"],
  ["Personal data exposure", "Keep personal data off-chain; minimize metadata", "Data classification and privacy review"],
  ["Regulatory classification", "Jurisdiction-specific qualified review", "Recorded legal analysis; no platform guarantee"],
  ["Bridge / oracle dependency", "Isolate, limit, monitor; independent security review", "Dependency inventory and incident route"],
  ["Operational continuity", "Monitoring, backup, migration and exit procedure", "Runbook and rehearsal evidence"],
];

const readinessItems = [
  "Use case defined",
  "Token / NFT purpose defined",
  "Legal review completed",
  "Contract owner identified",
  "Admin roles separated",
  "Treasury custody defined",
  "Supply and mint policy defined",
  "Metadata storage defined",
  "Personal data excluded",
  "Unit tests passed",
  "Security review passed",
  "Testnet deployment completed",
  "Contract verified",
  "Explorer readback completed",
  "Monitoring configured",
  "Incident contacts defined",
  "Migration procedure defined",
  "Release approval recorded",
  "Bridge route starts paused",
  "Relayer quorum verified",
  "Replay protection tested",
  "Finality policy verified",
  "Bridge incident runbook approved",
];

const networkSample = `// network-readiness.mjs
const candidate = {
  name: "JUNCA Social Ecosystem Chain Public Preview Testnet",
  chainId: 20260723,
  rpcUrl: process.env.JUNCA_TESTNET_RPC_URL,
  notice: "Public Testnet / No Monetary Value"
};

if (!candidate.rpcUrl) {
  throw new Error("BLOCKED: verified RPC binding is required");
}

console.log(JSON.stringify({
  ...candidate,
  rpcUrl: "[configured / redacted]"
}, null, 2));`;

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "gold" | "block" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function CopyBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(code);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = code;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className="code-wrap">
      <button className="copy-button" onClick={copy} aria-label="Copy code">
        {copied ? "Copied" : "Copy"}
      </button>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function Flow({ title, subtitle, nodes, gate }: { title: string; subtitle: string; nodes: string[]; gate?: string }) {
  return (
    <figure className="flow-figure">
      <figcaption>
        <span>{title}</span>
        <small>{subtitle}</small>
      </figcaption>
      <div className="flow">
        {nodes.map((node, index) => (
          <div className="flow-unit" key={node}>
            <div className="flow-node">{node}</div>
            {index < nodes.length - 1 && <span className="flow-arrow" aria-hidden="true">→</span>}
          </div>
        ))}
      </div>
      {gate && <div className="gate-note">{gate}</div>}
    </figure>
  );
}

function SectionHeading({ index, eyebrow, title, ja }: { index: string; eyebrow: string; title: string; ja: string }) {
  return (
    <header className="section-heading">
      <span className="section-index">{index}</span>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p className="ja-heading" lang="ja">{ja}</p>
      </div>
    </header>
  );
}

export default function Home() {
  const initial = Object.fromEntries(readinessItems.map((item) => [item, "BLOCKED"])) as Record<string, Status>;
  const [checks, setChecks] = useState<Record<string, Status>>(initial);
  const readiness = useMemo<Status>(() => {
    const values = Object.values(checks);
    if (values.includes("BLOCKED")) return "BLOCKED";
    if (values.includes("CONDITIONAL")) return "CONDITIONAL";
    return "READY";
  }, [checks]);

  return (
    <main>
      <header className="site-header">
        <a href="#top" className="wordmark" aria-label="JUNCA Social Ecosystem Chain home">
          <span>JUNCA</span>
          <small>Social Ecosystem Chain</small>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#capabilities">Capabilities</a>
          <a href="#issuance">Issuance</a>
          <a href="#interoperability">Interoperability</a>
          <a href="#developer">Developer</a>
          <a href="#governance">Governance</a>
          <a href="#readiness">Readiness</a>
        </nav>
        <Badge tone="block">Controlled Release</Badge>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Institutional Technical Reference · Protocol / Assets / Interoperability</p>
          <h1>JUNCA Social Ecosystem Chain</h1>
          <p className="hero-ja" lang="ja">プロトコル・アーキテクチャ／資産標準／相互運用／制度的ガバナンス</p>
          <p className="hero-lead">
            An institutional reference defining protocol boundaries, network state, asset standards,
            interoperability controls, governance responsibilities and release evidence.
          </p>
          <p className="hero-lead ja" lang="ja">
            JUNCA Social Ecosystem Chainの技術境界、ネットワーク状態、資産規格、相互運用統制、
            ガバナンス責任およびリリース証跡を体系化した専門技術リファレンス。
          </p>
          <div className="document-identifiers" aria-label="Document identification">
            <span>Class · Technical Reference</span>
            <span>Authority · JAIOS Institutional Governance</span>
            <span>Release · Controlled / Evidence Gated</span>
          </div>
        </div>
        <aside className="hero-panel" aria-label="Current release status">
          <div className="status-kicker">Protocol status register</div>
          <dl>
            <div><dt>Network</dt><dd>Public Preview Testnet candidate</dd></div>
            <div><dt>Chain ID</dt><dd><code>20260723</code> <span>candidate / not publicly registered</span></dd></div>
            <div><dt>Consensus</dt><dd>PoSV · 3-validator candidate topology</dd></div>
            <div><dt>Block period</dt><dd>2 seconds · configuration, not an SLO</dd></div>
            <div><dt>Interoperability</dt><dd>Ethereum / ERC · BSC Testnet · TRON Shasta <span>Ethereum binding planned; BSC/TRON controls implemented · all routes BLOCKED</span></dd></div>
            <div><dt>Runtime acceptance</dt><dd><Badge tone="block">BLOCKED</Badge></dd></div>
          </dl>
          <div className="testnet-notice">Public Testnet / No Monetary Value</div>
          <p>Issuance, protocol, treasury, operation and release controls: <strong>JAIOS Institutional Governance</strong>.</p>
        </aside>
      </section>

      <section className="context-band" aria-label="Technical reference domains">
        <div><strong>01</strong><span>Protocol · consensus, network boundary and runtime state</span></div>
        <div><strong>02</strong><span>Assets · ERC, token, NFT and credential models</span></div>
        <div><strong>03</strong><span>Interoperability · Ethereum / ERC, BSC and TRON controls</span></div>
      </section>

      <section className="reference-index" aria-labelledby="reference-index-title">
        <div className="reference-index-head">
          <div>
            <p className="eyebrow">Abstract / 文書要旨</p>
            <h2 id="reference-index-title">Protocol, assets and institutional operation as one technical system.</h2>
            <p lang="ja">プロトコル、デジタル資産、相互運用、制度的運用を一つの技術体系として定義する。</p>
          </div>
          <dl>
            <div><dt>Document class</dt><dd>Institutional Technical Reference</dd></div>
            <div><dt>Protocol authority</dt><dd>JAIOS Institutional Governance</dd></div>
            <div><dt>Network state</dt><dd>Public Testnet / No Monetary Value</dd></div>
            <div><dt>Publication state</dt><dd>Controlled · Evidence Gated</dd></div>
          </dl>
        </div>
        <nav className="chapter-index" aria-label="Technical reference contents">
          <a href="#overview"><span>01</span><strong>Protocol Scope</strong><small>Architecture and adoption state</small></a>
          <a href="#capabilities"><span>02</span><strong>Capability Register</strong><small>Evidence classification</small></a>
          <a href="#issuance"><span>03</span><strong>Fungible Assets</strong><small>Supply, authority, treasury</small></a>
          <a href="#nft"><span>04</span><strong>Non-Fungible Assets</strong><small>Identity and provenance</small></a>
          <a href="#interoperability"><span>05</span><strong>Interoperability</strong><small>Ethereum / ERC, BSC, TRON</small></a>
          <a href="#use-cases"><span>06</span><strong>Applied Architectures</strong><small>Asset and service patterns</small></a>
          <a href="#developer"><span>07</span><strong>Implementation</strong><small>Binding and verification</small></a>
          <a href="#adoption"><span>08</span><strong>Adoption Lifecycle</strong><small>Evidence-gated progression</small></a>
          <a href="#governance"><span>09</span><strong>Governance</strong><small>Authority and responsibility</small></a>
          <a href="#security"><span>10</span><strong>Security</strong><small>Risk and control evidence</small></a>
          <a href="#resources"><span>11</span><strong>References</strong><small>Canonical technical sources</small></a>
          <a href="#readiness"><span>12</span><strong>Readiness</strong><small>Release classification</small></a>
          <a href="#evidence"><span>13</span><strong>Evidence Matrix</strong><small>Known, pending and blocked</small></a>
        </nav>
      </section>

      <section className="content-section" id="overview">
        <SectionHeading index="01" eyebrow="Protocol Scope" title="Protocol architecture and adoption state." ja="プロトコル構造と採用状態。" />
        <div className="two-column">
          <div className="prose">
            <p>
              The chain is being prepared as a trust, participation and value-circulation layer.
              Adoption is structured around verifiable network configuration, partner-owned asset design,
              institutional release control and independently readable evidence.
            </p>
            <p lang="ja">
              チェーンは、参加・アイデンティティ・価値循環を接続する信頼基盤として整備中です。
              外部パートナーの資産設計責任と、ネットワーク側の制度的なリリース統制を分離します。
            </p>
          </div>
          <div className="status-ledger">
            <article><Badge>Implemented</Badge><p>Control plane, brand contract, release policy, fail-closed evidence logic.</p></article>
            <article><Badge tone="gold">In validation</Badge><p>Reproducible build, new-key custody, genesis and runtime acceptance.</p></article>
            <article><Badge tone="block">Not released</Badge><p>Public RPC, WebSocket, Explorer, Faucet and Mainnet partner deployment.</p></article>
          </div>
        </div>
        <Flow title="Chain adoption flow" subtitle="採用全体フロー" nodes={["Define purpose", "Review architecture", "Build & test", "Runtime acceptance", "Operate & evidence"]} gate="Mainnet release is a separate institutional decision." />
      </section>

      <section className="content-section" id="capabilities">
        <SectionHeading index="02" eyebrow="Capability Register" title="Capability classification and evidence state." ja="機能分類と実装証跡の状態。" />
        <div className="table-scroll" role="region" aria-label="Capability status table" tabIndex={0}>
          <table>
            <thead><tr><th>Capability</th><th>Use</th><th>Audience</th><th>Status</th><th>Condition</th></tr></thead>
            <tbody>
              {capabilityRows.map((row) => <tr key={row[0]}>{row.map((cell, i) => <td key={cell}>{i === 3 ? <Badge tone={cell.includes("Pending") || cell === "Planned" ? "gold" : "neutral"}>{cell}</Badge> : cell}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
        <p className="source-note">Scalability values in the repository are targets, not public guarantees. Load, chaos, state-growth, upgrade-rehearsal and bridge-security gates remain incomplete.</p>
      </section>

      <section className="content-section" id="issuance">
        <SectionHeading index="03" eyebrow="Fungible Asset Architecture" title="Supply, authority and treasury control." ja="供給・権限・トレジャリー統制。" />
        <div className="editorial-grid">
          <article>
            <h3>Purpose & economics</h3>
            <p>Define function, participants, supply logic, distribution, vesting and off-chain obligations before selecting a contract standard.</p>
            <p lang="ja">用途、参加者、供給、配布、Vesting、会計・法務上の責任を先に確定します。</p>
          </article>
          <article>
            <h3>Authority & custody</h3>
            <p>Separate owner, mint, burn, pause, treasury and upgrade roles. Prefer multisig or institutional custody where the risk profile requires it.</p>
            <p lang="ja">Owner、Mint、Burn、Pause、Treasury、Upgradeの権限を分離します。</p>
          </article>
          <article>
            <h3>Compatibility gate</h3>
            <p>Token standards, contract upgrade patterns and tooling remain <strong>Pending Verification</strong> until tested against the current client build.</p>
            <p lang="ja">対応規格と開発ツールは、現行クライアント上の実行確認後に確定します。</p>
          </article>
        </div>
        <Flow title="Token issuance lifecycle" subtitle="トークン発行ライフサイクル" nodes={["Purpose & classification", "Supply & authority", "Contract & tests", "Testnet evidence", "Release & monitoring"]} gate="No economic value or legal conformity is guaranteed by JAIOS Institutional Governance." />
        <div className="decision-row">
          {[
            ["Fixed supply", "No post-release minting; migration planning becomes central."],
            ["Mintable", "Requires controlled mint authority, limits and observable events."],
            ["Burnable", "Requires clear holder/admin rights and supply reconciliation."],
            ["Upgradeable", "Adds administrator and migration risk; must be explicitly governed."],
          ].map(([title, text]) => <article key={title}><h3>{title}</h3><p>{text}</p></article>)}
        </div>
      </section>

      <section className="content-section" id="nft">
        <SectionHeading index="04" eyebrow="Non-Fungible & Credential Architecture" title="Identity, provenance and metadata permanence." ja="識別性・来歴・メタデータ永続性。" />
        <div className="two-column">
          <div className="prose">
            <h3>Asset models</h3>
            <p>Single assets, collections and semi-fungible patterns remain subject to verified standard compatibility. Suitable use cases may include membership, certificates, access passes, authenticity records and licensed brand or IP assets.</p>
            <h3>Metadata discipline</h3>
            <p>Record schema, storage, integrity hash, update authority, retention, licensing and migration. Personal information should not be placed on-chain or in public metadata.</p>
          </div>
          <div className="storage-compare">
            <div><strong>Distributed storage</strong><span>Integrity and persistence planning; availability still requires operational stewardship.</span></div>
            <div><strong>Managed storage</strong><span>Controlled service levels and access; introduces provider and continuity dependencies.</span></div>
            <div><strong>Hybrid record</strong><span>On-chain digest plus governed off-chain asset; requires recovery and migration evidence.</span></div>
          </div>
        </div>
        <Flow title="NFT issuance and metadata flow" subtitle="NFT・メタデータフロー" nodes={["Rights & schema", "Asset storage", "Integrity digest", "Mint & transfer policy", "Preservation & migration"]} gate="Token URI, royalties and transfer restrictions remain subject to compatibility verification." />
      </section>

      <section className="content-section interoperability-section" id="interoperability">
        <SectionHeading index="05" eyebrow="Interoperability Control Plane" title="Ethereum / ERC, BSC and TRON route architecture." ja="Ethereum／ERC・BSC・TRON相互運用経路。" />
        <div className="two-column">
          <div className="prose">
            <p>
              The repository implements deterministic, fail-closed route validation for JUNCA Public Testnet,
              BSC Testnet and TRON Shasta. It also includes a testable bidirectional message reference engine
              and a destination-chain execution contract for controlled testnet review.
            </p>
            <p lang="ja">
              リポジトリには、JUNCA Public Testnet、BSC Testnet、TRON Shasta間のルート検証、
              双方向メッセージ状態機械、テストネット用実行コントラクトが実装されています。
              ただし、コントラクト配備、Relayer運用、資産移動は実施されていません。
            </p>
          </div>
          <div className="status-ledger">
            <article><Badge>Implemented</Badge><p>Route schema, SHA-256 evidence, protocol state machine, simulation and Solidity 0.8.24 compile evidence.</p></article>
            <article><Badge tone="gold">Test evidence</Badge><p>Interoperability, protocol and contract-control tests: 20/20 in the latest PR record.</p></article>
            <article><Badge tone="block">BLOCKED</Badge><p>Placeholder contracts, false attestations, no custody binding, no independent security review and no live relayer set.</p></article>
          </div>
        </div>

        <div className="table-scroll" role="region" aria-label="Interoperability route matrix" tabIndex={0}>
          <table>
            <thead><tr><th>Route</th><th>Asset mapping</th><th>Network identity</th><th>Bridge mode</th><th>Release state</th></tr></thead>
            <tbody>
              {interoperabilityRoutes.map((row) => <tr key={`${row[0]}-${row[1]}`}>{row.map((cell, i) => <td key={cell}>{i === 4 ? <Badge tone="block">{cell}</Badge> : cell}</td>)}</tr>)}
            </tbody>
          </table>
        </div>

        <Flow
          title="Cross-network message state"
          subtitle="クロスネットワーク・メッセージ状態"
          nodes={["OBSERVED", "FINALITY_PENDING", "ATTESTED", "EXECUTION_READY", "EXECUTED"]}
          gate="Execution readiness requires finality, verified relayer quorum, an unpaused approved route and limit checks."
        />

        <div className="bridge-control-grid">
          {bridgeControls.map(([title, text]) => <article key={title}><h3>{title}</h3><p>{text}</p></article>)}
        </div>

        <div className="legal-note">
          <strong>Implemented boundary / 実装境界</strong>
          <p>
            BSC Testnet is identified by EVM Chain ID <code>97</code>. TRON Shasta is identified as
            <code>tron-shasta</code>; no fictitious EVM Chain ID is assigned. Solidity compilation does not
            prove TRON TVM compatibility. Target-chain compilation, deployment, source verification and
            independent security review remain mandatory.
          </p>
          <p lang="ja">
            BSC TestnetはChain ID 97、TRON Shastaはnetwork identifier「tron-shasta」で識別します。
            Solidityのコンパイル成功はTRON TVM互換性を保証しません。対象チェーンでの再検証が必要です。
          </p>
        </div>
      </section>

      <section className="content-section" id="use-cases">
        <SectionHeading index="06" eyebrow="Applied Architectures" title="Asset, credential and service patterns." ja="資産・証明・サービスの適用構造。" />
        <div className="table-scroll use-case-matrix" role="region" aria-label="Use case comparison matrix" tabIndex={0}>
          <table>
            <thead><tr><th>Use case</th><th>On-chain</th><th>Off-chain</th><th>Primary control</th><th>Status</th></tr></thead>
            <tbody>
              {[
                ["Enterprise utility token", "Balances, transfer events", "Terms, account records", "Supply and treasury", "Planned"],
                ["Loyalty / points", "Optional asset record", "Customer and settlement data", "Privacy and reconciliation", "Planned"],
                ["Membership credential", "Credential reference", "Member profile", "Revocation and privacy", "Planned"],
                ["Brand / IP NFT", "Ownership and provenance", "Media and licence", "Rights and metadata", "Planned"],
                ["Authenticity certificate", "Digest and issuer", "Product dossier", "Issuer custody", "Planned"],
                ["Ticket / access pass", "Access asset state", "Identity and event ops", "Transfer and expiry", "Planned"],
                ["Regional ecosystem token", "Asset and settlement events", "Local operating rules", "Governance and compliance", "Planned"],
                ["Digital certificate", "Digest and status", "Evidence file", "Issuer and revocation", "Planned"],
                ["Community participation", "Participation receipt", "Personal data and moderation", "Data minimization", "Planned"],
                ["DApp / marketplace", "Contract events", "Search, content, support", "Platform and contract admin", "Pending Verification"],
              ].map((row) => <tr key={row[0]}>{row.map((cell, i) => <td key={cell}>{i === 4 ? <Badge tone="gold">{cell}</Badge> : cell}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
        <Flow title="On-chain and off-chain architecture" subtitle="データ分離" nodes={["User / enterprise record", "Data classification", "Minimal on-chain state", "Governed off-chain evidence", "Audit readback"]} />
      </section>

      <section className="content-section" id="developer">
        <SectionHeading index="07" eyebrow="Implementation Reference" title="Network binding, contract toolchain and verification." ja="ネットワーク接続・コントラクト実装・検証体系。" />
        <div className="developer-layout">
          <div>
            <ol className="steps">
              <li><span>01</span><div><strong>Prerequisites</strong><p>Node.js 22+, an approved wallet, test-only account, source control and a secrets-safe environment.</p></div></li>
              <li><span>02</span><div><strong>Network configuration</strong><p>Candidate Chain ID: <code>20260723</code>. RPC, WS, Explorer, Faucet and currency symbol: <b>Pending Verification / not publicly released</b>.</p></div></li>
              <li><span>03</span><div><strong>Contract toolchain</strong><p>Solidity/EVM compatibility, token standards and compiler targets must pass client-level tests before a deployment example is published.</p></div></li>
              <li><span>04</span><div><strong>Release evidence</strong><p>Compile, unit test, negative test, security review, testnet deployment, Explorer verification and monitoring evidence form one release packet.</p></div></li>
            </ol>
          </div>
          <div>
            <p className="code-label">Testable configuration guard</p>
            <CopyBlock code={networkSample} />
            <p className="source-note">No Solidity deployment sample is published until smart-contract compatibility and the public endpoint set are verified.</p>
          </div>
        </div>
        <Flow title="Wallet – DApp – RPC – Validator – Explorer" subtitle="接続と検証の読み順" nodes={["Wallet", "Partner DApp", "Public RPC boundary", "Validator quorum", "Explorer parity"]} gate="Public administrative, debug, mining, personal and txpool methods must remain unavailable." />
      </section>

      <section className="content-section" id="adoption">
        <SectionHeading index="08" eyebrow="Institutional Adoption Lifecycle" title="Evidence-gated progression from definition to operation." ja="定義から運用へ進む証跡基準の導入工程。" />
        <div className="process-list">
          {adoptionSteps.map(([n, title, owner, evidence, exit]) => (
            <article key={n}>
              <span>{n}</span><div><h3>{title}</h3><p>{owner}</p></div><dl><dt>Required evidence</dt><dd>{evidence}</dd><dt>Exit condition</dt><dd>{exit}</dd></dl>
            </article>
          ))}
        </div>
        <Flow title="Testnet-to-mainnet release gate" subtitle="リリース判定" nodes={["Contract candidate", "Public Testnet evidence", "Runtime acceptance", "Operational readiness", "Separate Mainnet review"]} gate="Current public-testnet runtime acceptance: BLOCKED. Mainnet remains separately blocked." />
      </section>

      <section className="content-section" id="governance">
        <SectionHeading index="09" eyebrow="Governance & Responsibility" title="Control is explicit, bounded and auditable." ja="責任主体・権限・証跡を分離し、監査可能にする。" />
        <div className="table-scroll" role="region" aria-label="Responsibility matrix" tabIndex={0}>
          <table>
            <thead><tr><th>Domain</th><th>Primary responsibility</th><th>Control focus</th><th>Evidence</th></tr></thead>
            <tbody>{responsibilities.map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <Flow title="Partner / JAIOS / network responsibility map" subtitle="責任分界" nodes={["Partner asset & legal design", "Development implementation", "JAIOS release governance", "Network operations", "Independent readback"]} />
        <div className="legal-note">
          <strong>Responsibility boundary</strong>
          <p>JAIOS Institutional Governance does not guarantee the economic value, market liquidity, legal classification or regulatory conformity of an external partner’s token, NFT or DApp.</p>
          <p lang="ja">外部パートナーが発行・運用する資産の経済価値、流動性、法的分類、規制適合性を保証するものではありません。</p>
        </div>
      </section>

      <section className="content-section" id="security">
        <SectionHeading index="10" eyebrow="Security & Risk" title="Each risk requires a control and a readable record." ja="リスク、統制、必要証跡を一体で設計する。" />
        <div className="risk-grid">
          {risks.map(([risk, control, evidence]) => <article key={risk}><h3>{risk}</h3><p>{control}</p><small>Evidence · {evidence}</small></article>)}
        </div>
        <Flow title="Security and custody architecture" subtitle="鍵・権限・運用統制" nodes={["Separated roles", "Multisig / custody", "Contract controls", "Monitoring", "Incident evidence"]} />
        <Flow title="Post-release monitoring and incident flow" subtitle="稼働後監視" nodes={["Detect", "Classify", "Contain / pause", "Evidence & decision", "Recover / migrate"]} gate="Rollback cannot erase confirmed on-chain history; migration and compensating controls must be planned." />
      </section>

      <section className="content-section" id="resources">
        <SectionHeading index="11" eyebrow="Primary References" title="Canonical implementation and standards sources." ja="実装正本と技術標準資料。" />
        <div className="resource-grid">
          <a href="https://github.com/juncaGlobal/junca-Project/pull/158" target="_blank" rel="noreferrer"><span>Current implementation</span><strong>PR #158 · Draft</strong><small>Source, release control and acceptance evidence</small></a>
          <a href="https://github.com/juncaGlobal/junca-Project" target="_blank" rel="noreferrer"><span>Repository</span><strong>juncaGlobal/junca-Project</strong><small>Canonical implementation repository</small></a>
          <a href="https://github.com/juncaGlobal/junca-Project/blob/agent/junca-social-ecosystem-chain/docs/JUNCA_SOCIAL_ECOSYSTEM_CHAIN_INTEROPERABILITY.md" target="_blank" rel="noreferrer"><span>Interoperability evidence</span><strong>Ethereum / ERC · BSC Testnet · TRON Shasta</strong><small>Route controls, state machine and release boundary</small></a>
          <a href="https://github.com/juncaGlobal/junca-Project/blob/agent/junca-social-ecosystem-chain/docs/JUNCA_SOCIAL_ECOSYSTEM_CHAIN_BRIDGE_CONTRACT.md" target="_blank" rel="noreferrer"><span>Bridge contract</span><strong>Controlled Testnet Implementation</strong><small>Solidity 0.8.24 compile and static-control evidence</small></a>
          <a href="https://ethereum.org/developers/docs/standards/" target="_blank" rel="noreferrer"><span>Ethereum standards</span><strong>ERC Technical Standards</strong><small>ERC-20, ERC-721 and application-level conventions</small></a>
          <a href="https://docs.bnbchain.org/bnb-smart-chain/" target="_blank" rel="noreferrer"><span>BNB Smart Chain</span><strong>BSC Technical Documentation</strong><small>Network and application reference</small></a>
          <a href="https://developers.tron.network/docs/token-standards-overview" target="_blank" rel="noreferrer"><span>TRON standards</span><strong>TRC Technical Standards</strong><small>TRC-20 and TRC-721 reference</small></a>
          <div><span>Network status</span><strong>Pending Deployment</strong><small>No public RPC, WS, Explorer or Faucet link is released here.</small></div>
          <div><span>SDK / API</span><strong>Pending Verification</strong><small>Publication follows tested repository availability.</small></div>
        </div>
      </section>

      <section className="content-section readiness-section" id="readiness">
        <SectionHeading index="12" eyebrow="Readiness Classification" title="Machine-readable release posture." ja="機械判定可能なリリース準備状態。" />
        <div className="readiness-head">
          <div><span>Overall result</span><strong className={`result-${readiness.toLowerCase().replace(" ", "-")}`}>{readiness}</strong></div>
          <p>Any BLOCKED item blocks release. CONDITIONAL requires recorded conditions. NOT APPLICABLE requires a reason in the partner evidence packet.</p>
        </div>
        <div className="checklist">
          {readinessItems.map((item, index) => (
            <label key={item}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{item}</strong>
              <select value={checks[item]} onChange={(e) => setChecks({ ...checks, [item]: e.target.value as Status })} aria-label={`${item} status`}>
                <option>READY</option>
                <option>CONDITIONAL</option>
                <option>BLOCKED</option>
                <option>NOT APPLICABLE</option>
              </select>
            </label>
          ))}
        </div>
      </section>

      <section className="content-section evidence-section" id="evidence">
        <SectionHeading index="13" eyebrow="Evidence Matrix" title="What is known, targeted and still blocked." ja="確定・目標・未検証・停止条件を分離する。" />
        <div className="evidence-grid">
          <article><Badge>Verified in source</Badge><h3>Control architecture</h3><p>Canonical name, institutional governance label, fail-closed release policy, candidate chain configuration and three-validator topology.</p></article>
          <article><Badge tone="gold">Target only</Badge><h3>Scale profile</h3><p>Throughput, finality, latency, availability and nine-validator production topology are targets, not public claims.</p></article>
          <article><Badge tone="gold">Pending verification</Badge><h3>Partner stack</h3><p>Smart-contract compatibility, token/NFT standards, SDK/API, wallet, compiler and verification toolchain.</p></article>
          <article><Badge>Implemented in source</Badge><h3>Ethereum / ERC, BSC & TRON control plane</h3><p>Route validation, message-state engine, simulation, replay controls and testnet bridge contract. No deployment or asset movement.</p></article>
          <article><Badge tone="block">Blocked</Badge><h3>Public release</h3><p>Custody-bound validator addresses, runtime observations, public endpoints, Explorer parity, rollback and independent readback.</p></article>
        </div>
      </section>

      <footer>
        <div>
          <strong>JUNCA Social Ecosystem Chain</strong>
          <p>Protocol Architecture, Asset Standards & Institutional Adoption Reference</p>
        </div>
        <div>
          <span>Governance</span><strong>JAIOS Institutional Governance</strong>
        </div>
        <div>
          <span>Release notice</span><strong>Public Testnet / No Monetary Value</strong>
        </div>
      </footer>
    </main>
  );
}
