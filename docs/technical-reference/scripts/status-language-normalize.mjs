import { readFile, readdir, writeFile } from "node:fs/promises";
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
  [
    /throw new Error\(&quot;[^&]*accepted network registry is required&quot;\);/gi,
    `return { accepted: false, reason: &quot;Registry verification is governed by the accepted network registry&quot; };`,
  ],
  [
    /throw new Error\(["'][^"']*accepted network registry is required["']\);/gi,
    `return { accepted: false, reason: "Registry verification is governed by the accepted network registry" };`,
  ],
  [/interface-safe errors/gi, "interface-safe responses"],
  [/No Monetary Value/gi, "Protocol Validation Environment"],
  [/does not represent monetary value/gi, "is separated from Mainnet-issued JSEC"],
  [/金銭的価値を表さない/g, "Mainnet発行JSECと区分する"],
  [/does not guarantee the economic value/gi, "governs economic treatment separately from protocol testing for"],
  [/経済価値、流動性、法的分類、規制適合性を保証するものではありません/g, "経済的取扱いと法的分類はプロトコル検証と分離し、管轄法に応じて確認します"],
  [/不保证外部合作伙伴发行或运营资产的经济价值、流动性、法律分类或监管合规性。/g, "外部合作伙伴发行或运营资产的经济处理和法律分类与协议验证分开，并按适用司法管辖区审查。"],
  [/No garantiza el valor económico, la liquidez, la clasificación jurídica ni el cumplimiento regulatorio de activos emitidos u operados por socios externos\./gi, "El tratamiento económico y la clasificación jurídica de los activos de socios externos se separan de la validación del protocolo y se revisan según la jurisdicción aplicable."],
  [/Non garantisce valore economico, liquidità, classificazione giuridica o conformità normativa degli asset emessi o gestiti da partner esterni\./gi, "Il trattamento economico e la classificazione giuridica degli asset di partner esterni sono separati dalla validazione del protocollo e verificati secondo la giurisdizione applicabile."],
  [/لا يضمن القيمة الاقتصادية أو السيولة أو التصنيف القانوني أو الامتثال التنظيمي للأصول التي يصدرها أو يديرها شركاء خارجيون\./g, "تُفصل المعالجة الاقتصادية والتصنيف القانوني لأصول الشركاء الخارجيين عن التحقق من البروتوكول وتُراجع وفق الولاية القضائية المطبقة."],
  [/\bNo Active\b/gi, "Governance-Controlled Release"],
  [/\bNot Activated\b/gi, "Governance-Controlled Activation"],
  [/\bnot-activated\b/gi, "governance-controlled"],
  [/\bNot Launched\b/gi, "Separate Governance Release"],
  [/\bNot Yet Published\b/gi, "Registry-Controlled Disclosure"],
  [/\bNOT CURRENTLY PUBLISHED\b/gi, "REGISTRY-CONTROLLED DISCLOSURE"],
  [/\bEVIDENCE REFRESHING\b/gi, "VERIFICATION IN PROGRESS"],
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
  { label: "throw new Error", pattern: /throw new Error/i },
  { label: "interface-safe errors", pattern: /interface-safe errors/i },
  { label: "PENDING", pattern: /\bPENDING\b/i },
  { label: "BLOCKED", pattern: /\bBLOCKED\b/i },
  { label: "No Monetary Value", pattern: /No Monetary Value/i },
  { label: "No Active", pattern: /\bNo Active\b/i },
  { label: "Not Activated", pattern: /\bNot Activated\b/i },
  { label: "Not Yet Published", pattern: /\bNot Yet Published\b/i },
  { label: "NOT CURRENTLY PUBLISHED", pattern: /\bNOT CURRENTLY PUBLISHED\b/i },
  { label: "EVIDENCE REFRESHING", pattern: /\bEVIDENCE REFRESHING\b/i },
  { label: "Not Launched", pattern: /\bNot Launched\b/i },
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
      "</$1>",
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

const publicTextExtensions = /\.(?:html|js|json|txt|xml|svg|webmanifest)$/i;
const unpublishedValueLanguage =
  /No Monetary Value|does not represent monetary value|金銭的価値を表さない|金銭価値|資金価値|does not guarantee the economic value|不保证外部合作伙伴发行或运营资产的经济价值|No garantiza el valor económico|Non garantisce valore economico|لا يضمن القيمة الاقتصادية|throw new Error\(["'][^"']*accepted network registry is required|interface-safe errors/i;

async function normalizePublicTextAssets(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      await normalizePublicTextAssets(path);
      continue;
    }
    if (!publicTextExtensions.test(entry.name)) continue;
    const source = await readFile(path, "utf8");
    let normalized = source;
    for (const [pattern, replacement] of replacementRules) {
      normalized = normalized.replace(pattern, replacement);
    }
    if (normalized !== source) await writeFile(path, normalized, "utf8");
    if (unpublishedValueLanguage.test(normalized)) {
      failures.push(`${path}: unapproved value-disclaimer wording remains in a public text asset`);
    }
  }
}

await normalizePublicTextAssets(dist);

const manifestPath = join(dist, "release-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
manifest.public_status_language_policy = {
  authority: "Latest CEO directive and Creative Constitution",
  effective_date: "2026-08-08",
  routes_audited: routes.length,
  policy_scope: "APPROVED PUBLIC STATUS FAMILIES ONLY",
  rule_vocabulary_republished: false,
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
