import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const origin = "https://docs.jaios-governance.org";
const release = "2026.07.25";
const chainSource = "effe17badf6628b6ad5160062ca583501fe72b31";

const routes = [
  {
    path: "/",
    title: "Technical Reference",
    ja: "公式技術リファレンス",
    eyebrow: "Protocol reference · controlled publication",
    summary: "A concise entry point to the protocol architecture, asset boundaries, interoperability controls, implementation route, institutional governance and release evidence of JUNCA Social Ecosystem Chain.",
    summaryJa: "JUNCA Social Ecosystem Chainのプロトコル構造、資産境界、相互運用統制、実装経路、制度的ガバナンス、公開証跡へ接続する公式技術リファレンスです。",
    body: `
      <section class="purpose-grid" aria-labelledby="purpose-title">
        <div>
          <p class="section-label">Purpose / 目的</p>
          <h2 id="purpose-title">One reference. Clear operating boundaries.</h2>
          <p>This publication supports technical assessment and implementation planning without presenting unreleased runtime functions as operational.</p>
          <p lang="ja">未稼働機能を稼働済みと表示せず、技術評価と実装判断に必要な境界・責任・証跡を整理します。</p>
        </div>
        <dl class="status-register">
          <div><dt>Official chain</dt><dd>JUNCA Social Ecosystem Chain</dd></div>
          <div><dt>Governance</dt><dd>JAIOS Institutional Governance</dd></div>
          <div><dt>Network label</dt><dd>Public Testnet / No Monetary Value</dd></div>
          <div><dt>Source reference</dt><dd><code>${chainSource.slice(0, 12)}</code> · verified implementation</dd></div>
        </dl>
      </section>
      <section aria-labelledby="reference-map">
        <div class="section-head">
          <p class="section-label">Reference map / 技術書構成</p>
          <h2 id="reference-map">Move directly to the required layer.</h2>
        </div>
        <div class="route-grid">
          ${[
            ["Protocol", "Architecture, consensus boundary and runtime state.", "プロトコル構造と実行境界", "/protocol"],
            ["Assets", "Issuance, administration and custody boundaries.", "資産発行・管理・保管境界", "/assets"],
            ["Interoperability", "Route controls, finality and fail-closed release.", "相互運用と停止統制", "/interoperability"],
            ["Implementation", "Evidence-gated adoption and deployment route.", "証跡に基づく実装経路", "/implementation"],
            ["Governance", "Institutional roles and separation of duties.", "制度的責任と職務分離", "/governance"],
            ["Evidence", "Release gates, QA and readback requirements.", "公開ゲート・QA・Readback", "/evidence"],
            ["Glossary", "Canonical terms and publication labels.", "正本用語と公開表記", "/glossary"]
          ].map(([name, text, jaText, href], index) => `<a class="route-card" href="${href}">
            <span>0${index + 1}</span><h3>${name}</h3><p>${text}</p><small lang="ja">${jaText}</small>
          </a>`).join("")}
        </div>
      </section>
      <section class="boundary-panel" aria-labelledby="boundary-title">
        <p class="section-label">Publication boundary / 公開境界</p>
        <h2 id="boundary-title">Architecture is documented. Runtime claims remain evidence-gated.</h2>
        <div class="boundary-columns">
          <div><h3>Implemented in source</h3><p>Authenticated validator sessions, finalized fork choice, certified block-range synchronization, snapshot integrity and faulty-peer quarantine.</p></div>
          <div><h3>Not implied</h3><p>Public validator runtime acceptance, mainnet launch, monetary value, activated bridges, deployed external routes or asset movement.</p></div>
        </div>
      </section>`
  },
  {
    path: "/protocol",
    title: "Protocol Architecture",
    ja: "プロトコル・アーキテクチャ",
    eyebrow: "Layer 01 · protocol",
    summary: "The current source implements authenticated validator synchronization and certificate-bound finality while keeping public runtime claims behind an exact-environment acceptance gate.",
    summaryJa: "現行Sourceは認証済みValidator同期とCertificateに拘束されたFinalityを実装し、公開Runtimeの表明は同一環境の受入ゲート後に限定します。",
    body: `
      ${diagram("Validator synchronization trust path", [
        ["Authenticate", "Signed peer session and exact chain identity"],
        ["Observe", "Finalized status with monotonic sequence"],
        ["Certify", "Epoch-bound validator votes and strict quorum"],
        ["Synchronize", "Certified block range or verified snapshot"],
        ["Contain", "Protocol faults and peer quarantine"]
      ])}
      ${table("Protocol state model", ["Domain", "Defined architecture", "Publication state"], [
        ["Network", "Public testnet architecture", status("Evidence gated")],
        ["Validator sync", "Authenticated peer sessions and exact schemas", status("Implemented · source verified")],
        ["Finality", "Certificate reconstruction, quorum and epoch-bound validator sets", status("Implemented · source verified")],
        ["Catch-up", "Finality-anchored block ranges and snapshot integrity", status("Implemented · source verified")],
        ["Fault isolation", "Replay rejection, protocol-fault accounting and quarantine", status("Implemented · source verified")],
        ["Chain identity", "Canonical identity registry", status("Public registration pending")],
        ["RPC / Explorer", "Interface and acceptance requirements", status("Endpoint deployment pending")],
        ["Mainnet", "Separate future release domain", status("Not launched")]
      ])}
      ${callout("Current source boundary", `Implementation status is bound to source ${chainSource}. Public validator operation remains unverified until endpoint, advancing-head and multi-node acceptance evidence are read back.`, "実装状況は現行Sourceへ固定されています。公開Validator稼働は、Endpoint、Advancing Head、Multi-node受入証跡のReadback完了まで未検証です。")}`
  },
  {
    path: "/assets",
    title: "Asset Standards",
    ja: "資産標準",
    eyebrow: "Layer 02 · assets",
    summary: "Asset standards separate protocol capability from issuance authority, custody, supply policy and legal classification.",
    summaryJa: "プロトコル機能と、発行権限、保管、供給方針、法的分類を明確に分離します。",
    body: `
      ${table("Asset responsibility boundary", ["Domain", "Required control", "Current publication state"], [
        ["Fungible assets", "Supply, mint, pause and administrator policy", status("Standard defined · deployment unverified")],
        ["Non-fungible assets", "Rights, metadata integrity and administrator policy", status("Standard defined · deployment unverified")],
        ["Treasury", "Institutional custody and separation of duties", status("Required before release")],
        ["Metadata", "Integrity, retention and personal-data exclusion", status("Evidence required")],
        ["Monetary value", "Separate legal and production release decision", status("None on public testnet")]
      ])}
      <section class="three-grid" aria-label="Asset control model">
        ${card("01", "Define", "Purpose, rights, participants and lifecycle must be recorded before implementation.")}
        ${card("02", "Control", "Administrative authority, custody, limits and incident actions must be separated.")}
        ${card("03", "Evidence", "Source, tests, deployment address and explorer readback must resolve to one release.")}
      </section>
      ${callout("Mandatory label", "All test assets are treated as having no monetary value unless a separate approved release states otherwise.", "別途承認された公開判断がない限り、テスト資産に金銭的価値はありません。")}`
  },
  {
    path: "/interoperability",
    title: "Interoperability",
    ja: "相互運用",
    eyebrow: "Layer 03 · route control",
    summary: "Interoperability is a controlled release domain. Route design does not mean that an external route, bridge contract or asset transfer is active.",
    summaryJa: "相互運用は独立した公開統制領域です。経路設計は、外部Route、Bridge Contract、資産移動の稼働を意味しません。",
    body: `
      ${diagram("Message lifecycle", [
        ["Observe", "Finalized source event"],
        ["Verify", "Domain, nonce and signer quorum"],
        ["Authorize", "Limits and release gate"],
        ["Execute", "Destination action"],
        ["Reconcile", "Evidence and incident trail"]
      ])}
      ${table("External route register", ["Route", "Design boundary", "Public state"], [
        ["Ethereum / ERC", "Target compatibility and control requirements", status("Not deployed")],
        ["BSC", "Testnet adapter and route-control model", status("Route blocked")],
        ["TRON", "Shasta adapter and route-control model", status("Route blocked")],
        ["Replay protection", "Message, transaction and nonce uniqueness", status("Required")],
        ["Emergency control", "Pause, limits and incident procedure", status("Required before activation")]
      ])}
      ${callout("Fail-closed rule", "No route may be presented as active until contracts, custody, quorum, finality, limits, monitoring and rollback evidence pass the same release gate.", "Contract、保管、Quorum、Finality、上限、監視、Rollback証跡が同一公開ゲートを通過するまで、Routeを稼働済みと表示しません。")}`
  },
  {
    path: "/implementation",
    title: "Implementation",
    ja: "実装ガイド",
    eyebrow: "Layer 04 · controlled adoption",
    summary: "Implementation proceeds from use-case definition to architecture, governance, testnet evidence, security review and operational acceptance.",
    summaryJa: "用途定義から、Architecture、Governance、Testnet証跡、Security Review、運用受入へ段階的に進めます。",
    body: `
      <ol class="implementation-steps">
        ${[
          ["Scope", "Define purpose, participants, value flow and excluded functions."],
          ["Architecture", "Map on-chain, off-chain, data and integration boundaries."],
          ["Governance", "Assign administrator, custody, review and incident responsibility."],
          ["Build", "Bind source, dependencies, configuration and deterministic artifact."],
          ["Verify", "Complete tests, security review and runtime acceptance."],
          ["Release", "Record exact commit, environment, evidence and rollback point."]
        ].map(([title, text], index) => `<li><span>0${index + 1}</span><div><h2>${title}</h2><p>${text}</p></div></li>`).join("")}
      </ol>
      ${table("Minimum handoff packet", ["Evidence", "Required content", "Decision supported"], [
        ["Source", "Repository, exact commit and dependency record", "Reproducibility"],
        ["Security", "Threat model, test result and finding closure", "Technical acceptance"],
        ["Operations", "Monitoring, incident and rollback procedure", "Operational readiness"],
        ["Governance", "Role matrix and approval record", "Institutional accountability"],
        ["Runtime", "Endpoint, chain identity and advancing-head readback", "Release state"]
      ])}`
  },
  {
    path: "/governance",
    title: "Institutional Governance",
    ja: "制度的ガバナンス",
    eyebrow: "Layer 05 · accountability",
    summary: "JAIOS Institutional Governance defines protocol and release accountability while preserving separate operating, custody, implementation and independent-review responsibilities.",
    summaryJa: "JAIOS Institutional Governanceは、運用、保管、実装、独立Reviewを分離しながら、ProtocolとReleaseの組織責任を明確化します。",
    body: `
      ${table("Responsibility model", ["Domain", "Responsible function", "Required evidence"], [
        ["Protocol governance", "JAIOS Institutional Governance", "Policy and release record"],
        ["Network operations", "Authorized network operators", "Health, continuity and signer evidence"],
        ["Implementation", "Authorized development function", "Source, tests and deployment packet"],
        ["Custody", "Appointed institutional custodian", "Signer register and segregation record"],
        ["Independent review", "Review / assurance function", "Findings and closure evidence"],
        ["Incident response", "Assigned domain owners", "Containment, recovery and closure record"]
      ])}
      <section class="three-grid" aria-label="Separation of duties">
        ${card("P", "Production", "Creates source, artifact and first-line QA evidence.")}
        ${card("R", "Review", "Tests quality, security, publication boundaries and sources.")}
        ${card("D", "Deployment", "Binds the approved artifact to the production environment and records readback.")}
      </section>
      ${callout("Public representation", "Governance statements identify the responsible institution. Personal-control wording is not used in public materials.", "公開物では責任主体となる組織を表示し、個人支配を示す表現は使用しません。")}`
  },
  {
    path: "/evidence",
    title: "Evidence & Release",
    ja: "証跡・公開管理",
    eyebrow: "Layer 06 · verification",
    summary: "A release is accepted only when source, artifact, infrastructure, DNS, TLS and rendered experience resolve to the same deployment.",
    summaryJa: "Source、Artifact、Infrastructure、DNS、TLS、実表示が同一Deploymentへ一致した場合にのみ公開完了とします。",
    body: `
      ${diagram("Release evidence chain", [
        ["Commit", "Exact source SHA"],
        ["CI", "Build and policy gates"],
        ["Artifact", "Deterministic manifest"],
        ["Deployment", "S3 and CloudFront binding"],
        ["Readback", "DNS, TLS and rendered QA"]
      ])}
      ${table("Acceptance register", ["Gate", "Pass condition", "Current publication state"], [
        ["Source", `Exact chain source ${chainSource.slice(0, 12)} exists on main`, status("Verified")],
        ["Chain implementation", "Authenticated sync and certified finality tests pass", status("Verified in source")],
        ["Publication quality", "Build, metadata, font and rendered-route tests pass", status("Verified")],
        ["Infrastructure", "Caller identity, OIDC role and resource IDs read back", status("Verified")],
        ["Delivery", "Artifact matches S3 and invalidation is completed", status("Verified")],
        ["Public endpoint", "DNS, TLS and eight canonical routes pass", status("Verified")]
      ])}
      ${callout("Evidence rule", "A planned, configured or deploying state is never reported as verified production.", "計画済み、設定済み、Deploying状態をProduction Verifiedとして報告しません。")}`
  },
  {
    path: "/glossary",
    title: "Glossary",
    ja: "用語集",
    eyebrow: "Canonical language",
    summary: "Canonical terms keep architecture, runtime state and release claims precise across technical and institutional communication.",
    summaryJa: "正本用語により、Architecture、Runtime State、Release Claimを技術・制度文書間で一貫させます。",
    body: `
      <dl class="glossary">
        ${[
          ["JUNCA Social Ecosystem Chain", "The official chain name. Former names are historical references only."],
          ["JAIOS Institutional Governance", "The approved public designation for institutional protocol and release responsibility."],
          ["Public Testnet / No Monetary Value", "The mandatory network label until a separate approved release changes the state."],
          ["Target architecture", "The intended completed design. It is not evidence that a runtime function is live."],
          ["Runtime readback", "Evidence collected from the exact operating environment after deployment."],
          ["Release gate", "A controlled decision point requiring defined evidence and responsibility."],
          ["Fail-closed", "The affected action remains blocked when required identity, evidence or boundary checks fail."],
          ["Rollback point", "The exact prior source and infrastructure state to which recovery is authorized."]
        ].map(([term, definition]) => `<div><dt>${term}</dt><dd>${definition}</dd></div>`).join("")}
      </dl>
      ${callout("Language discipline", "Fact, interpretation, target state and verified runtime state remain visibly separate.", "事実、解釈、目標状態、検証済み稼働状態を明確に分離します。")}`
  }
];

