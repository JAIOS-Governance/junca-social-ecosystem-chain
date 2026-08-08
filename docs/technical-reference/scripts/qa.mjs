// R22 publication marker: JAIOS institutional link accepted for production.
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  secondaryLanguageMeta,
  secondaryTranslationIndex,
} from "../src/secondary-language.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const repositoryRoot = join(root, "..", "..");
const origin = "https://docs.jaios-governance.org";
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const prohibited = [
  "CEO-controlled", "CEO-sovereign", "Mainnet is live", "Bridge is active", "monetary value enabled",
  "Runtime Deployment in Progress", "Pending Live Acceptance", "Runtime Unverified", "Public endpoint pending",
  "No Monetary Value",
  "No Active", "Not Activated", "Not Yet Published", "NOT CURRENTLY PUBLISHED", "EVIDENCE REFRESHING", "Not Launched", "not-activated",
  "Known, under verification and not activated",
  "Public Testnet Runtime Active", "Runtime Verified", "Live Acceptance Verified", "Automation Active · PASS",
  "Continuous block production remains under review", "No public endpoint is asserted",
  "PENDING", "pending", "保留中",
];
const failures = [];
const secondaryIndex = secondaryTranslationIndex();
const visibleText = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");

for (const route of routes) {
  const file = route === "/" ? join(dist, "index.html") : join(dist, route.slice(1), "index.html");
  const html = await readFile(file, "utf8");
  const canonical = `${origin}${route === "/" ? "/" : route}`;
  if (!new RegExp(`<link[^>]+rel=["']canonical["'][^>]+href=["']${canonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'][^>]*>`).test(html)) {
    failures.push(`${route}: missing canonical ${canonical}`);
  }
  if (!new RegExp(`<meta[^>]+property=["']og:url["'][^>]+content=["']${canonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'][^>]*>`).test(html)) {
    failures.push(`${route}: missing og:url ${canonical}`);
  }
  for (const required of [
    "JUNCA Social Ecosystem Chain",
    "JAIOS Institutional Governance",
    "Public Testnet",
    "Governed Read-only Operations",
    "Protocol Validation Environment",
    "Measured runtime evidence, published from the current Explorer readback.",
    "Finality",
    "READY · READ-ONLY",
    "3 / 3",
    "Finalized Height",
    "Chain ID",
    "20260723",
    "Block Timestamp",
    'data-live-runtime="observed-at"',
    'data-live-runtime="source"',
    "Mainnet State: UNCHANGED",
    "Production Asset Boundary: UNCHANGED",
    "Bridge State: GOVERNANCE-CONTROLLED",
    'data-live-runtime="height"',
    "PR #237 · MERGED",
    "PR #236 · OPEN DRAFT",
    'href="https://chain.jaios-governance.org/"',
    'href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/237"',
    'href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/236"',
    'href="https://jaios-governance.org/"',
    'class="jaios-institutional-link"',
    'href="https://explorer.jaios-governance.org/"',
    'class="public-explorer-link"',
    'src="/official-junca-symbol.png"',
    'class="header-explorer-link"',
    '<meta name="application-name" content="JUNCA Docs">',
    '<meta name="apple-mobile-web-app-title" content="JUNCA Docs">',
    'src="/junca-chain-official-wordmark.png?v=20260807-r38"',
    'src="/official-brand-lockup-r32.js?v=20260807-r38"',
    'src="/docs-controls-r32.js?v=20260807-r38"',
    'src="/live-runtime-r38.js?v=20260807-r38"',
    'src="/secondary-language.js?v=20260807-r38"',
    'href="/favicon.ico"',
    'id="secondary-language-select"',
    'English remains the fixed primary language.',
    'alt="JUNCA"',
  ]) {
    if (!html.includes(required)) failures.push(`${route}: missing ${required}`);
  }
  if (!html.includes("CANONICAL EXPLORER") && !html.includes("VERIFIED SAME-ORIGIN PROXY")) {
    failures.push(`${route}: missing verified runtime evidence source mode`);
  }
  for (const term of prohibited) {
    if (html.toLowerCase().includes(term.toLowerCase())) failures.push(`${route}: prohibited public claim ${term}`);
  }
  const exposedPublicState = visibleText(html).match(
    /\b(?:PENDING|BLOCKED|FAILED|STOPPED|RETRYING|UNAVAILABLE|NOT ACTIVATED|NO ACTIVE|NOT YET PUBLISHED|NOT CURRENTLY PUBLISHED|EVIDENCE REFRESHING|NOT LAUNCHED)\b/i,
  )?.[0];
  if (exposedPublicState) {
    failures.push(`${route}: exposed public failure-oriented state ${exposedPublicState}`);
  }
  for (const forbiddenDisplay of [
    "BLOCKED: accepted network registry is required",
  ]) {
    if (visibleText(html).includes(forbiddenDisplay)) {
      failures.push(`${route}: exposed technical failure display ${forbiddenDisplay}`);
    }
  }
  if (!html.startsWith('<!DOCTYPE html><html lang="en">')) {
    failures.push(`${route}: English must remain the fixed document language`);
  }
  if (/<html[^>]*\bdir=["']rtl["']/.test(html)) {
    failures.push(`${route}: RTL must not be applied to the English document root`);
  }
  for (const [value, { label }] of Object.entries(secondaryLanguageMeta)) {
    if (!html.includes(`<option value="${value}">${label}</option>`)) {
      failures.push(`${route}: missing secondary-language option ${value}`);
    }
  }
  const secondaryElements = [...html.matchAll(
    /<([a-z][\w-]*)([^>]*\blang="ja"[^>]*\bdata-secondary-copy[^>]*\bdata-secondary-key="([^"]+)"[^>]*)>([\s\S]*?)<\/\1>/gi,
  )];
  if (secondaryElements.length === 0) {
    failures.push(`${route}: no build-time secondary-language elements found`);
  }
  for (const [, , , key, japanese] of secondaryElements) {
    const record = secondaryIndex.get(japanese);
    if (!record) failures.push(`${route}: untranslated Japanese source ${japanese}`);
    else if (record.key !== key) failures.push(`${route}: secondary-language key mismatch for ${japanese}`);
  }
  const authoredJapaneseCount = [...html.matchAll(/\blang="ja"/g)].length;
  if (secondaryElements.length !== authoredJapaneseCount) {
    failures.push(`${route}: ${authoredJapaneseCount - secondaryElements.length} Japanese elements lack static multilingual coverage`);
  }
}
const secondaryRuntime = await readFile(join(dist, "secondary-language.js"), "utf8");
for (const required of [
  "junca-docs-secondary-language",
  "data-secondary-copy",
  "data-secondary-key",
  "window.localStorage",
  'element.dir = "rtl"',
  'element.removeAttribute("dir")',
]) {
  if (!secondaryRuntime.includes(required)) failures.push(`secondary-language runtime missing ${required}`);
}
if (secondaryRuntime.includes("MutationObserver")) {
  failures.push("secondary-language runtime must not depend on DOM observation");
}
const home = await readFile(join(dist, "index.html"), "utf8");
if (home.length > 100000) failures.push(`/: overview payload is too long (${home.length} bytes)`);
if (home.includes("codex-preview")) failures.push("/: development preview metadata remains");
for (const requiredInstallLink of [
  'rel="icon" href="https://docs.jaios-governance.org/icon-192.png?v=20260807-r38"',
  'rel="apple-touch-icon" href="https://docs.jaios-governance.org/apple-touch-icon.png?v=20260807-r38"',
  'rel="manifest" href="https://docs.jaios-governance.org/manifest.webmanifest?v=20260807-r38"',
]) {
  if (!home.includes(requiredInstallLink)) failures.push(`/: missing cache-busted install metadata ${requiredInstallLink}`);
}
for (const required of [
  "Chain Core",
  "Implemented / CI Verified",
  "AWS Runtime",
  "Read-only Operations",
  "Assets Moved",
  "Revision · 2026.08.07 / R38",
]) {
  if (!home.includes(required)) failures.push(`/: missing release-state item ${required}`);
}
const cssName = (await readdir(join(dist, "assets"))).find((name) => /^index-.*\.css$/.test(name));
if (!cssName) failures.push("approved design stylesheet missing");
const css = cssName ? await readFile(join(dist, "assets", cssName), "utf8") : "";
for (const font of ["Cormorant Garamond", "Source Serif 4", "Inter", "Shuei Mincho", "Shuei Kaku Gothic"]) {
  if (!css.includes(font)) failures.push(`font stack missing ${font}`);
}
if (!home.includes(".wordmark img{display:block;width:190px")) {
  failures.push("canonical JUNCA wordmark display rule missing");
}
if (!home.includes(".site-header .header-explorer-link{display:none!important}")) {
  failures.push("mobile header must hide the desktop Explorer shortcut");
}
if (!home.includes("grid-template-columns:minmax(0,1fr) 48px!important")) {
  failures.push("mobile header must remain a two-column brand/menu layout");
}
if (!home.includes("width:132px;max-width:44vw")) {
  failures.push("mobile JUNCA wordmark viewport guard missing");
}
if (!home.includes(".menu-toggle span:last-child{position:absolute")) {
  failures.push("mobile menu label collision guard missing");
}
if (!home.includes("body.docs-menu-open{overflow:hidden}")) failures.push("mobile body-scroll lock style missing");
if (!css.includes(":focus-visible")) failures.push("keyboard focus style missing");
for (const required of [".release-status", ".finality-brief", ".developer-modules", ".evidence-tracks"]) {
  if (!css.includes(required)) failures.push(`approved design stylesheet missing ${required}`);
}
const protocol = await readFile(join(dist, "protocol", "index.html"), "utf8");
for (const required of [
  "Certified Finality and Validator Epoch Safety",
  "strict greater-than-two-thirds voting power",
  "Old-epoch validator proofs are rejected",
  "Developer Environment CI verified",
]) {
  if (!protocol.includes(required)) failures.push(`/protocol: missing ${required}`);
}
const implementation = await readFile(join(dist, "implementation", "index.html"), "utf8");
for (const required of [
  "Public Testnet Network Configuration",
  "<code>20260723</code>",
  "explorer.jaios-governance.org",
  "Transaction submission is disabled",
  "Getting Started",
  "Smart Contract Deployment",
  "Token Standard",
  "NFT Standard",
  "Partner Release Checklist",
]) {
  if (!implementation.includes(required)) failures.push(`/implementation: missing ${required}`);
}
const evidence = await readFile(join(dist, "evidence", "index.html"), "utf8");
for (const required of [
  "Documentation Publication Evidence",
  "Network Runtime Evidence",
  "6de0979b9725",
  "/pull/237",
  "/pull/236",
]) {
  if (!evidence.includes(required)) failures.push(`/evidence: missing ${required}`);
}
const og = await readFile(join(dist, "og-reference.png"));
if (og.length < 10000) failures.push("1200x630 PNG social preview is missing or invalid");
const sitemap = await readFile(join(dist, "sitemap.xml"), "utf8");
for (const route of routes) {
  const url = `${origin}${route === "/" ? "/" : route}`;
  if (!sitemap.includes(`<loc>${url}</loc>`)) failures.push(`sitemap missing ${url}`);
}
if (!(await readFile(join(dist, "robots.txt"), "utf8")).includes("Allow: /")) failures.push("robots.txt does not allow production indexing");
const llms = await readFile(join(dist, "llms.txt"), "utf8");
for (const required of [
  "JUNCA Social Ecosystem Chain",
  "juncachain",
  "junca Platform",
  "JUNCA PLATFORM APP",
  "JUNCA GLOBAL CHAIN",
  "JCC (JUNCA CASH)",
  "Proof-of-Concept",
  "Public Testnet",
  "Mainnet Changed: false",
  "Assets Moved: false",
  "Bridge Activated: false",
]) {
  if (!llms.includes(required)) failures.push(`llms.txt missing ${required}`);
}
if ((await readFile(join(dist, "googlebc356aae986ed066.html"), "utf8")).trim() !== "google-site-verification: googlebc356aae986ed066.html") {
  failures.push("Google Search Console verification file is missing or invalid");
}
await readFile(join(dist, "404.html"), "utf8");
const releaseManifest = JSON.parse(await readFile(join(dist, "release-manifest.json"), "utf8"));
if (/No Monetary Value|金銭的価値|金銭価値|資金価値/i.test(JSON.stringify(releaseManifest))) {
  failures.push("release manifest must not republish unapproved value-disclaimer wording");
}
if (releaseManifest.revision !== "R38") failures.push("release manifest revision must be R38");
if (!/^[0-9a-f]{40}$/.test(releaseManifest.chain_source_commit ?? "")) {
  failures.push("release manifest must bind the exact development source commit");
}
if (
  process.env.GITHUB_SHA &&
  releaseManifest.development_source_commit !== process.env.GITHUB_SHA
) {
  failures.push("release manifest development source must match the workflow commit");
}
if (!/^[0-9a-f]{40}$/.test(releaseManifest.runtime_artifact_commit ?? "")) {
  failures.push("runtime artifact commit must be an exact public evidence SHA");
}
if (releaseManifest.runtime_artifact_commit_status !== "VERIFIED") {
  failures.push("runtime artifact provenance must be verified");
}
if (
  releaseManifest.runtime_evidence?.source_evidence?.runtime_artifact_commit !==
  releaseManifest.runtime_artifact_commit
) {
  failures.push("runtime artifact commit must match nested source evidence");
}
for (const field of ["runtime_genesis_sha256", "runtime_node_artifact_sha256"]) {
  if (!/^[0-9a-f]{64}$/.test(releaseManifest[field] ?? "")) {
    failures.push(`${field} must be an exact public evidence digest`);
  }
  if (
    releaseManifest.runtime_evidence?.source_evidence?.[field] !==
    releaseManifest[field]
  ) {
    failures.push(`${field} must match nested source evidence`);
  }
}
if (releaseManifest.runtime_status !== "VERIFIED_READY_READ_ONLY") {
  failures.push("release manifest must record the verified read-only runtime state");
}
if (releaseManifest.public_endpoint_status !== "ACTIVE_READ_ONLY") failures.push("public endpoint must remain active and read-only");
const approvedRuntimeEvidenceEndpoints = new Set([
  "https://explorer.jaios-governance.org/explorer.json",
  "https://docs.jaios-governance.org/explorer.json",
]);
if (!approvedRuntimeEvidenceEndpoints.has(releaseManifest.runtime_evidence_endpoint)) {
  failures.push("runtime evidence endpoint is outside the approved canonical/fallback routes");
}
if (!["CANONICAL EXPLORER", "VERIFIED SAME-ORIGIN PROXY"].includes(releaseManifest.runtime_evidence_source_mode)) {
  failures.push("runtime evidence source mode is not verified");
}
if (
  !Number.isInteger(releaseManifest.runtime_evidence?.finalized_height) ||
  releaseManifest.runtime_evidence.finalized_height <= 1
) {
  failures.push("verified advancing finalized height is missing");
}
if (releaseManifest.runtime_evidence?.total_power !== 3) failures.push("verified finality quorum is missing");
for (const field of ["finalized_hash", "certificate_hash", "state_root"]) {
  if (!/^0x[0-9a-f]{64}$/i.test(releaseManifest.runtime_evidence?.[field] ?? "")) {
    failures.push(`measured runtime ${field} is missing`);
  }
}
if (!releaseManifest.runtime_evidence?.observed_at) failures.push("runtime observation timestamp is missing");
if (!releaseManifest.runtime_evidence?.client_version) failures.push("runtime client version is missing");
if (releaseManifest.runtime_evidence?.mainnet_changed !== false) failures.push("mainnet boundary is missing");
if (releaseManifest.runtime_evidence?.assets_moved !== false) failures.push("asset movement boundary is missing");
if (releaseManifest.runtime_evidence?.bridge_activated !== false) failures.push("bridge boundary is missing");
if (!/^0x[0-9a-f]+$/i.test(releaseManifest.runtime_evidence?.block_timestamp ?? "")) failures.push("publication-snapshot block timestamp is missing");
if (!/^\d{4}-\d{2}-\d{2}T/.test(releaseManifest.runtime_evidence?.block_timestamp_public_label ?? "")) {
  failures.push("English publication-snapshot block timestamp label is missing");
}
if (releaseManifest.runtime_evidence?.block_timestamp_public_label_ja !== "公開時点の確定Block時刻") {
  failures.push("Japanese publication-snapshot block timestamp label is missing");
}
if (releaseManifest.runtime_evidence?.mainnet_activation_authorized !== false) {
  failures.push("mainnet activation authorization boundary is missing");
}
if (releaseManifest.runtime_evidence?.block_activity_conclusion !== "PUBLICATION_SNAPSHOT_ONLY") {
  failures.push("manifest height must remain classified as a publication snapshot");
}
if (releaseManifest.development_governance?.canonical_foundation?.pull_request !== 237) {
  failures.push("PR #237 canonical development foundation is missing");
}
if (releaseManifest.development_governance?.auxiliary_gateway?.state !== "OPEN_DRAFT_UNMERGED_UNDEPLOYED") {
  failures.push("PR #236 auxiliary gateway boundary is missing");
}
await readFile(join(dist, "manifest.webmanifest"), "utf8");
const installManifest = JSON.parse(await readFile(join(dist, "manifest.webmanifest"), "utf8"));
if (installManifest.id !== "/") failures.push("install manifest identity must remain bound to the canonical root");
if (installManifest.short_name !== "JUNCA Docs") failures.push("install manifest short name must be JUNCA Docs");
for (const requiredIcon of [
  "/icon-192.png?v=20260807-r38",
  "/icon-512.png?v=20260807-r38",
  "/icon-maskable-512.png?v=20260807-r38",
]) {
  if (!installManifest.icons?.some((icon) => icon.src === requiredIcon)) {
    failures.push(`install manifest missing cache-busted official symbol ${requiredIcon}`);
  }
}
await readFile(join(dist, "icon-192.png"));
await readFile(join(dist, "icon-512.png"));
await readFile(join(dist, "icon-maskable-512.png"));
await readFile(join(dist, "apple-touch-icon.png"));
await readFile(join(dist, "favicon.ico"));
const officialWordmark = await readFile(join(dist, "junca-chain-official-wordmark.png"));
const officialWordmarkDigest = createHash("sha256").update(officialWordmark).digest("hex");
if (officialWordmarkDigest !== "31cc93f73cf01d8479260cf1a6894c0ca28ca0eff7bd95c89226e086049728ac") {
  failures.push("official flattened JUNCA wordmark digest mismatch");
}
const brandRuntime = await readFile(join(dist, "official-brand-lockup-r32.js"), "utf8");
for (const required of [
  "data-official-junca-wordmark",
  "MutationObserver",
  ".official-product-name",
  ".footer-brand-lockup",
]) {
  if (!brandRuntime.includes(required)) failures.push(`official brand hydration guard missing ${required}`);
}
const docsControls = await readFile(join(dist, "docs-controls-r32.js"), "utf8");
for (const required of ["Escape", "docs-menu-open", "aria-expanded", "menuButton.focus()"]) {
  if (!docsControls.includes(required)) failures.push(`mobile menu control missing ${required}`);
}
const liveRuntime = await readFile(join(dist, "live-runtime-r38.js"), "utf8");
for (const required of [
  'CANONICAL_EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json"',
  'SAME_ORIGIN_PROXY_URL = "/explorer.json"',
  "fetchExplorer(CANONICAL_EXPLORER_URL)",
  "fetchExplorer(SAME_ORIGIN_PROXY_URL)",
  'source = "VERIFIED SAME-ORIGIN PROXY"',
  'cache: "no-store"',
  "REFRESH_MS = 15_000",
  "TIMEOUT_MS = 10_000",
  "Preserve the last verified values",
  'window.addEventListener("online"',
  'document.addEventListener("visibilitychange"',
]) {
  if (!liveRuntime.includes(required)) failures.push(`live runtime integration missing ${required}`);
}
if (liveRuntime.includes("release-manifest.json")) {
  failures.push("Docs manifest must not be used as the live network source");
}
if (!home.includes('class="official-product-name"')) failures.push("/: official product-name lockup missing");
if (!home.includes('class="official-brand-lockup"')) failures.push("/: documentation brand lockup missing");
if (!home.includes('class="footer-brand-lockup"')) failures.push("/: footer brand lockup missing");
for (const retiredTypedLockup of [
  '<span>JUNCA Social Ecosystem Chain</span>',
  '<h1>JUNCA Social Ecosystem Chain</h1>',
  '<strong>JUNCA Social Ecosystem Chain</strong>',
]) {
  if (home.includes(retiredTypedLockup)) failures.push(`/: retired typed lockup remains: ${retiredTypedLockup}`);
}
const retiredAssets = [
  "junca-j-r21-192.png",
  "junca-j-r21-512.png",
  "junca-j-r21-maskable-512.png",
  "junca-j-r21-apple-touch.png",
  "junca-j-r21.svg",
  "junca-j-r21.webmanifest",
  "junca-symbol-r20-192.png",
  "junca-symbol-r20-512.png",
  "junca-symbol-r20-maskable-512.png",
  "junca-symbol-r20-apple-touch.png",
  "junca-symbol-r20.svg",
  "junca-symbol-r20.webmanifest",
];
const rootAssets = new Set(await readdir(dist));
for (const retiredAsset of retiredAssets) {
  if (rootAssets.has(retiredAsset)) failures.push(`retired install asset remains: ${retiredAsset}`);
  if (home.includes(retiredAsset)) failures.push(`/: retired install asset reference remains: ${retiredAsset}`);
}
const favicon = await readFile(join(dist, "favicon.svg"), "utf8");
if (!favicon.includes('data-symbol="JUNCA Official Symbol"')) failures.push("favicon does not declare the official symbol");
if (!favicon.includes('data-rendering="non-distorting-resize"')) failures.push("favicon symbol rendering contract is missing");
if (!favicon.includes('data-source-drive-id="1DiGrLHOWRcrVnt2BdijSFDy3U4mSvgBn"')) failures.push("favicon official Drive source is missing");
if (!favicon.includes('data-source-package-sha256="3dc49cf3e5110207f4a1274e972d194943aaac8df657caa969cc4e326ecceba9"')) failures.push("favicon package digest is missing");
if (!favicon.includes('href="data:image/png;base64,')) failures.push("favicon symbol must be self-contained");
if (/<text[\s>]/.test(favicon)) failures.push("favicon must ship as a flattened official symbol, not runtime text");
for (const prohibitedMarker of ["Monotype official Optima Bold specimen", "flattened-approved-specimen", "Approved Optima Bold J specimen"]) {
  if (favicon.includes(prohibitedMarker)) failures.push(`favicon retains retired J provenance: ${prohibitedMarker}`);
}
const expectedSymbolDigests = new Map([
  ["official-junca-symbol.png", "8c97a6770bf26bee416e9d9014cf16ec94d750c264d2bf6aa23d246357bc0e22"],
  ["icon-192.png", "e0467b657d02d3be641056d53d922f83f7e557413b4d48b9450517012e4e5b3a"],
  ["icon-512.png", "8c97a6770bf26bee416e9d9014cf16ec94d750c264d2bf6aa23d246357bc0e22"],
  ["icon-maskable-512.png", "8c97a6770bf26bee416e9d9014cf16ec94d750c264d2bf6aa23d246357bc0e22"],
  ["apple-touch-icon.png", "1eb5fb801e45366beabf85cc724ac4686864f805b64540c23e8a36aeaf2903f5"],
]);
for (const [name, expected] of expectedSymbolDigests) {
  const path = name === "official-junca-symbol.png"
    ? join(root, "src", name)
    : join(dist, name);
  const actual = createHash("sha256").update(await readFile(path)).digest("hex");
  if (actual !== expected) failures.push(`${name}: official symbol digest mismatch`);
}
const infrastructure = await readFile(join(repositoryRoot, "infra", "aws", "docs-publication", "main.yaml"), "utf8");
const workflow = await readFile(join(repositoryRoot, ".github", "workflows", "junca-chain-docs-production.yml"), "utf8");
for (const required of [
  "DeletionPolicy: Retain",
  "PublicAccessBlockConfiguration",
  "OriginAccessControl",
  "TLSv1.2_2021",
  "DocsAliasA:",
  "DocsAliasAAAA:",
  "repo:JAIOS-Governance@${RepositoryOwnerId}/junca-social-ecosystem-chain@${RepositoryId}:environment:${EnvironmentName}",
  "junca-chain-docs-production"
]) {
  if (!infrastructure.includes(required)) failures.push(`infrastructure missing ${required}`);
}
for (const prohibitedAction of ["ec2:RunInstances", "kms:CreateKey", "iam:CreateAccessKey"]) {
  if (infrastructure.includes(prohibitedAction)) failures.push(`publication role includes prohibited action ${prohibitedAction}`);
}
for (const required of [
  "environment: junca-chain-docs-production",
  "id-token: write",
  "AWS_DOCS_DEPLOYMENT_ROLE_ARN",
  "aws cloudfront wait invalidation-completed",
  "release-manifest.json"
]) {
  if (!workflow.includes(required)) failures.push(`workflow missing ${required}`);
}
if (/AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY/.test(workflow)) failures.push("workflow contains long-term AWS credential names");
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`QA PASS: ${routes.length} routes, metadata, official fonts, accessibility baseline and publication boundary`);
