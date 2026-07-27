import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const snapshot = join(root, "snapshot");
const dist = join(root, "dist");
const release = "2026.07.27";
const revision = "R24";
const chainSource = "f4fbc9fa39cbd8f1c4d57fea9bca86bb2afaf37d";
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const governanceFooter = '<div><span>Governance</span><strong>JAIOS Institutional Governance</strong></div>';
const governanceLink = [
  '<a class="jaios-institutional-link" href="https://jaios-governance.org/"',
  ' aria-label="Open the JAIOS Institutional Governance official website">',
  '<img src="/official-junca-symbol.png" alt="" width="48" height="48"/>',
  '<span><small>Governance</small><strong>JAIOS Institutional Governance</strong>',
  '<em>Official institutional website →</em></span></a>',
].join("");
const explorerLink = [
  '<a class="public-explorer-link" href="https://explorer.jaios-governance.org/"',
  ' aria-label="Open the JUNCA Social Ecosystem Chain Public Explorer">',
  '<span><small>Public Testnet</small><strong>Public Explorer</strong>',
  '<em>Read finalized network data →</em></span></a>',
].join("");
const headerExplorerLink = [
  '<a class="header-explorer-link" href="https://explorer.jaios-governance.org/"',
  ' aria-label="Open live JUNCA Social Ecosystem Chain Public Explorer">',
  '<span>Live Public Explorer</span><em>Finalized readback ↗</em></a>',
].join("");
const governanceLinkStyle = [
  '<style id="jaios-institutional-link-style">',
  '.site-header .header-explorer-link{display:flex;flex-direction:column;margin-left:auto;',
  'padding:.55rem .8rem;border:1px solid rgba(198,169,107,.45);color:inherit;text-decoration:none}',
  '.site-header .header-explorer-link span{font-size:.68rem;font-weight:700;color:#0b2a4b}',
  '.site-header .header-explorer-link em{font-size:.55rem;font-style:normal;color:#806a3c}',
  'footer .jaios-institutional-link{display:grid;grid-template-columns:48px 1fr;',
  'gap:.85rem;align-items:center;color:inherit;text-decoration:none;',
  'border:1px solid rgba(220,228,235,.18);padding:.8rem .9rem;',
  'transition:border-color .2s ease,background .2s ease}',
  'footer .jaios-institutional-link:hover,footer .jaios-institutional-link:focus-visible{',
  'border-color:#c6a96b;background:rgba(255,255,255,.05);outline:none}',
  'footer .jaios-institutional-link img{width:48px;height:48px;display:block}',
  'footer .jaios-institutional-link span{display:flex;flex-direction:column;gap:.18rem}',
  'footer .jaios-institutional-link small{color:#9dacba;text-transform:uppercase;',
  'letter-spacing:.08em;font-size:.61rem;font-style:normal}',
  'footer .jaios-institutional-link strong{color:#fff}',
  'footer .jaios-institutional-link em{color:#c6a96b;font-size:.65rem;font-style:normal}',
  'footer .public-explorer-link{display:flex;align-items:center;color:inherit;text-decoration:none;',
  'border:1px solid rgba(220,228,235,.18);padding:.8rem .9rem;',
  'transition:border-color .2s ease,background .2s ease}',
  'footer .public-explorer-link:hover,footer .public-explorer-link:focus-visible{',
  'border-color:#c6a96b;background:rgba(255,255,255,.05);outline:none}',
  'footer .public-explorer-link span{display:flex;flex-direction:column;gap:.18rem}',
  'footer .public-explorer-link small{color:#9dacba;text-transform:uppercase;',
  'letter-spacing:.08em;font-size:.61rem;font-style:normal}',
  'footer .public-explorer-link strong{color:#fff}',
  'footer .public-explorer-link em{color:#c6a96b;font-size:.65rem;font-style:normal}',
  '</style>',
].join("");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(snapshot, dist, { recursive: true });
for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  const source = await readFile(path, "utf8");
  if (!source.includes(governanceFooter)) {
    throw new Error(`Missing canonical governance footer in ${route}`);
  }
  await writeFile(
    path,
    source
      .replace("</head>", `${governanceLinkStyle}</head>`)
      .replace('<span class="badge badge-gold">Technical Reference</span>', `${headerExplorerLink}<span class="badge badge-gold">Technical Reference</span>`)
      .replace(governanceFooter, `${governanceLink}${explorerLink}`)
      .replaceAll("junca-j-r21.svg", "favicon.svg")
      .replaceAll("junca-j-r21-192.png", "icon-192.png")
      .replaceAll("junca-j-r21-apple-touch.png", "apple-touch-icon.png")
      .replaceAll("junca-j-r21.webmanifest", "manifest.webmanifest")
      .replaceAll("Revision · 2026.07.27 / R21", "Revision · 2026.07.27 / R24"),
    "utf8",
  );
}
const home404 = (await readFile(join(dist, "index.html"), "utf8"))
  .replace(/<title>[^<]*<\/title>/, "<title>Reference Not Found | JUNCA Social Ecosystem Chain</title>")
  .replace(/<link rel="canonical" href="[^"]+">/, '<link rel="canonical" href="https://docs.jaios-governance.org/404">');
await writeFile(join(dist, "404.html"), home404, "utf8");

const files = [];
async function register(path) {
  const data = await readFile(join(dist, path));
  files.push({
    path,
    bytes: data.length,
    sha256: createHash("sha256").update(data).digest("hex"),
  });
}

for (const route of routes) {
  await register(route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
}
async function registerTree(directory, prefix = "") {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const relative = join(prefix, entry.name);
    if (entry.isDirectory()) await registerTree(join(directory, entry.name), relative);
    else if (!files.some((file) => file.path === relative)) await register(relative);
  }
}
await registerTree(dist);

await writeFile(join(dist, "release-manifest.json"), `${JSON.stringify({
  schema: "junca-chain-docs-release/v2",
  release,
  revision,
  design_source: "Sites Version 15",
  chain_source_commit: chainSource,
  canonical_origin: "https://docs.jaios-governance.org",
  network_label: "Public Testnet / Runtime Deployment in Progress / No Monetary Value",
  runtime_status: "UNVERIFIED",
  public_endpoint_status: "PENDING",
  governance: "JAIOS Institutional Governance",
  routes,
  files,
}, null, 2)}\n`, "utf8");

console.log(`Built ${routes.length} canonical routes from the approved Version 15 design system, revision ${revision}`);
