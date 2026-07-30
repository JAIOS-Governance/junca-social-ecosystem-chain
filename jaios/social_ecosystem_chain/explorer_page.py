"""Self-contained public-testnet explorer document."""

from __future__ import annotations


EXPLORER_DOCUMENT = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#071827">\n  <meta name="application-name" content="JUNCA Explorer">\n  <meta name="apple-mobile-web-app-capable" content="yes">\n  <meta name="apple-mobile-web-app-title" content="JUNCA Explorer">
  <meta name="description" content="Finalized-only public explorer for the JUNCA Social Ecosystem Chain Public Testnet.">
  <link rel="icon" type="image/png" href="/explorer-icon.png">
  <link rel="apple-touch-icon" href="/explorer-icon.png">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="canonical" href="https://explorer.jaios-governance.org/">
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
      --cyan: #65b9c7;
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
        radial-gradient(circle at 78% 4%, rgba(36, 101, 132, .18), transparent 29rem),
        radial-gradient(circle at 12% 18%, rgba(198, 169, 107, .08), transparent 25rem),
        linear-gradient(180deg, rgba(255,255,255,.025), transparent 34rem),
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
      border-bottom: 1px solid rgba(222, 201, 151, .16);
      background: rgba(7, 24, 39, .94);
      backdrop-filter: blur(18px);
    }
    .header-row {
      min-height: 78px;
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
      padding: 9px 13px;
      border: 1px solid transparent;
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    nav a:hover, nav a:focus-visible {
      border-color: var(--line);
      color: var(--gold);
      background: rgba(255,255,255,.035);
      outline: none;
    }
    .status-band {
      border-bottom: 1px solid var(--line-soft);
      background: linear-gradient(90deg, #091d2f, #0a2236 55%, #091d2f);
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
    .status-dot.live {
      box-shadow: 0 0 0 0 rgba(132, 198, 161, .58);
      animation: live-pulse 1.8s ease-out infinite;
    }
    @keyframes live-pulse {
      0% { box-shadow: 0 0 0 0 rgba(132, 198, 161, .58); }
      70%, 100% { box-shadow: 0 0 0 8px rgba(132, 198, 161, 0); }
    }
    .notice { color: var(--gold); }
    main { padding: 30px 0 82px; }
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
      min-height: 300px;
      padding: 38px 0 34px;
      border-bottom: 1px solid var(--line-soft);
    }
    .search-panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: linear-gradient(145deg, rgba(19, 51, 77, .88), rgba(8, 26, 42, .84));
      box-shadow: 0 22px 60px rgba(0, 0, 0, .18);
      padding: 22px;
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
      background: linear-gradient(150deg, rgba(16, 43, 67, .86), rgba(8, 26, 42, .88));
      box-shadow: 0 16px 42px rgba(0, 0, 0, .12);
    }
    .metric { position: relative; min-height: 132px; overflow: hidden; padding: 20px; }
    .metric::before {
      position: absolute;
      inset: 0 auto auto 0;
      width: 100%;
      height: 2px;
      background: linear-gradient(90deg, var(--gold), rgba(222,201,151,0));
      content: "";
    }
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
    .operations-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 30px;
    }
    .operation {
      min-height: 94px;
      padding: 15px 16px;
      border-top: 1px solid var(--line);
      background: linear-gradient(150deg, rgba(11, 34, 54, .76), rgba(8, 26, 42, .66));
    }
    .operation span {
      display: block;
      color: var(--muted);
      font-size: 10px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .operation strong {
      display: block;
      margin-top: 9px;
      color: var(--ink);
      font-size: 14px;
    }
    .operation small { display: block; margin-top: 4px; color: var(--quiet); font-size: 10px; }
    .operation strong.good { color: var(--green); }
    .operation strong.warn { color: var(--amber); }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin: 38px 0 14px;
    }
    .section-head p { margin: 0; color: var(--muted); font-size: 12px; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .panel { padding: 24px; min-width: 0; }
    .data-list { margin: 18px 0 0; }
    .data-row {
      display: grid;
      grid-template-columns: minmax(150px, .7fr) minmax(0, 1.3fr);
      gap: 18px;
      align-items: start;
      padding: 14px 0;
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
      background: linear-gradient(150deg, rgba(11, 34, 54, .72), rgba(8, 26, 42, .64));
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
      opacity: .88;
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
      padding: 32px 0 40px;
      color: var(--quiet);
      font-size: 11px;
    }
    .footer-destinations {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 26px;
    }
    .footer-destination {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: center;
      min-height: 112px;
      padding: 20px 22px;
      border: 1px solid var(--line-soft);
      border-radius: var(--radius);
      color: inherit;
      background: rgba(11, 34, 54, .58);
      transition: border-color .2s ease, background .2s ease, transform .2s ease;
    }
    .footer-destination:hover, .footer-destination:focus-visible {
      border-color: var(--gold);
      background: rgba(16, 43, 67, .8);
      transform: translateY(-2px);
      outline: none;
    }
    .footer-destination span { min-width: 0; }
    .footer-destination small {
      display: block;
      margin-bottom: 7px;
      color: var(--gold);
      font-size: 9px;
      letter-spacing: .15em;
      text-transform: uppercase;
    }
    .footer-destination strong {
      display: block;
      color: var(--ink);
      font-size: 15px;
      line-height: 1.35;
    }
    .footer-destination em {
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 10px;
      font-style: normal;
    }
    .footer-destination b { color: var(--gold); font-size: 20px; font-weight: 400; }
    .footer-row { display: flex; justify-content: space-between; gap: 22px; flex-wrap: wrap; }
    .footer-links { display: flex; gap: 18px; flex-wrap: wrap; }
    .footer-links a:hover, .footer-links a:focus-visible { color: var(--gold); }
    .skeleton { color: var(--quiet); }
    .review { color: var(--amber); }
    @media (max-width: 1040px) {
      .metric-grid, .boundary-grid, .operations-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .unavailable-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .shell { width: min(100% - 24px, 1480px); }
      .header-row { grid-template-columns: 1fr; gap: 8px; padding: 14px 0; }
      .identity-logo { width: 150px; }
      nav { overflow-x: auto; padding-bottom: 3px; }
      nav a { padding-left: 0; padding-right: 18px; white-space: nowrap; }
      .hero, .two-col { grid-template-columns: 1fr; }
      .footer-destinations { grid-template-columns: 1fr; }
      .hero { min-height: 0; padding-top: 26px; }
      .metric-grid, .boundary-grid, .unavailable-grid, .operations-grid { grid-template-columns: 1fr 1fr; }
      .data-row { grid-template-columns: 1fr; gap: 5px; }
      .data-row dd { text-align: left; }
    }
    @media (max-width: 480px) {
      .metric-grid, .boundary-grid, .unavailable-grid, .operations-grid { grid-template-columns: 1fr; }
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
        <a href="#development">Development</a>
        <a href="#evidence">Evidence</a>
      </nav>
    </div>
  </header>

  <div class="status-band">
    <div class="shell status-row">
      <span><i id="status-dot" class="status-dot" aria-hidden="true"></i><span id="network-status">Verification in progress</span></span>
      <span id="live-mode">Readback starting</span>
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
        <p class="search-note">NOT YET PUBLISHED — history indexer and general transaction access are outside the current public evidence surface.</p>
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

      <div class="section-head">
        <div><p class="eyebrow">Continuous observation</p><h2>Live Operations Monitor</h2></div>
        <p>Automatic public readback every 5 seconds</p>
      </div>
      <div class="operations-grid" aria-live="polite">
        <div class="operation"><span>Gateway</span><strong id="gateway-state">Verification in progress</strong><small id="gateway-latency">Readback starting</small></div>
        <div class="operation"><span>Finality</span><strong id="finality-live">Verification in progress</strong><small>Certificate-backed</small></div>
        <div class="operation"><span>Head Movement</span><strong id="head-movement">Observation starting</strong><small id="head-age">Age evidence starting</small></div>
        <div class="operation"><span>Successful Samples</span><strong id="sample-count">0</strong><small id="failure-count">Readbacks retained 0</small></div>
        <div class="operation"><span>Next Readback</span><strong id="next-readback">5s</strong><small id="last-success">Last success —</small></div>
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
        <p>Fields not currently published are not inferred or shown as zero.</p>
      </div>
      <div class="unavailable-grid">
        <article class="unavailable"><h3>Transactions</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Addresses</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Tokens</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Contracts</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Gas &amp; TPS</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Accounts</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Validators &amp; Staking</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Governance</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Faucet</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Wallet Connection</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Bridge History</h3><span>NOT YET PUBLISHED</span></article>
        <article class="unavailable"><h3>Market Data</h3><span>NOT YET PUBLISHED</span></article>
      </div>
    </section>

    <section id="development" aria-labelledby="development-title">
      <div class="section-head">
        <div><p class="eyebrow">Governed development continuity</p><h2 id="development-title">JSEC Development Evidence</h2></div>
        <p>Development evidence remains separate from live runtime activation.</p>
      </div>
      <div class="two-col">
        <article class="panel">
          <h3>Canonical persistent panel</h3>
          <p class="footnote">Current local development checkpoints, cross-cell integration results and the exact local-versus-remote publication boundary are maintained in one continuously updated governance record.</p>
          <div class="evidence-links">
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/issues/218#issuecomment-5127105621"><span>JSEC Live Development Status</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/303"><span>Recovery PR #303 · Remote Evidence</span><span>↗</span></a>
          </div>
        </article>
        <article class="panel">
          <h3>Evidence boundary</h3>
          <dl class="data-list">
            <div class="data-row"><dt>Live Runtime</dt><dd><span class="pill">Explorer JSON</span></dd></div>
            <div class="data-row"><dt>Development Checkpoints</dt><dd><span class="pill">Local Evidence Only</span></dd></div>
            <div class="data-row"><dt>Remote Publication</dt><dd><span class="pill">PR #303 Exact Head</span></dd></div>
            <div class="data-row"><dt>Operational Recovery</dt><dd><span class="pill">Verification in Progress</span></dd></div>
          </dl>
          <div class="evidence-links">
            <a href="https://chain.jaios-governance.org/api/operational"><span>Chain Operational API</span><span>↗</span></a>
            <a href="https://chain.jaios-governance.org/evidence"><span>Chain Evidence View</span><span>↗</span></a>
          </div>
        </article>
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
            <div class="data-row"><dt>Genesis SHA-256</dt><dd><code id="genesis-sha256">—</code></dd></div>
            <div class="data-row"><dt>Node Artifact SHA-256</dt><dd><code id="node-artifact-sha256">—</code></dd></div>
            <div class="data-row"><dt>Runtime Source Commit</dt><dd><code id="runtime-source-commit">—</code></dd></div>
          </dl>
        </article>
        <article class="panel">
          <h3>Public records</h3>
          <div class="evidence-links">
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30239491148"><span>Public Testnet Release</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30239469442"><span>IAM Recovery</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30237527940"><span>Runtime Foundation</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain"><span>Canonical Repository</span><span>↗</span></a>
            <a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/issues/218#issuecomment-5127105621"><span>JSEC Development Evidence</span><span>↗</span></a>
            <a href="https://chain.jaios-governance.org/api/operational"><span>Chain Operational API</span><span>↗</span></a>
            <a href="https://docs.jaios-governance.org/"><span>Technical Reference</span><span>↗</span></a>
            <a href="https://chain.jaios-governance.org/"><span>Chain Overview</span><span>↗</span></a>
          </div>
        </article>
      </div>
    </section>
  </main>

  <footer>
    <div class="shell">
      <div class="footer-destinations" aria-label="Official destinations">
        <a class="footer-destination" href="https://jaios-governance.org/" aria-label="Open the JAIOS Institutional Governance official website">
          <span><small>Governance</small><strong>JAIOS Institutional Governance</strong><em>Official institutional website</em></span><b aria-hidden="true">↗</b>
        </a>
        <a class="footer-destination" href="https://chain.jaios-governance.org/" aria-label="Open the JUNCA Social Ecosystem Chain official website">
          <span><small>Chain Overview</small><strong>JUNCA Social Ecosystem Chain</strong><em>Network concept, structure and public information</em></span><b aria-hidden="true">↗</b>
        </a>
      </div>
      <div class="footer-row">
        <span>Issued and operated by JAIOS Institutional Governance</span>
        <span class="footer-links"><a href="/explorer.json">Explorer JSON</a><a href="https://health.jaios-governance.org/health">Health</a><a href="https://docs.jaios-governance.org/">Technical Reference</a></span>
      </div>
    </div>
  </footer>

  <script>
    (() => {
      "use strict";
      const byId = (id) => document.getElementById(id);
      const set = (id, value, className) => {
        const node = byId(id);
        node.textContent = value ?? "NOT CURRENTLY PUBLISHED";
        node.classList.remove("skeleton", "review", "good", "warn");
        if (className) node.classList.add(className);
      };
      const REFRESH_SECONDS = 5;
      let nextRefreshAt = Date.now();
      let loading = false;
      let samples = 0;
      let retainedReadbacks = 0;
      let previousHeight = null;
      const blockTimestamp = (value) => {
        if (typeof value !== "string") return "NOT YET PUBLISHED";
        const date = new Date(Number.parseInt(value, 16) * 1000);
        return Number.isNaN(date.valueOf()) ? "NOT YET PUBLISHED" : date.toISOString();
      };
      const blockAge = (value) => {
        if (typeof value !== "string") return "Age evidence not currently published";
        const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number.parseInt(value, 16)));
        if (!Number.isFinite(seconds)) return "Age evidence not currently published";
        if (seconds < 60) return `Block age ${seconds}s`;
        if (seconds < 3600) return `Block age ${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `Block age ${Math.floor(seconds / 3600)}h`;
        return `Block age ${Math.floor(seconds / 86400)}d`;
      };
      const scheduleNext = () => {
        nextRefreshAt = Date.now() + REFRESH_SECONDS * 1000;
      };
      const updateCountdown = () => {
        const remaining = Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000));
        set("next-readback", loading ? "Reading…" : `${remaining}s`);
      };
      const load = async () => {
        if (loading) return;
        loading = true;
        updateCountdown();
        const startedAt = performance.now();
        try {
          const explorerResponse = await fetch("/explorer.json", {cache: "no-store"});
          if (!explorerResponse.ok) throw new Error("Explorer data unavailable");
          const explorer = await explorerResponse.json();
          const head = explorer.head;
          if (!head || explorer.finalized_only !== true) throw new Error("Finalized data unavailable");
          const latency = Math.max(0, Math.round(performance.now() - startedAt));
          samples += 1;
          set("network-status", explorer.status === "ready" ? "READY · READ-ONLY" : "VERIFICATION IN PROGRESS");
          set("live-mode", `READBACK · ${REFRESH_SECONDS}s`);
          byId("status-dot").classList.toggle("ready", explorer.status === "ready");
          byId("status-dot").classList.toggle("live", explorer.status === "ready");
          set("height", String(head.height));
          set("quorum", `${head.signed_power} / ${head.total_power}`);
          set("finality-status", explorer.finalized_only ? "Finalized-only" : "Verification in progress", "pill");
          set("finality-height", String(head.height));
          set("finality-hash", head.hash);
          set("certificate-hash", head.certificate_hash);
          set("signed-power", String(head.signed_power));
          set("total-power", String(head.total_power));
          set("chain-id", `${explorer.network.chain_id_decimal} (${explorer.network.chain_id})`);
          set("peers", String(explorer.network.peer_count));
          set("client-version", explorer.network.client_version);
          set("runtime-source-commit", explorer.runtime_artifact.source_commit);
          set("genesis-sha256", explorer.runtime_artifact.genesis_sha256);
          set("node-artifact-sha256", explorer.runtime_artifact.node_artifact_sha256);
          set("block-number", `${head.height} (${`0x${Number(head.height).toString(16)}`})`);
          set("block-hash", head.hash);
          set("parent-hash", head.parent_hash);
          set("state-root", head.state_root);
          set("block-time", blockTimestamp(head.timestamp));
          const count = Number.isInteger(head.transaction_count)
            ? head.transaction_count
            : "NOT YET PUBLISHED";
          set("transactions", String(count));
          set("block-transactions", String(count));
          set("gateway-state", "READY · READ-ONLY", "good");
          set("gateway-latency", `Latency ${latency} ms`);
          set("finality-live", head.signed_power === head.total_power ? "CERTIFICATE OBSERVED" : "VERIFICATION IN PROGRESS", head.signed_power === head.total_power ? "good" : "warn");
          if (previousHeight === null) {
            set("head-movement", "BASELINE OBSERVED", "good");
          } else if (head.height > previousHeight) {
            set("head-movement", `+${head.height - previousHeight} BLOCK`, "good");
          } else {
            set("head-movement", "OBSERVATION CONTINUES");
          }
          previousHeight = head.height;
          set("head-age", blockAge(head.timestamp));
          set("sample-count", String(samples));
          set("failure-count", `Readbacks retained ${retainedReadbacks}`);
          const observedAt = explorer.observed_at || new Date().toISOString();
          set("updated-at", `Live observation ${observedAt}`);
          set("last-success", `Last success ${new Date().toLocaleTimeString()}`);
        } catch {
          retainedReadbacks += 1;
          set("network-status", "VERIFICATION IN PROGRESS", "review");
          set("live-mode", "READBACK CONTINUES", "review");
          byId("status-dot").classList.remove("ready");
          byId("status-dot").classList.remove("live");
          set("gateway-state", "VERIFICATION IN PROGRESS", "review");
          set("gateway-latency", "Last verified evidence retained");
          set("failure-count", `Readbacks retained ${retainedReadbacks}`, "review");
          set("updated-at", "Last verified readback retained", "review");
        } finally {
          loading = false;
          scheduleNext();
          updateCountdown();
        }
      };
      load();
      window.setInterval(load, REFRESH_SECONDS * 1000);
      window.setInterval(updateCountdown, 250);
      window.addEventListener("online", load);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") load();
      });
    })();
  </script>
</body>
</html>
"""