function status(text) {
  return `<span class="state">${text}</span>`;
}

function card(index, title, text) {
  return `<article class="number-card"><span>${index}</span><h2>${title}</h2><p>${text}</p></article>`;
}

function callout(title, text, ja) {
  return `<aside class="callout"><p class="section-label">${title}</p><p>${text}</p><p lang="ja">${ja}</p></aside>`;
}

function diagram(title, nodes) {
  return `<figure class="architecture">
    <figcaption><p class="section-label">Architecture / アーキテクチャ</p><h2>${title}</h2></figcaption>
    <div class="architecture-flow">${nodes.map(([name, text], index) => `<div class="architecture-node">
      <span>0${index + 1}</span><div><h3>${name}</h3><p>${text}</p></div>
    </div>`).join("")}</div>
  </figure>`;
}

function table(title, headers, rows) {
  return `<section class="table-section"><div class="section-head"><p class="section-label">Reference register</p><h2>${title}</h2></div>
    <div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th scope="col">${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((cell, index) => index === 0 ? `<th scope="row">${cell}</th>` : `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
  </section>`;
}

function navigation(activePath) {
  return routes.map((route) => `<a href="${route.path}"${route.path === activePath ? ` aria-current="page"` : ""}>${route.path === "/" ? "Overview" : route.title.split(" ")[0]}</a>`).join("");
}

function template(route) {
  const canonical = `${origin}${route.path === "/" ? "/" : route.path}`;
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${route.title} | JUNCA Social Ecosystem Chain</title>
  <meta name="description" content="${route.summary}">
  <meta name="theme-color" content="#f4f1e9">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <link rel="canonical" href="${canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="JUNCA Social Ecosystem Chain Technical Reference">
  <meta property="og:title" content="${route.title} | JUNCA Social Ecosystem Chain">
  <meta property="og:description" content="${route.summary}">
  <meta property="og:url" content="${canonical}">
  <meta property="og:image" content="${origin}/assets/og-reference.svg">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/assets/styles.css">
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <a class="identity" href="/" aria-label="JUNCA Social Ecosystem Chain technical reference home">
      <span>JUNCA</span><small>Social Ecosystem Chain</small>
    </a>
    <nav aria-label="Primary navigation">${navigation(route.path)}</nav>
    <div class="network-label">Public Testnet<br><small>No Monetary Value</small></div>
  </header>
  <main id="main">
    <header class="page-intro${route.path === "/" ? " home-intro" : ""}">
      <div class="edition"><span>Technical Reference</span><span>Release ${release}</span></div>
      <p class="eyebrow">${route.eyebrow}</p>
      <h1>${route.title}</h1>
      <p class="title-ja" lang="ja">${route.ja}</p>
      <div class="lead-grid"><p>${route.summary}</p><p lang="ja">${route.summaryJa}</p></div>
    </header>
    <div class="content-shell">${route.body}</div>
  </main>
  <footer>
    <div><strong>JUNCA Social Ecosystem Chain</strong><span>Official Technical Reference</span></div>
    <div><span>Governance</span><strong>JAIOS Institutional Governance</strong></div>
    <div><span>Publication boundary</span><strong>Architecture and operating model</strong></div>
  </footer>
</body>
</html>`;
}

