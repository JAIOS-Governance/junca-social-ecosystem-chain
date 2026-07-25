import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const snapshot = join(root, "snapshot");
const dist = join(root, "dist");
const release = "2026.07.25";
const chainSource = "effe17badf6628b6ad5160062ca583501fe72b31";
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(snapshot, dist, { recursive: true });
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
for (const path of [
  "404.html",
  "robots.txt",
  "sitemap.xml",
  "favicon.svg",
  "assets/framework-CXnKph_e.js",
  "assets/index-1XiXncph.css",
  "assets/index-CQAqIo7E.js",
  "assets/layout-segment-context-DBXXpv6J.js",
  "assets/reference-CAhzOOHN.js",
  "assets/rolldown-runtime-S-ySWqyJ.js",
]) {
  await register(path);
}

await writeFile(join(dist, "release-manifest.json"), `${JSON.stringify({
  schema: "junca-chain-docs-release/v2",
  release,
  design_source: "Sites Version 15",
  chain_source_commit: chainSource,
  canonical_origin: "https://docs.jaios-governance.org",
  network_label: "Public Testnet / No Monetary Value",
  governance: "JAIOS Institutional Governance",
  routes,
  files,
}, null, 2)}\n`, "utf8");

console.log(`Built ${routes.length} canonical routes from the approved Version 15 design snapshot`);
