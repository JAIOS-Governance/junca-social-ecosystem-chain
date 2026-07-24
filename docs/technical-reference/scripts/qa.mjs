import { readFile } from "node:fs/promises";
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
  for (const required of [
    `<link rel="canonical" href="${canonical}">`,
    `<meta property="og:url" content="${canonical}">`,
    "JUNCA Social Ecosystem Chain",
    "JAIOS Institutional Governance",
    "Public Testnet"
  ]) {
    if (!html.includes(required)) failures.push(`${route}: missing ${required}`);
  }
  for (const term of prohibited) {
    if (html.toLowerCase().includes(term.toLowerCase())) failures.push(`${route}: prohibited public claim ${term}`);
  }
}
const home = await readFile(join(dist, "index.html"), "utf8");
if (home.length > 22000) failures.push(`/: overview is too long (${home.length} bytes)`);
const css = await readFile(join(dist, "assets", "styles.css"), "utf8");
for (const font of ["Cormorant Garamond", "Source Serif 4", "Inter", "Shuei Mincho", "Shuei Kaku Gothic"]) {
  if (!css.includes(font)) failures.push(`font stack missing ${font}`);
}
if (!css.includes(":focus-visible")) failures.push("keyboard focus style missing");
const sitemap = await readFile(join(dist, "sitemap.xml"), "utf8");
for (const route of routes) {
  const url = `${origin}${route === "/" ? "/" : route}`;
  if (!sitemap.includes(`<loc>${url}</loc>`)) failures.push(`sitemap missing ${url}`);
}
if (!(await readFile(join(dist, "robots.txt"), "utf8")).includes("Allow: /")) failures.push("robots.txt does not allow production indexing");
await readFile(join(dist, "404.html"), "utf8");
await readFile(join(dist, "release-manifest.json"), "utf8");
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