await rm(dist, { recursive: true, force: true });
await mkdir(join(dist, "assets"), { recursive: true });
for (const asset of ["styles.css", "favicon.svg", "og-reference.svg"]) {
  await cp(join(root, "src", asset), join(dist, "assets", asset));
}
for (const route of routes) {
  const directory = route.path === "/" ? dist : join(dist, route.path.slice(1));
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, "index.html"), template(route), "utf8");
}
await writeFile(join(dist, "404.html"), template({
  path: "/404",
  title: "Reference Not Found",
  ja: "指定された技術リファレンスは見つかりません",
  eyebrow: "HTTP 404",
  summary: "The requested technical reference does not exist at this address.",
  summaryJa: "指定されたURLに技術リファレンスは存在しません。",
  body: `<section class="not-found"><h2>Return to the reference map.</h2><p><a class="text-link" href="/">Open Technical Reference</a></p></section>`
}), "utf8");
await writeFile(join(dist, "sitemap.xml"), `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${routes.map((route) => `  <url><loc>${origin}${route.path === "/" ? "/" : route.path}</loc></url>`).join("\n")}
</urlset>
`, "utf8");
await writeFile(join(dist, "robots.txt"), `User-agent: *\nAllow: /\nSitemap: ${origin}/sitemap.xml\n`, "utf8");

const manifestFiles = [];
for (const path of [
  ...routes.map((route) => route.path === "/" ? "index.html" : `${route.path.slice(1)}/index.html`),
  "404.html", "robots.txt", "sitemap.xml", "assets/styles.css", "assets/favicon.svg", "assets/og-reference.svg"
]) {
  const data = await readFile(join(dist, path));
  manifestFiles.push({ path, bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") });
}
await writeFile(join(dist, "release-manifest.json"), `${JSON.stringify({
  schema: "junca-chain-docs-release/v1",
  release,
  canonical_origin: origin,
  network_label: "Public Testnet / No Monetary Value",
  governance: "JAIOS Institutional Governance",
  chain_source_commit: chainSource,
  routes: routes.map(({ path }) => path),
  files: manifestFiles
}, null, 2)}\n`, "utf8");

console.log(`Built ${routes.length} canonical routes into ${dist}`);
