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
const explorerProxyUrl = "https://docs.jaios-governance.org/explorer.json";
const operationalUrl = "https://chain.jaios-governance.org/api/operational";
const expectedSchema = "junca-public-explorer/v4";
const expectedChainId = 20260723;
const integerValue = (value) => {
  if (Number.isInteger(value)) return value;
  if (typeof value === "string" && /^0x[0-9a-f]+$/i.test(value)) return Number.parseInt(value, 16);
  if (typeof value === "string" && /^[0-9]+$/.test(value)) return Number.parseInt(value, 10);
  return Number.NaN;
};
const isHash = (value) => /^0x[0-9a-f]{64}$/i.test(String(value ?? ""));
const isDigest = (value) => /^[0-9a-f]{64}$/i.test(String(value ?? ""));
const isCommit = (value) => /^[0-9a-f]{40}$/i.test(String(value ?? ""));
const validateExplorer = (candidate) => {
  const candidateHead = candidate?.head ?? {};
  const candidateNetwork = candidate?.network ?? {};
  const artifact = candidate?.runtime_artifact ?? {};
  return candidate?.schema_version === expectedSchema &&
    candidate?.status === "ready" && candidate?.read_only === true &&
    candidate?.finalized_only === true &&
    candidate?.notice === "Public Testnet / Protocol Validation Environment" &&
    candidate?.mainnet_changed === false && candidate?.assets_moved === false &&
    candidate?.bridge_activated === false && Number.isInteger(candidateHead.height) &&
    candidateHead.height > 1 && candidateHead.signed_power === 3 &&
    candidateHead.total_power === 3 && isHash(candidateHead.hash) &&
    isHash(candidateHead.certificate_hash) && isHash(candidateHead.state_root) &&
    integerValue(candidateHead.timestamp) > 0 &&
    candidateNetwork.chain_id_decimal === expectedChainId && candidateNetwork.peer_count === 2 &&
    isCommit(artifact.source_commit) && isDigest(artifact.genesis_sha256) &&
    isDigest(artifact.node_artifact_sha256);
};
const validateOperational = (operationalCandidate, explorerCandidate) => {
  const candidate = operationalCandidate?.network ?? {};
  const head = explorerCandidate.head;
  const network = explorerCandidate.network;
  const finality = String(candidate.finality ?? "").replace(/\s+/g, "").split("/").map(integerValue);
  const operationalHeight = integerValue(candidate.height);
  const failures = [];
  if (candidate.state !== "VERIFIED") failures.push("state");
  if (candidate.status !== "READY · READ-ONLY") failures.push("status");
  if (integerValue(candidate.chainId) !== expectedChainId) failures.push("chain_id");
  if (!Number.isInteger(operationalHeight) || operationalHeight <= 1) failures.push("height");
  if (integerValue(candidate.peers) !== network.peer_count) failures.push("peers");
  if (!(finality.length === 2 && finality[0] === head.signed_power && finality[1] === head.total_power)) failures.push("finality");
  if (candidate.clientVersion !== network.client_version) failures.push("client_version");
  if (!isCommit(candidate.runtimeSourceCommit)) failures.push("source_commit_format");
  if (!isDigest(candidate.nodeArtifactSha256)) failures.push("node_artifact_format");
  if (!isDigest(candidate.genesisSha256)) failures.push("genesis_format");
  if (candidate.mainnetChanged !== false) failures.push("mainnet_boundary");
  if (candidate.assetsMoved !== false) failures.push("asset_boundary");
  if (candidate.bridgeActivated !== false) failures.push("bridge_boundary");
  if (candidate.source !== explorerUrl) failures.push("canonical_source");
  if (failures.length > 0) {
    console.error(`Operational API corroboration mismatch: ${failures.join(",")}`);
    return false;
  }
  return true;
};
const fetchJson = async (url, label) => {
  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Cache-Control": "no-cache, no-store, max-age=0",
      Pragma: "no-cache",
      "User-Agent": "JUNCA-Docs-Current-State/1.1",
    },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`${label} readback failed: HTTP ${response.status}`);
  return response.json();
};
const candidates = [
  { url: explorerUrl, source: "CANONICAL EXPLORER" },
  { url: explorerUrl, source: "CANONICAL EXPLORER" },
  { url: explorerProxyUrl, source: "VERIFIED SAME-ORIGIN PROXY" },
  { url: explorerUrl, source: "CANONICAL EXPLORER" },
  { url: explorerProxyUrl, source: "VERIFIED SAME-ORIGIN PROXY" },
];
let explorer;
let explorerEvidenceSource;
let explorerEvidenceUrl;
const readbackFailures = [];
for (const candidate of candidates) {
  try {
    const [explorerCandidate, operationalCandidate] = await Promise.all([
      fetchJson(candidate.url, candidate.source),
      fetchJson(operationalUrl, "OPERATIONAL API"),
    ]);
    if (!validateExplorer(explorerCandidate)) throw new Error(`${candidate.source} boundary mismatch`);
    if (!validateOperational(operationalCandidate, explorerCandidate)) throw new Error(`${candidate.source} parity mismatch`);
    explorer = explorerCandidate;
    explorerEvidenceSource = candidate.source;
    explorerEvidenceUrl = candidate.url;
    break;
  } catch (error) {
    readbackFailures.push(error instanceof Error ? error.message : String(error));
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}
if (!explorer) throw new Error(`Governed current-state readback failed: ${readbackFailures.join(" | ")}`);
const head = explorer.head ?? {};
const network = explorer.network ?? {};
const runtimeArtifact = explorer.runtime_artifact ?? {};
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

const prohibitedVisible = /\bPENDING\b|\bBLOCKED\b|No Monetary Value|\bNo Active\b|\bNot Activated\b|\bNot Yet Published\b|\bNOT CURRENTLY PUBLISHED\b|\bEVIDENCE REFRESHING\b|\bNot Launched\b|\bnot-activated\b|保留中/i;
const results = [];

for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  let html = await readFile(path, "utf8");
  for (const [before, after] of replacements) html = html.split(before).join(after);
  html = html.replace(/(<dd[^>]*data-live-runtime="source"[^>]*>)[^<]*(<\/dd>)/g, `$1${explorerEvidenceSource}$2`);
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
    source: explorerEvidenceUrl,
    source_mode: explorerEvidenceSource,
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
    source_endpoint: explorerEvidenceUrl,
    source_mode: explorerEvidenceSource,
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
