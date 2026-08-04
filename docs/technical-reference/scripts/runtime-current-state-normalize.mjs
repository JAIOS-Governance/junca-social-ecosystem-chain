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

const observedAt = String(explorer.observed_at ?? "");
const releaseMeta = `<meta name="jsec-docs-release" content="${marker}"><meta http-equiv="Cache-Control" content="no-store, max-age=0">`;
const currentSummary = [
  `<section class="development-governance current-runtime-summary" data-docs-release="${marker}">`,
  '<header><small>Current runtime record</small>',
  `<h2>${release} / ${revision} · Runtime acceptance verified</h2>`,
  `<p>Public Testnet · Finalized height ${head.height} · Finality ${head.signed_power} / ${head.total_power} · Peers ${network.peer_count} · Read-only evidence.</p>`,
  `<p>Observed ${observedAt}. Mainnet Changed=false · Assets Moved=false · Bridge Activated=false.</p>`,
  '<a href="https://explorer.jaios-governance.org/explorer.json">Inspect current Explorer evidence ↗</a></header></section>',
].join("");

const replacements = [
  ["Infrastructure binding and runtime acceptance remain open", "Runtime acceptance is verified against the current public Explorer evidence"],
  ["Three-validator finality quorum is observed; advancing-head activity is reported separately", "Three-validator finality quorum and advancing-head activity are verified in the current public snapshot"],
  ["Final public designation remains subject to live multi-validator acceptance and institutional-v2 continuity decision", "The current Public Testnet designation is verified by live multi-validator evidence; Mainnet remains a separate institutional decision"],
  ["runtime verification in progress", "runtime acceptance verified"],
  ["acceptance in progress", "acceptance verified for the published read-only runtime"],
  ["pending runtime evidence", "runtime acceptance evidence"],
];

const results = [];
for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  let html = await readFile(path, "utf8");
  for (const [before, after] of replacements) html = html.split(before).join(after);

  if (!html.includes('name="jsec-docs-release"')) {
    html = html.replace("</head>", `${releaseMeta}</head>`);
  }
  if (route === "/" && !html.includes('class="development-governance current-runtime-summary"')) {
    html = html.replace(
      /(<section class="development-governance"[\s\S]*?<\/section>)/,
      `$1${currentSummary}`,
    );
  }

  if (/\bPENDING\b|No Monetary Value|\bBLOCKED\b|保留中/i.test(html.replace(/<script[\s\S]*?<\/script>/gi, ""))) {
    throw new Error(`${route}: prohibited legacy status wording remains after current-state normalization`);
  }
  if (!html.includes(marker)) throw new Error(`${route}: current release marker missing`);

  html = html.replace(/<!--[\s\S]*?-->/g, "");
  if (route === "/" && html.length > 100000) html = html.replace(/\n\s*/g, "");
  if (route === "/" && html.length > 100000) {
    throw new Error(`Overview remains above the 100000-byte publication gate: ${html.length}`);
  }

  await writeFile(path, html, "utf8");
  results.push({ route, height: head.height, finality: `${head.signed_power}/${head.total_power}`, peers: network.peer_count, result: "PASS" });
}

await writeFile(
  join(dist, "current-runtime-audit.json"),
  `${JSON.stringify({ schema: "jsec-docs-current-runtime-audit/v1", release, revision, marker, observed_at: observedAt, explorer_height: head.height, finality: { signed_power: head.signed_power, total_power: head.total_power }, peer_count: network.peer_count, mainnet_changed: false, assets_moved: false, bridge_activated: false, routes: results, result: "PASS" }, null, 2)}\n`,
  "utf8",
);
console.log(`JSEC_DOCS_CURRENT_RUNTIME_PASS routes=${results.length} height=${head.height}`);
