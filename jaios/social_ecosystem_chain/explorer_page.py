"""Self-contained public-testnet explorer document."""

from __future__ import annotations


EXPLORER_DOCUMENT = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#071827">
  <meta name="description" content="Finalized-only public explorer for the JUNCA Social Ecosystem Chain Public Testnet.">
  <link rel="canonical" href="https://scan.jaios-governance.org/">
  <title>JUNCA Social Ecosystem Chain — Public Testnet Explorer</title>
  <style>
    :root {
      color-scheme: dark;
      --ink: #f3efe6;
      --muted: #9da9b2;
      --quiet: #6f7c86;
      --navy: #071827;
      --navy-2: #0b2236;
      --navy-3: #102b43;
      --line: rgba(222, 201, 151, .24);
      --line-soft: rgba(255, 255, 255, .08);
      --gold: #dec997;
      --gold-deep: #a98e59;
      --green: #84c6a1;
      --amber: #d6b86c;
      --red: #d5968e;
      --radius: 14px;
      --sans: Inter, "Helvetica Neue", Arial, sans-serif;
      --editorial: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      --wordmark: "Optima LT Std", Optima, "URW Classico", serif;
    }
    * { box-sizing: border-box; }
    html { background: var(--navy); scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(180deg, rgba(255,255,255,.025), transparent 28rem),
        var(--navy);
      font-family: var(--sans);
      font-size: 15px;
      line-height: 1.5;
    }
    a { color: inherit; text-decoration: none; }
    button, input { font: inherit; }
    .shell { width: min(1480px, calc(100% - 40px)); margin: 0 auto; }
    .site-header {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line-soft);
      background: rgba(7, 24, 39, .94);
      backdrop-filter: blur(18px);
    }
    .header-row {
      min-height: 72px;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto;
      gap: 28px;
      align-items: center;
    }
    .identity { min-width: 0; display: flex; align-items: center; gap: 16px; }
    .identity-logo {
      display: block;
      width: 188px;
      height: auto;
      flex: 0 0 auto;
    }
    .identity-copy { min-width: 0; }
    .wordmark {
      font-family: var(--wordmark);
      font-weight: 700;
      letter-spacing: .02em;
      font-size: 18px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .identity small {
      display: block;
      color: var(--muted);
      font-size: 10px;
      letter-spacing: .18em;
      text-transform: uppercase;
    }
    nav { display: flex; gap: 8px; align-items: center; }
    nav a {
      padding: 9px 12px;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    nav a:hover, nav a:focus-visible { color: var(--gold); }
    .status-band {
      border-bottom: 1px solid var(--line-soft);
      background: #091d2f;
    }
    .status-row {
      min-height: 38px;
      display: flex;
      gap: 22px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      display: inline-block;
      margin-right: 7px;
      border-radius: 50%;
      background: var(--amber);
    }
    .status-dot.ready { background: var(--green); }
    .notice { color: var(--gold); }
    main { padding: 34px 0 76px; }
    .eyebrow {
      margin: 0 0 9px;
      color: var(--gold);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .18em;
      text-transform: uppercase;
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 {
      max-width: 900px;
      margin-bottom: 12px;
      font-family: var(--wordmark);
      font-size: clamp(34px, 5vw, 66px);
      line-height: 1.02;
      letter-spacing: -.025em;
    }
    h2 {
      margin-bottom: 4px;
      font-family: var(--editorial);
      font-size: 25px;
      letter-spacing: -.01em;
    }
    h3 {
      margin-bottom: 4px;
      font-size: 13px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .lede {
      max-width: 790px;
      color: var(--muted);
      font-size: 16px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(300px, .8fr);
      gap: 28px;
      align-items: end;
      padding: 34px 0 28px;
    }
    .search-panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(16, 43, 67, .58);
      padding: 19px;
    }
    .search-panel label {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .search-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .search-row input {
      min-width: 0;
      height: 45px;
      padding: 0 14px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      color: var(--quiet);
      background: #081a2a;
    }
    .search-row button {
      height: 45px;
      padding: 0 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--quiet);
      background: transparent;
      cursor: not-allowed;
    }
    .search-note { margin: 10px 0 0; color: var(--quiet); font-size: 11px; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 14px 0 30px;
    }
    .metric, .panel {
      border: 1px solid var(--line-soft);
      border-radius: var(--radius);
      background: rgba(11, 34, 54, .82);
    }
    .metric { min-height: 126px; padding: 19px; }
    .metric-label {
      display: block;
      margin-bottom: 20px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .metric-value {
      display: block;
      overflow: hidden;
      font-family: var(--editorial);
      font-size: clamp(24px, 2.8vw, 38px);
      line-height: 1.05;
      text-overflow: ellipsis;
    }
    .metric-sub { display: block; margin-top: 7px; color: var(--quiet); font-size: 11px; }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin: 34px 0 13px;
    }
    .section-head p { margin: 0; color: var(--muted); font-size: 12px; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .panel { padding: 22px; min-width: 0; }
    .data-list { margin: 18px 0 0; }
    .data-row {
      display: grid;
      grid-template-columns: minmax(150px, .7fr) minmax(0, 1.3fr);
      gap: 18px;
      align-items: start;
      padding: 13px 0;
      border-top: 1px solid var(--line-soft);
    }
    .data-row dt { color: var(--muted); font-size: 12px; }
    .data-row dd { margin: 0; min-width: 0; text-align: right; }
    code, .mono {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 25px;
      padding: 3px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--gold);
      font-size: 10px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .boundary-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .boundary {
      padding: 17px;
      border-top: 1px solid var(--line);
      background: rgba(11, 34, 54, .58);
    }
    .boundary span { display: block; color: var(--muted); font-size: 10px; text-transform: uppercase; }
    .boundary strong { display: block; margin-top: 6px; color: var(--ink); font-size: 13px; }
    .unavailable-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .unavailable {
      min-height: 96px;
      padding: 16px;
      border: 1px solid var(--line-soft);
      border-radius: 10px;
      background: rgba(8, 26, 42, .62);
    }
    .unavailable span { display: block; margin-top: 14px; color: var(--quiet); font-size: 11px; }
    .evidence-links { display: grid; gap: 9px; margin-top: 16px; }
    .evidence-links a {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 0;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
    }
    .evidence-links a:hover, .evidence-links a:focus-visible { color: var(--gold); }
    .footnote {
      max-width: 980px;
      margin: 38px 0 0;
      padding-left: 16px;
      border-left: 1px solid var(--gold-deep);
      color: var(--muted);
    }
    footer {
      border-top: 1px solid var(--line-soft);
      padding: 28px 0 40px;
      color: var(--quiet);
      font-size: 11px;
    }
    .footer-row { display: flex; justify-content: space-between; gap: 22px; flex-wrap: wrap; }
    .footer-links { display: flex; gap: 18px; flex-wrap: wrap; }
    .footer-links a:hover, .footer-links a:focus-visible { color: var(--gold); }
    .skeleton { color: var(--quiet); }
    .error { color: var(--red); }
    @media (max-width: 1040px) {
      .metric-grid, .boundary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .unavailable-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .shell { width: min(100% - 24px, 1480px); }
      .header-row { grid-template-columns: 1fr; gap: 8px; padding: 14px 0; }
      .identity-logo { width: 150px; }
      nav { overflow-x: auto; padding-bottom: 3px; }
      nav a { padding-left: 0; padding-right: 18px; white-space: nowrap; }
      .hero, .two-col { grid-template-columns: 1fr; }
      .hero { padding-top: 26px; }
      .metric-grid, .boundary-grid, .unavailable-grid { grid-template-columns: 1fr 1fr; }
      .data-row { grid-template-columns: 1fr; gap: 5px; }
      .data-row dd { text-align: left; }
    }
    @media (max-width: 480px) {
      .metric-grid, .boundary-grid, .unavailable-grid { grid-template-columns: 1fr; }
      .wordmark { font-size: 15px; }
      h1 { font-size: 37px; }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
    }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="shell header-row">
      <a class="identity" href="/" aria-label="JUNCA Social Ecosystem Chain Explorer home">
        <img class="identity-logo" src="/junca-chain-logo.png" width="900" height="271" alt="JUNCA">
        <span class="identity-copy">
          <span class="wordmark">Social Ecosystem Chain</span>
          <small>Public Testnet Explorer</small>
        </span>
      </a>
      <nav aria-label="Primary">
        <a href="#network">Network</a>
        <a href="#finality">Finality</a>
        <a href="#block">Latest Block</a>
        <a href="#evidence">Evidence</a>
      </nav>
    </div>
  </header>

  <div class="status-band">
    <div class="shell status-row">
      <span><i id="status-dot" class="status-dot" aria-hidden="true"></i><span id="network-status">Connecting</span></span>
      <span>Finalized-only</span>
      <span>Read-only</span>
      <span class="notice">Public Testnet / No Monetary Value</span>
    </div>
  </div>

  <main class="shell">
    <section class="hero" aria-labelledby="page-title">
      <div>
        <p class="eyebrow">Network observation / ネットワーク観測</p>
        <h1 id="page-title">Public Testnet Explorer</h1>
        <p class="lede">Finalized network state, quorum evidence and the latest publicly readable block. Values are read from the live public gateway and are not embedded in this page.</p>
      </div>
      <div class="search-panel">
        <label for="search">Block / Transaction / Address</label>
        <div class="search-row">
          <input id="search" type="search" value="" placeholder="Search will become available with the indexer" disabled>
          <button type="button" disabled>Search</button>
        </div>
        <p class="search-note">Not Available Yet — history indexer and general transaction access are not active.</p>
      </div>
    </section>

    <section id="network" aria-labelledby="network-title">
      <div class="section-head">
        <div><p class="eyebrow">Live overview</p><h2 id="network-title">Network Overview</h2></div>
        <p id="updated-at">Last updated —</p>
      </div>
      <div class="metric-grid">
        <article class="metric"><span class="metric-label">Finalized Height</span><strong id="height" class="metric-value skeleton">—</strong><span class="metric-sub">Latest certified block</span></article>
        <article class="metric"><span class="metric-label">Quorum</span><strong id="quorum" class="metric-value skeleton">—</strong><span class="metric-sub">Signed power / total power</span></article>
        <article class="metric"><span class="metric-label">Transactions</span><strong id="transactions" class="metric-value skeleton">—</strong><span class="metric-sub">Latest finalized block</span></article>
        <article class="metric"><span class="metric-label">Peer Count</span><strong id="peers" class="metric-value skeleton">—</strong><span class="metric-sub">Public RPC observation</span></article>
      </div>

      <div class="two-col">
        <article class="panel">
          <p class="eyebrow">Network identity</p>
          <h2>Public Testnet</h2>
          <dl class="data-list">
            <div class="data-row"><dt>Network</dt><dd>JUNCA Social Ecosystem Chain</dd></div>
            <div class="data-row"><dt>Chain ID</dt><dd><code id="chain-id">—</code></dd></div>
            <div class="data-row"><dt>Client</dt><dd><code id="client-version">—</code></dd></div>
            <div class="data-row"><dt>Access</dt><dd><span class="pill">Read-only</span></dd></div>
            <div class="data-row"><dt>RPC</dt><dd><a class="mono" href="https://rpc.jaios-governance.org/">rpc.jaios-governance.org</a></dd></div>
            <div class="data-row"><dt>Health</dt><dd><a class="mono" href="https://health.jaios-governance.org/health">health.jaios-governance.org/health</a></dd></div>
          </dl>
        </article>

        <article id="finality" class="panel">
          <p class="eyebrow">Consensus evidence</p>
          <h2>Finality Overview</h2>
          <dl class="data-list">
            <div class="data-row"><dt>Status</dt><dd id="finality-status">—</dd></div>
            <div class="data-row"><dt>Finalized Height</dt><dd><code id="finality-height">—</code></dd></div>
            <div class="data-row"><dt>Block Hash</dt><dd><code id="finality-hash">—</code></dd></div>
            <div class="data-row"><dt>Certificate Hash</dt><dd><code id="certificate-hash">—</code></dd></div>
            <div class="data-row"><dt>Signed Power</dt><dd id="signed-power">—</dd></div>
            <div class="data-row"><dt>Total Power</dt><dd id="total-power">—</dd></div>
          </dl>
        </article>
      </div>
    </section>

    <section id="block" aria-labelledby="block-title">
      <div class="section-head">
        <div><p class="eyebrow">Canonical readback</p><h2 id="block-title">Latest Finalized Block</h2></div>
        <p>Dynamic JSON-RPC response</p>
      </div>
      <article class="panel">
        <dl class="data-list">
          <div class="data-row"><dt>Block Number</dt><dd><code id="block-number">—</code></dd></div>
          <div class="data-row"><dt>Block Hash</dt><dd><code id="block-hash">—</code></dd></div>
          <div class="data-row"><dt>Parent Hash</dt><dd><code id="parent-hash">—</code></dd></div>
          <div class="data-row"><dt>State Root</dt><dd><code id="state-root">—</code></dd></div>
          <div class="data-row"><dt>Timestamp</dt><dd id="block-time">—</dd></div>
          <div class="data-row"><dt>Transaction Count</dt><dd id="block-transactions">—</dd></div>
        </dl>
      </article>
    </section>

    <section aria-labelledby="boundary-title">
      <div class="section-head">
        <div><p class="eyebrow">Explicit release boundary</p><h2 id="boundary-title">Network Boundary</h2></div>
      </div>
      <div class="boundary-grid">
        <div class="boundary"><span>Mainnet Status</span><strong>Not Active</strong></div>
        <div class="boundary"><span>Asset Movement</span><strong>Not Active</strong></div>
        <div class="boundary"><span>Bridge</span><strong>Not Active</strong></div>
        <div class="boundary"><span>Public Access</span><strong>Read-only</strong></div>
        <div class="boundary"><span>Monetary Value</span><strong>None</strong></div>
      </div>
      <p class="footnote">JUNCA Social Ecosystem Chain Public Testnet is a test environment for validating the protocol, validator topology, finality, and public read-only access. Mainnet, asset movement, and bridge functionality are not active.<br>本Public Testnetは、プロトコル、Validator構成、Finalityおよび公開読取経路の検証を目的とするテスト環境です。</p>
    </section>

    <section aria-labelledby="future-title">
      <div class="section-head">
        <div><p class="eyebrow">Progressive disclosure</p><h2 id="future-title">Planned Data Surfaces</h2></div>
        <p>Unavailable fields are not inferred or shown as zero.</p>
      </div>
      <div class="unavailable-grid">
        <article class="unavailable"><h3>Transactions</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Addresses</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Tokens</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Contracts</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Gas &amp; TPS</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Accounts</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Validators &amp; Staking</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Governance</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Faucet</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Wallet Connection</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Bridge History</h3><span>Not Available Yet</span></article>
        <article class="unavailable"><h3>Market Data</h3><span>Not Available Yet</span></article>
      </div>
    </section>

    <section id="evidence" aria-labelledby="evidence-title">
      <div class="section-head">
        <div><p class="eyebrow">Release provenance</p><h2 id="evidence-title">Evidence</h2></div>
      </div>
      <div class="two-col">
        <article class="panel">
          <h3>Runtime artifacts</h3>
          <dl class="data-list">
            <div class="data-row"><dt>Validator Count</dt><dd>3</dd></div>
            <div class="data-row"><dt>Genesis SHA-256</dt><dd><code>285f1aa2610ec98fba598aa3c8e721b54daeeddf2047b7f809f57c63db98dc95</code></dd></div>
            <div class="data-row"><dt>Node Artifact SHA-256</dt><dd><code>f1cfb7bf2ca1186bde3613b66db254a13c49f1117d676397e43b756c58f66dc0</code></dd></div>
            <div class="data-row"><dt>Runtime Source Commit</dt><dd><code>20057fbbf55528d2a8d14134fd8302067575fe75</code></dd></div>
            <div class="data-row"><dt>Release Artifact Digest</dt><dd><code>sha256:2ec95166958fafdac81c07d92044e6560779961975b08453d4ef321c08975d68</code></dd></div>
          </dl>
        </article>
        <article class="panel">
          <h3>Public records</h3>
          <div class="evidence-links">
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30239491148"><span>Public Testnet Release</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30239469442"><span>IAM Recovery</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30237527940"><span>Runtime Foundation</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain"><span>Canonical Repository</span><span>↗</span></a>
            <a href="https://docs.jaios-governance.org/"><span>Technical Reference</span><span>↗</span></a>
            <a href="https://chain.jaios-governance.org/"><span>Chain Overview</span><span>↗</span></a>
          </div>
        </article>
      </div>
    </section>
  </main>

  <footer>
    <div class="shell footer-row">
      <span>Issued and operated by JAIOS Institutional Governance</span>
      <span class="footer-links"><a href="/explorer.json">Explorer JSON</a><a href="https://health.jaios-governance.org/health">Health</a><a href="https://docs.jaios-governance.org/">Documentation</a></span>
    </div>
  </footer>

  <script>
    (() => {
      "use strict";
      const byId = (id) => document.getElementById(id);
      const set = (id, value, className) => {
        const node = byId(id);
        node.textContent = value ?? "Not Available Yet";
        node.classList.remove("skeleton", "error");
        if (className) node.classList.add(className);
      };
      const rpc = async (method, params = []) => {
        const response = await fetch("/", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({jsonrpc: "2.0", id: method, method, params}),
          cache: "no-store"
        });
        if (!response.ok) throw new Error(`${method} unavailable`);
        const data = await response.json();
        if (data.error || !Object.prototype.hasOwnProperty.call(data, "result")) {
          throw new Error(`${method} unavailable`);
        }
        return data.result;
      };
      const decimal = (hex) => Number.parseInt(hex, 16).toString(10);
      const blockTimestamp = (value) => {
        if (typeof value !== "string") return "Not Available Yet";
        const date = new Date(Number.parseInt(value, 16) * 1000);
        return Number.isNaN(date.valueOf()) ? "Not Available Yet" : date.toISOString();
      };
      const load = async () => {
        try {
          const explorerResponse = await fetch("/explorer.json", {cache: "no-store"});
          if (!explorerResponse.ok) throw new Error("Explorer data unavailable");
          const explorer = await explorerResponse.json();
          const head = explorer.head;
          if (!head || explorer.finalized_only !== true) throw new Error("Finalized data unavailable");
          set("network-status", explorer.status);
          byId("status-dot").classList.toggle("ready", explorer.status === "ready");
          set("height", String(head.height));
          set("quorum", `${head.signed_power} / ${head.total_power}`);
          set("finality-status", explorer.finalized_only ? "Finalized-only" : "Unavailable", "pill");
          set("finality-height", String(head.height));
          set("finality-hash", head.hash);
          set("certificate-hash", head.certificate_hash);
          set("signed-power", String(head.signed_power));
          set("total-power", String(head.total_power));

          const [chainId, peerCount, client, block] = await Promise.all([
            rpc("eth_chainId"),
            rpc("net_peerCount"),
            rpc("web3_clientVersion"),
            rpc("eth_getBlockByNumber", ["latest", false])
          ]);
          set("chain-id", `${decimal(chainId)} (${chainId})`);
          set("peers", decimal(peerCount));
          set("client-version", client);
          set("block-number", block?.number ? `${decimal(block.number)} (${block.number})` : "Not Available Yet");
          set("block-hash", block?.hash);
          set("parent-hash", block?.parentHash);
          set("state-root", block?.stateRoot);
          set("block-time", blockTimestamp(block?.timestamp));
          const count = Array.isArray(block?.transactions) ? block.transactions.length : "Not Available Yet";
          set("transactions", String(count));
          set("block-transactions", String(count));
          set("updated-at", `Last updated ${new Date().toISOString()}`);
        } catch (error) {
          set("network-status", "Data unavailable", "error");
          byId("status-dot").classList.remove("ready");
          ["height", "quorum", "transactions", "peers"].forEach((id) => set(id, "—", "error"));
          set("updated-at", "Live readback unavailable", "error");
        }
      };
      load();
      window.setInterval(load, 30000);
    })();
  </script>
</body>
</html>
"""
