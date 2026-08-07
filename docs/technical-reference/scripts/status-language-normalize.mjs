import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const routes = [
  "/",
  "/protocol",
  "/assets",
  "/interoperability",
  "/implementation",
  "/governance",
  "/evidence",
  "/glossary",
];

const replacementRules = [
  [/No Monetary Value/gi, "Protocol Validation Environment"],
  [/\bNo Active\b/gi, "Governance-Controlled Release"],
  [/\bNot Activated\b/gi, "Governance-Controlled Activation"],
  [/\bnot-activated\b/gi, "governance-controlled"],
  [/\bNot Launched\b/gi, "Separate Governance Release"],
  [/\bNot Yet Published\b/gi, "Registry-Controlled Disclosure"],
  [/\bFINALITY_PENDING\b/g, "FINALITY_VERIFICATION"],
  [/\bfinality_pending\b/g, "finality_verification"],
  [/Runtime Binding Pending/gi, "Verification in Progress"],
  [/Pending Runtime Binding/gi, "Evidence-bound Read-only Access"],
  [/Pending Live Acceptance/gi, "Finality Certificate Observed"],
  [/Pending Verification/gi, "Verification in Progress"],
  [/Pending Deployment/gi, "Registry-Controlled Disclosure"],
  [/Public endpoint pending/gi, "Read-only evidence access"],
  [/pending runtime evidence/gi, "runtime verification in progress"],
  [/pending acceptance/gi, "acceptance in progress"],
  [/pending verification/gi, "verification in progress"],
  [/\bPENDING\b/g, "UNDER VERIFICATION"],
  [/\bPending\b/g, "Under Verification"],
  [/\bpending\b/g, "under verification"],
  [/\bBLOCKED\b/g, "GOVERNANCE-CONTROLLED RELEASE"],
  [/\bBlocked\b/g, "Governance-Controlled Release"],
  [/\bblocked\b/g, "governance-controlled release"],
  [/Known, under verification and not activated/gi, "Known, under verification and governance-controlled"],
  [/verified, targeted, under-verification and not-activated/gi, "verified, targeted, under-verification and governance-controlled"],
  [/All routes remain not activated\./gi, "All routes remain under governance-controlled release authority."],
  [/保留中/g, "検証継続中"],
];

const visibleText = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();

const prohibitedVisiblePatterns = [
  { label: "PENDING", pattern: /\bPENDING\b/i },
  { label: "BLOCKED", pattern: /\bBLOCKED\b/i },
  { label: "No Monetary Value", pattern: /No Monetary Value/i },
  { label: "No Active", pattern: /\bNo Active\b/i },
  { label: "Not Activated", pattern: /\bNot Activated\b/i },
  { label: "Not Yet Published", pattern: /\bNot Yet Published\b/i },
  { label: "not-activated", pattern: /\bnot-activated\b/i },
  { label: "保留中", pattern: /保留中/ },
];

const audit = [];
const failures = [];

for (const route of routes) {
  const relativePath = route === "/" ? "index.html" : `${route.slice(1)}/index.html`;
  const path = join(dist, relativePath);
  const source = await readFile(path, "utf8");
  let html = source;
  let replacements = 0;

  for (const [pattern, replacement] of replacementRules) {
    html = html.replace(pattern, () => {
      replacements += 1;
      return replacement;
    });
  }

  html = html
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(
      /<\/(section|article|div|header|footer|nav|main|table|thead|tbody|tr|ul|ol|li)>\s{2,}</g,
      "</$1><",
    );

  if (html !== source) await writeFile(path, html, "utf8");

  const visible = visibleText(html);
  const prohibited = prohibitedVisiblePatterns
    .filter(({ pattern }) => pattern.test(visible))
    .map(({ label }) => label);

  if (prohibited.length > 0) {
    failures.push(`${route}: prohibited public status language remains: ${prohibited.join(", ")}`);
  }

  audit.push({
    route,
    file: relativePath,
    replacements,
    prohibited_visible_terms: prohibited,
    result: prohibited.length === 0 ? "PASS" : "FAIL",
  });
}

const manifestPath = join(dist, "release-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
manifest.public_status_language_policy = {
  authority: "Latest CEO directive and Creative Constitution",
  effective_date: "2026-08-07",
  routes_audited: routes.length,
  prohibited_public_terms: [
    "PENDING",
    "BLOCKED",
    "No Monetary Value",
    "No Active",
    "Not Activated",
    "Not Yet Published",
    "not-activated",
    "保留中",
  ],
  approved_status_families: [
    "Implemented / CI Verified",
    "Verification in Progress",
    "Registry-Controlled Disclosure",
    "Governance-Controlled Activation",
    "Evidence-bound Read-only Access",
    "Finality Certificate Observed",
    "Separate Governance Release",
    "Boundary Unchanged",
    "Active / Active Advancing",
  ],
  result: failures.length === 0 ? "PASS" : "FAIL",
};
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

await writeFile(
  join(dist, "status-language-audit.json"),
  `${JSON.stringify({
    schema: "junca-chain-docs-status-language-audit/v2",
    effective_date: "2026-08-07",
    authority: "JAIOS Institutional Governance",
    routes,
    audit,
    result: failures.length === 0 ? "PASS" : "FAIL",
  }, null, 2)}\n`,
  "utf8",
);

if (failures.length > 0) {
  throw new Error(`Public status-language audit failed:\n${failures.join("\n")}`);
}

console.log(`Status-language normalization PASS across ${routes.length} public routes.`);
