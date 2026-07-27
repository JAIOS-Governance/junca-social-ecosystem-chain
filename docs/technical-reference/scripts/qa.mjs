// R22 publication marker: JAIOS institutional link accepted for production.
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const repositoryRoot = join(root, "..", "..");
const origin = "https://docs.jaios-governance.org";
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const prohibited = ["CEO-controlled", "CEO-sovereign", "Mainnet is live", "Bridge is active", "monetary value enabled"];
const failures = [];

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
    "Runtime Deployment in Progress",
    'href="https://jaios-governance.org/"',
    'class="jaios-institutional-link"',
    'href="https://explorer.jaios-governance.org/"',
    'class="public-explorer-link"',
    'src="/official-junca-symbol.png"',
    'class="header-explorer-link"',
    '<meta name="application-name" content="JUNCA Docs">',
    '<meta name="apple-mobile-web-app-title" content="JUNCA Docs">',
  ]) {
    if (!html.includes(required)) failures.push(`${route}: missing ${required}`);
  }
  for (const term of prohibited) {
    if (html.toLowerCase().includes(term.toLowerCase())) failures.push(`${route}: prohibited public claim ${term}`);
  }
}
const home = await readFile(join(dist, "index.html"), "utf8");
if (home.length > 90000) failures.push(`/: overview payload is too long (${home.length} bytes)`);
if (home.includes("codex-preview")) failures.push("/: development preview metadata remains");
for (const requiredInstallLink of [
  'rel="icon" href="https://docs.jaios-governance.org/icon-192.png"',
  'rel="icon" href="https://docs.jaios-governance.org/icon-192.png"',
  'rel="apple-touch-icon" href="https://docs.jaios-governance.org/apple-touch-icon.png"',
  'rel="manifest" href="https://docs.jaios-governance.org/manifest.webmanifest"',
]) {
  if (!home.includes(requiredInstallLink)) failures.push(`/: missing cache-busted install metadata ${requiredInstallLink}`);
}
for (const required of [
  "Chain Core",
  "Implemented / CI Verified",
  "AWS Runtime",
  "Pending Live Acceptance",
  "Assets Moved",
  "Revision · 2026.07.27 / R24",
]) {
  if (!home.includes(required)) failures.push(`/: missing release-state item ${required}`);
}
const cssName = (await readdir(join(dist, "assets"))).find((name) => /^index-.*\.css$/.test(name));
if (!cssName) failures.push("approved design stylesheet missing");
const css = cssName ? await readFile(join(dist, "assets", cssName), "utf8") : "";
for (const font of ["Cormorant Garamond", "Source Serif 4", "Inter", "Shuei Mincho", "Shuei Kaku Gothic"]) {
  if (!css.includes(font)) failures.push(`font stack missing ${font}`);
}
for (const required of [
  '--wordmark:"Optima LT Std Bold","Optima LT Std"',
  "font-family:var(--wordmark)",
  "font-weight:700",
  "font-synthesis:none",
]) {
  if (!css.includes(required)) failures.push(`formal wordmark typography missing ${required}`);
}
if (!css.includes(":focus-visible")) failures.push("keyboard focus style missing");
for (const required of [".release-status", ".finality-brief", ".developer-modules", ".evidence-tracks"]) {
  if (!css.includes(required)) failures.push(`approved design stylesheet missing ${required}`);
}
const protocol = await readFile(join(dist, "protocol", "index.html"), "utf8");
for (const required of [
  "Certified Finality and Validator Epoch Safety",
  "strict greater-than-two-thirds voting power",
  "Old-epoch validator proofs are rejected",
  "400 / 400 automated tests passed",
]) {
  if (!protocol.includes(required)) failures.push(`/protocol: missing ${required}`);
}
const implementation = await readFile(join(dist, "implementation", "index.html"), "utf8");
for (const required of [
  "Public Testnet Network Configuration",
  "Pending Runtime Binding",
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
  "34d838b8a59c",
  "/pull/51",
  "/pull/76",
  "30224301657",
  "30211341527",
  "30212766916",
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
await readFile(join(dist, "404.html"), "utf8");
await readFile(join(dist, "release-manifest.json"), "utf8");
await readFile(join(dist, "manifest.webmanifest"), "utf8");
const installManifest = JSON.parse(await readFile(join(dist, "manifest.webmanifest"), "utf8"));
if (installManifest.id !== "/") failures.push("install manifest identity must remain bound to the canonical root");
if (installManifest.short_name !== "JUNCA Docs") failures.push("install manifest short name must be JUNCA Docs");
for (const requiredIcon of [
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
]) {
  if (!installManifest.icons?.some((icon) => icon.src === requiredIcon)) {
    failures.push(`install manifest missing cache-busted official symbol ${requiredIcon}`);
  }
}
await readFile(join(dist, "icon-192.png"));
await readFile(join(dist, "icon-512.png"));
await readFile(join(dist, "icon-maskable-512.png"));
await readFile(join(dist, "apple-touch-icon.png"));
await readFile(join(dist, "junca-j-r21-192.png"));
await readFile(join(dist, "junca-j-r21-512.png"));
await readFile(join(dist, "junca-j-r21-maskable-512.png"));
await readFile(join(dist, "junca-j-r21-apple-touch.png"));
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
  ["junca-symbol-r20-192.png", "48db3873676c0b70969b47b067a51907d8b69bb2c6b231253bb83a767b7604f7"],
  ["junca-symbol-r20-512.png", "d93ca49d87da8098423d7afa2be3d4ec7af5a042c115e30896a20be55d1567c5"],
  ["junca-symbol-r20-maskable-512.png", "d93ca49d87da8098423d7afa2be3d4ec7af5a042c115e30896a20be55d1567c5"],
  ["junca-symbol-r20-apple-touch.png", "30aaf78297a8dd8077025eefc3d7b4bf613fd1ab955dd1d47858f9d797ecec88"],
  ["junca-j-r21-192.png", "6588f3699cc6d5d3c6fdf2ea557221e519d929063c4d12a9ffb3c2ef38265fdf"],
  ["junca-j-r21-512.png", "6a4dade831a4a9b6e72761a172b713ccddc8d904ab0f2fea34a17d5cf3993172"],
  ["junca-j-r21-maskable-512.png", "6a4dade831a4a9b6e72761a172b713ccddc8d904ab0f2fea34a17d5cf3993172"],
  ["junca-j-r21-apple-touch.png", "b851abc4eed6991b3dae2914422b9ae3ecb32913e85283dca1452e124248a675"],
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