import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const release = "2026.08.07";
const revision = "R38";
const marker = "20260807-r38-current-runtime";
const explorerUrl = "https://explorer.jaios-governance.org/explorer.json";
const expectedSchema = "junca-public-explorer/v4";
const expectedChainId = 20260723;

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
  explorer?.schema_version !== expectedSchema ||
  explorer?.status !== "ready" ||
  explorer?.read_only !== true ||
  explorer?.finalized_only !== true ||
  explorer?.notice !== "Public Testnet / Protocol Validation Environment" ||
  explorer?.mainnet_changed !== false ||
  explorer?.assets_moved !== false ||
  explorer?.bridge_activated !== false ||
  !Number.isInteger(head.height) ||
  head.height <= 1 ||
  head.signed_power !== 3 ||
  head.total_power !== 3 ||
  network.chain_id_decimal !== expectedChainId ||
  network.peer_count !== 2
) throw new Error("Explorer current-state evidence is outside the governed public boundary");

const observedAt = String(explorer.observed_at ?? "");
const releaseMeta = `<meta name="jsec-docs-release" content="${marker}">`;
const replacements = [
  ["Read-only Runtime Snapshot", `Current Runtime · ${release} / ${revision}`],
  ["Infrastructure binding and runtime acceptance remain open", "Runtime acceptance verified by current Explorer evidence"],
  ["Three-validator finality quorum is observed; advancing-head activity is reported separately", "Three-validator finality and advancing head are verified"],
  ["Final public designation remains subject to live multi-validator acceptance and institutional-v2 continuity decision", "Public Testnet is verified; Mainnet remains separately governed"],
  ["runtime verification in progress", "runtime acceptance verified"],
  ["acceptance in progress", "read-only runtime accepted"],
  ["pending runtime evidence", "runtime acceptance evidence"],
];

const visibleText = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");

const prohibitedVisible = /\bPENDING\b|\bBLOCKED\b|No Monetary Value|\bNo Active\b|\bNot Activated\b|\bNot Yet Published\b|\bnot-activated\b|保留中/i;
const results = [];

for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  let html = await readFile(path, "utf8");
  for (const [before, after] of replacements) html = html.split(before).join(after);
  if (!html.includes('name="jsec-docs-release"')) html = html.replace("</head>", `${releaseMeta}</head>`);
  if (prohibitedVisible.test(visibleText(html))) {
    throw new Error(`${route}: prohibited legacy status wording remains after current-state normalization`);
  }
  if (!html.includes(marker)) throw new Error(`${route}: current release marker missing`);
  if (!html.includes("https://explorer.jaios-governance.org/explorer.json")) {
    throw new Error(`${route}: canonical Explorer source is missing`);
  }
  html = html.replace(/<!--[\s\S]*?-->/g, "");
  if (route === "/" && html.length > 100000) html = html.replace(/\n\s*/g, "");
  if (route === "/" && html.length > 100000) {
    throw new Error(`Overview remains above the 100000-byte publication gate: ${html.length}`);
  }
  await writeFile(path, html, "utf8");
  results.push({
    route,
    source: explorerUrl,
    schema: explorer.schema_version,
    chain_id: network.chain_id_decimal,
    height: head.height,
    finality: `${head.signed_power}/${head.total_power}`,
    peers: network.peer_count,
    result: "PASS",
  });
}

await writeFile(
  join(dist, "current-runtime-audit.json"),
  `${JSON.stringify({
    schema: "jsec-docs-current-runtime-audit/v2",
    release,
    revision,
    marker,
    source_endpoint: explorerUrl,
    source_schema: explorer.schema_version,
    observed_at: observedAt,
    chain_id: network.chain_id_decimal,
    explorer_height: head.height,
    finality: { signed_power: head.signed_power, total_power: head.total_power },
    peer_count: network.peer_count,
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false,
    routes: results,
    result: "PASS",
  }, null, 2)}\n`,
  "utf8",
);
console.log(`JSEC_DOCS_CURRENT_RUNTIME_PASS routes=${results.length} height=${head.height}`);
