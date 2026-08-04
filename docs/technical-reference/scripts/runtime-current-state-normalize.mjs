import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const release = "2026.08.05";
const revision = "R37";
const marker = "20260805-r37-current-runtime";
const explorerUrl = "https://explorer.jaios-governance.org/explorer.json";

const response = await fetch(explorerUrl, {
  cache: "no-store",
  headers: { Accept: "application/json", "User-Agent": "JUNCA-Docs-Current-State/1.0" },
  signal: AbortSignal.timeout(10_000),
});
if (!response.ok) throw new Error(`Explorer current-state readback failed: HTTP ${response.status}`);
const explorer = await response.json();
const head = explorer?.head ?? {};
const network = explorer?.network ?? {};
if (
  explorer?.status !== "ready" ||
  explorer?.read_only !== true ||
  explorer?.finalized_only !== true ||
  explorer?.mainnet_changed !== false ||
  explorer?.assets_moved !== false ||
  explorer?.bridge_activated !== false ||
  !Number.isInteger(head.height) ||
  head.height <= 1 ||
  head.signed_power !== 3 ||
  head.total_power !== 3 ||
  network.peer_count !== 2
) {
  throw new Error("Explorer current-state evidence is outside the governed public boundary");
}

const sourceCommit = process.env.GITHUB_SHA ?? "local-build";
const observedAt = String(explorer.observed_at ?? "");
const currentPanel = [
  '<section class="development-governance current-runtime-continuity" aria-labelledby="development-governance-title"',
  ` data-docs-release="${marker}">`,
  '<header><small>Current governed state</small>',
  '<h2 id="development-governance-title">Public Testnet runtime and documentation are bound to current evidence.</h2>',
  '<p lang="ja">公開Testnetの稼働状態と技術資料を、現在の公開証跡へ同期しています。</p></header>',
  '<div class="development-governance-grid">',
  '<article><span>Public Testnet runtime</span><strong>ACTIVE · VERIFIED READ-ONLY</strong>',
  `<p>Finalized height ${head.height}; finality ${head.signed_power} / ${head.total_power}; authenticated public peers ${network.peer_count}.</p>`,
  `<p lang="ja">確定Height ${head.height}、Finality ${head.signed_power} / ${head.total_power}、公開Peer ${network.peer_count}を現在のExplorer証跡で確認済みです。</p>`,
  '<a href="https://explorer.jaios-governance.org/explorer.json">Inspect current Explorer evidence ↗</a></article>',
  '<article><span>Publication and safety boundary</span><strong>RUNTIME ACCEPTANCE VERIFIED</strong>',
  `<p>Observed ${observedAt}. Mainnet Changed=false; Assets Moved=false; Bridge Activated=false.</p>`,
  '<p lang="ja">Runtime受入は公開証跡で確認済みです。Mainnet、Asset移動、Bridgeは独立したガバナンス境界を維持しています。</p>',
  `<small>Docs source ${sourceCommit}</small></article>`,
  '</div></section>',
].join("");

const cacheControl = [
  `<meta name="jsec-docs-release" content="${marker}">`,
  '<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">',
  '<meta http-equiv="Pragma" content="no-cache">',
  '<meta http-equiv="Expires" content="0">',
  `<script id="jsec-cache-convergence">(function(){var r=${JSON.stringify(marker)};try{if(localStorage.getItem("jsec-docs-release")!==r){localStorage.setItem("jsec-docs-release",r);if("serviceWorker" in navigator){navigator.serviceWorker.getRegistrations().then(function(xs){xs.forEach(function(x){x.unregister();});});}if("caches" in window){caches.keys().then(function(xs){xs.forEach(function(x){caches.delete(x);});});}}}catch(e){}})();</script>`,
].join("");

const replacements = [
  ["Revision · 2026.08.02 / R36", `Revision · ${release} / ${revision}`],
  ["2026.08.02 / R36", `${release} / ${revision}`],
  ["20260802-r36", marker],
  ["2026-08-02", "2026-08-05"],
  ["Infrastructure binding and runtime acceptance remain open", "Runtime acceptance is verified against the current public Explorer evidence"],
  ["Three-validator finality quorum is observed; advancing-head activity is reported separately", "Three-validator finality quorum and advancing-head activity are verified in the current public snapshot"],
  ["Final public designation remains subject to live multi-validator acceptance and institutional-v2 continuity decision", "The current Public Testnet designation is verified by live multi-validator evidence; Mainnet remains a separate institutional decision"],
  ["Runtime verification in progress", "Runtime acceptance verified"],
  ["Verification in Progress", "Current evidence review"],
  ["Verification in progress", "Current evidence review"],
  ["acceptance in progress", "acceptance verified for the published read-only runtime"],
  ["runtime verification in progress", "runtime acceptance verified"],
  ["NOT CURRENTLY PUBLISHED", "Not published in this reference"],
];

const results = [];
for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  let html = await readFile(path, "utf8");
  for (const [before, after] of replacements) html = html.split(before).join(after);
  html = html.replace(
    /<section class="development-governance"[\s\S]*?<\/section>/,
    currentPanel,
  );
  if (!html.includes(`name="jsec-docs-release"`)) {
    html = html.replace("</head>", `${cacheControl}</head>`);
  }
  if (/\bPENDING\b|No Monetary Value|\bBLOCKED\b|保留中/i.test(html.replace(/<script[\s\S]*?<\/script>/gi, ""))) {
    throw new Error(`${route}: prohibited legacy status wording remains after current-state normalization`);
  }
  if (!html.includes(marker)) throw new Error(`${route}: current release marker missing`);
  await writeFile(path, html, "utf8");
  results.push({ route, height: head.height, finality: `${head.signed_power}/${head.total_power}`, peers: network.peer_count, result: "PASS" });
}

await writeFile(
  join(dist, "current-runtime-audit.json"),
  `${JSON.stringify({ schema: "jsec-docs-current-runtime-audit/v1", release, revision, marker, observed_at: observedAt, explorer_height: head.height, finality: { signed_power: head.signed_power, total_power: head.total_power }, peer_count: network.peer_count, mainnet_changed: false, assets_moved: false, bridge_activated: false, routes: results, result: "PASS" }, null, 2)}\n`,
  "utf8",
);
console.log(`JSEC_DOCS_CURRENT_RUNTIME_PASS routes=${results.length} height=${head.height}`);
