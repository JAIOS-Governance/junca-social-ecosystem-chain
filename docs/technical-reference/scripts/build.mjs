import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  renderSecondaryLanguageRuntime,
  secondaryLanguageMeta,
  secondaryTranslationIndex,
} from "../src/secondary-language.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const snapshot = join(root, "snapshot");
const dist = join(root, "dist");
const release = "2026.07.28";
const revision = "R31";
const chainSource = "6de0979b97254c5b4777ede8c82378fd4e143137";
const observedAt = "2026-07-28T15:44:23.017334+00:00";
const officialWordmarkSource = join(root, "..", "..", "jaios", "social_ecosystem_chain", "assets", "junca-chain-logo-gold-on-navy.png");
const routes = ["/", "/protocol", "/assets", "/interoperability", "/implementation", "/governance", "/evidence", "/glossary"];
const secondaryIndex = secondaryTranslationIndex();
const secondaryLanguageToolbar = [
  '<div class="secondary-language-toolbar" aria-label="Secondary-language display settings">',
  '<div><span>Secondary language</span><small>English remains the fixed primary language.</small></div>',
  '<label for="secondary-language-select">Select secondary language</label>',
  '<select id="secondary-language-select" name="secondary-language">',
  ...Object.entries(secondaryLanguageMeta).map(
    ([value, { label }]) => `<option value="${value}">${label}</option>`,
  ),
  '</select></div>',
].join("");

function decorateSecondaryCopy(html, route) {
  let count = 0;
  const decorated = html.replace(
    /<([a-z][\w-]*)([^>]*\blang="ja"[^>]*)>([\s\S]*?)<\/\1>/gi,
    (match, tag, attributes, japanese) => {
      if (/<[^>]+>/.test(japanese)) {
        throw new Error(`${route}: secondary-language element contains unsupported nested markup`);
      }
      const record = secondaryIndex.get(japanese);
      if (!record) {
        throw new Error(`${route}: missing static secondary-language translation for ${japanese}`);
      }
      count += 1;
      return `<${tag}${attributes} data-secondary-copy data-secondary-key="${record.key}">${japanese}</${tag}>`;
    },
  );
  if (count === 0) throw new Error(`${route}: no authored secondary-language copy found`);
  return decorated;
}
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
const runtimePanel = [
  '<section class="live-runtime-evidence" aria-labelledby="live-runtime-evidence-title">',
  '<div class="runtime-evidence-heading"><span class="runtime-live-mark"><i aria-hidden="true"></i>Governed readback</span>',
  '<small>Public Testnet · Read-only · No Monetary Value</small>',
  '<h2 id="live-runtime-evidence-title">Verified operational evidence, presented without inference.</h2>',
  '<p lang="ja">実測済みの運用証跡を、推測を加えずに表示します。</p>',
  `<p>Explorer snapshot observed · ${observedAt}</p></div>`,
  '<dl><div><dt>Network</dt><dd>VERIFIED</dd></div>',
  '<div><dt>Runtime</dt><dd>READY · READ-ONLY</dd></div>',
  '<div><dt>Finality</dt><dd>3 / 3</dd></div>',
  '<div><dt>Finalized Height</dt><dd>1</dd></div>',
  '<div><dt>Chain ID</dt><dd>20260723</dd></div>',
  '<div><dt>Transactions</dt><dd>0</dd></div>',
  '<div><dt>Peer Count</dt><dd>0</dd></div>',
  '<div><dt>Block Timestamp</dt><dd>NOT CURRENTLY PUBLISHED</dd></div></dl>',
  '<p class="live-runtime-boundary">The block timestamp is not currently published in this evidence view. This status does not indicate a runtime error. ',
  'Mainnet Changed: false · Assets Moved: false · Bridge Activated: false · Mainnet Activation Authorized: false.</p>',
  '<div class="runtime-evidence-actions"><a href="https://chain.jaios-governance.org/api/operational">Operational API ↗</a>',
  '<a href="https://explorer.jaios-governance.org/explorer.json">Explorer JSON ↗</a></div>',
  '</section>',
].join("");
const developmentGovernancePanel = [
  '<section class="development-governance" aria-labelledby="development-governance-title">',
  '<header><small>Development governance</small>',
  '<h2 id="development-governance-title">Canonical foundation and auxiliary gateway are explicitly separated.</h2>',
  '<p lang="ja">正規開発基盤と補助ゲートウェイを明確に分離して表示します。</p></header>',
  '<div class="development-governance-grid">',
  '<article><span>Canonical protocol development foundation</span><strong>PR #237 · MERGED</strong>',
  '<p>Reproducible blockchain protocol development environment merged to main.</p>',
  '<p lang="ja">再現可能なブロックチェーン開発環境を正規基盤としてmainへ統合済みです。</p>',
  '<a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/237">Inspect PR #237 ↗</a></article>',
  '<article><span>Auxiliary read-only capability</span><strong>PR #236 · OPEN DRAFT</strong>',
  '<p>Custom GPT Gateway remains auxiliary, unmerged and not deployed or registered.</p>',
  '<p lang="ja">Custom GPT Gatewayは補助機能であり、未統合・未配置・未登録です。</p>',
  '<a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/236">Inspect PR #236 ↗</a></article>',
  '</div></section>',
].join("");
const relationshipRail = [
  '<nav class="site-relationship-rail" aria-label="JUNCA official digital estate">',
  '<a href="https://jaios-governance.org/"><span>Governance</span><strong>JAIOS Institutional Governance</strong></a>',
  '<a href="https://chain.jaios-governance.org/"><span>Chain Product</span><strong>Operational Hub</strong></a>',
  '<a href="https://docs.jaios-governance.org/" aria-current="page"><span>Technical Reference</span><strong>JUNCA Chain Docs</strong></a>',
  '<a href="https://explorer.jaios-governance.org/"><span>Public Evidence</span><strong>Explorer</strong></a>',
  '<a href="https://github.com/JAIOS-Governance/junca-social-ecosystem-chain"><span>Source</span><strong>GitHub Repository</strong></a>',
  '</nav>',
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
  '.live-runtime-evidence{position:relative;overflow:hidden;margin:3rem auto;padding:2.2rem;max-width:1180px;',
  'background:linear-gradient(135deg,#061426 0%,#0b2038 62%,#122b45 100%);color:#fff;',
  'border:1px solid rgba(198,169,107,.68);box-shadow:0 24px 64px rgba(4,17,32,.22),inset 0 1px rgba(255,255,255,.05)}',
  '.live-runtime-evidence:before{content:"";position:absolute;inset:0 0 auto;height:3px;',
  'background:linear-gradient(90deg,#991b1b,#c6a96b,#f0d89b)}',
  '.live-runtime-evidence h2{margin:.45rem 0;font-family:var(--serif,serif);font-size:clamp(2rem,4vw,4rem)}',
  '.live-runtime-evidence small,.live-runtime-evidence dt{color:#c6a96b;text-transform:uppercase;letter-spacing:.08em}',
  '.runtime-live-mark{display:inline-flex;align-items:center;gap:.55rem;margin:0 0 .8rem;color:#f0d89b;',
  'font-size:.65rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase}',
  '.runtime-live-mark i{width:.55rem;height:.55rem;border-radius:50%;background:#7de0b5;',
  'box-shadow:0 0 0 .3rem rgba(125,224,181,.12),0 0 1rem rgba(125,224,181,.55)}',
  '.live-runtime-evidence dl{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin:2rem 0;background:transparent}',
  '.live-runtime-evidence dl div{padding:1rem;background:rgba(5,19,35,.72);border:1px solid rgba(198,169,107,.22)}',
  '.live-runtime-evidence dt{font-size:.61rem}',
  '.live-runtime-evidence dd{margin:.35rem 0 0;font-weight:700}.live-runtime-evidence a{color:#c6a96b}',
  '.live-runtime-boundary{color:#a9b5c4}.live-runtime-evidence>p{max-width:780px}',
  '.runtime-evidence-actions{display:flex;flex-wrap:wrap;gap:.8rem}.runtime-evidence-actions a{',
  'display:inline-flex;padding:.72rem .9rem;border:1px solid rgba(198,169,107,.45);text-decoration:none}',
  '.development-governance{margin:3rem auto;padding:2.2rem;max-width:1180px;border:1px solid #d7c79f;background:#fbf8f0}',
  '.development-governance header>small{color:#806a3c;text-transform:uppercase;letter-spacing:.1em}',
  '.development-governance h2{max-width:900px;margin:.45rem 0;font-family:var(--serif,serif);font-size:clamp(1.8rem,3.5vw,3.4rem)}',
  '.development-governance-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-top:1.5rem}',
  '.development-governance-grid article{padding:1.25rem;background:#fff;border:1px solid #ded7c7;box-shadow:0 12px 30px rgba(15,35,55,.06)}',
  '.development-governance-grid article>span{display:block;color:#806a3c;font-size:.65rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}',
  '.development-governance-grid strong{display:block;margin:.55rem 0;color:#0b2a4b;font-size:1.25rem}',
  '.development-governance-grid a{color:#755d27;font-weight:700}',
  '.site-relationship-rail{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;margin:3rem auto;max-width:1180px;background:#d5dce3;border:1px solid #d5dce3}',
  '.site-relationship-rail a{display:flex;min-height:88px;flex-direction:column;justify-content:center;padding:.85rem;background:#fff;color:#0b2a4b;text-decoration:none}',
  '.site-relationship-rail span{color:#806a3c;font-size:.58rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}',
  '.site-relationship-rail strong{margin-top:.25rem;font-size:.78rem}',
  '.site-relationship-rail a:focus-visible,.site-relationship-rail a:hover{outline:none;background:#fbf8f0}',
  'body.docs-menu-open{overflow:hidden}',
  '@media(max-width:760px){.live-runtime-evidence{margin:1.5rem;padding:1.4rem}.live-runtime-evidence dl{grid-template-columns:repeat(2,1fr)}}',
  '@media(max-width:760px){.development-governance{margin:1.5rem;padding:1.4rem}.development-governance-grid{grid-template-columns:1fr}',
  '.site-relationship-rail{grid-template-columns:1fr;margin:1.5rem}.site-relationship-rail a{min-height:70px}}',
  '.wordmark{min-width:0;display:block}.wordmark img{display:block;width:190px;max-width:100%;height:auto;object-fit:contain}',
  '.documentation-nav-head .official-brand-lockup{display:block}.documentation-nav-head .official-brand-lockup img{width:200px;height:auto}',
  '.documentation-nav-head .official-brand-lockup span{display:block;margin-top:.65rem}',
  '.hero .official-product-name img{width:min(410px,78vw);height:auto;margin-bottom:1rem}',
  '.hero .official-product-name span{display:block}',
  '.footer-brand-lockup{display:flex;flex-direction:column;gap:.55rem}.footer-brand-lockup img{width:190px;height:auto}',
  '.footer-brand-lockup span{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase}',
  '.secondary-language-toolbar{display:flex;align-items:center;justify-content:flex-end;gap:.9rem;',
  'padding:.65rem max(1rem,calc((100vw - 1180px)/2));border-block:1px solid #dfe4e8;background:#f7f5ef;color:#0b2a4b}',
  '.secondary-language-toolbar>div{display:flex;flex-direction:column}.secondary-language-toolbar span{font-size:.72rem;font-weight:800}',
  '.secondary-language-toolbar small{color:#667486;font-size:.62rem}.secondary-language-toolbar label{position:absolute;',
  'width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.secondary-language-toolbar select{min-width:8.5rem;',
  'min-height:2.5rem;padding:.4rem 2rem .4rem .65rem;border:1px solid #c6a96b;background:#fff;color:#0b2a4b;font:inherit}',
  '.secondary-language-toolbar select:focus-visible{outline:2px solid #8a6d2f;outline-offset:2px}',
  '[data-secondary-copy][dir="rtl"]{direction:rtl;text-align:right;unicode-bidi:isolate}',
  '@media(max-width:560px){.secondary-language-toolbar{align-items:stretch;flex-direction:column;gap:.5rem;',
  'padding:.75rem 1rem}.secondary-language-toolbar select{width:100%}}',
  '@media(width<=720px){.site-header{display:grid!important;grid-template-columns:minmax(0,1fr) 48px!important;gap:.5rem;min-height:82px;padding:.8rem 1rem!important}',
  '.site-header .header-explorer-link{display:none!important}.wordmark{overflow:hidden}',
  '.wordmark img{width:132px;max-width:44vw}.site-header .header-title,.site-header>.badge{display:none!important}',
  '.menu-toggle{width:48px;height:48px;margin:0!important;padding:0!important;justify-self:end;display:grid!important;place-items:center}',
  '.menu-toggle span:last-child{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}',
  '.menu-toggle span:first-child{font-size:1.5rem;line-height:1}',
  '.hero .official-product-name img{width:min(300px,82vw)}.official-product-name span{font-size:.72em}}',
  '</style>',
].join("");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(snapshot, dist, { recursive: true });
for (const retiredAsset of [
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
]) {
  await rm(join(dist, retiredAsset), { force: true });
}
await cp(officialWordmarkSource, join(dist, "junca-chain-official-wordmark.png"));
await cp(
  join(snapshot, "official-brand-lockup-r29.js"),
  join(dist, "official-brand-lockup-r31.js"),
);
await cp(join(root, "src", "docs-controls.js"), join(dist, "docs-controls-r31.js"));
await writeFile(
  join(dist, "secondary-language.js"),
  `${renderSecondaryLanguageRuntime()}\n`,
  "utf8",
);
await cp(join(snapshot, "icon-192.png"), join(dist, "favicon.ico"));
await rm(join(dist, "official-brand-lockup-r29.js"));
for (const route of routes) {
  const path = join(dist, route === "/" ? "index.html" : `${route.slice(1)}/index.html`);
  const source = await readFile(path, "utf8");
  if (!source.includes(governanceFooter)) {
    throw new Error(`Missing canonical governance footer in ${route}`);
  }
  const decorated = decorateSecondaryCopy(
    source
      .replace('<a href="/" class="wordmark" aria-label="JUNCA Social Ecosystem Chain home"><span>JUNCA Social Ecosystem Chain</span></a>', '<a href="/" class="wordmark" aria-label="JUNCA Social Ecosystem Chain home"><img src="/junca-chain-official-wordmark.png?v=20260728-r31" alt="JUNCA" width="190" height="57"></a>')
      .replace('<div class="documentation-nav-head"><p>Contents / 目次</p><strong>JUNCA Social Ecosystem Chain</strong>', '<div class="documentation-nav-head"><p>Contents / 目次</p><strong class="official-brand-lockup"><img src="/junca-chain-official-wordmark.png?v=20260728-r31" alt="JUNCA" width="200" height="60"><span>Social Ecosystem Chain</span></strong>')
      .replace('<h1>JUNCA Social Ecosystem Chain</h1>', '<h1 class="official-product-name"><img src="/junca-chain-official-wordmark.png?v=20260728-r31" alt="JUNCA" width="410" height="123"><span>Social Ecosystem Chain</span></h1>')
      .replace("</head>", `<meta name="application-name" content="JUNCA Docs"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="JUNCA Docs"><link rel="icon" href="/favicon.ico" sizes="any">${governanceLinkStyle}<script defer src="/secondary-language.js?v=20260728-r31"></script></head>`)
      .replace('<span class="badge badge-gold">Technical Reference</span>', `${headerExplorerLink}<span class="badge badge-gold">Technical Reference</span>`)
      .replace("</header>", `</header>${secondaryLanguageToolbar}`)
      .replace(governanceFooter, `${governanceLink}${explorerLink}`)
      .replace("<footer", `${relationshipRail}${developmentGovernancePanel}${runtimePanel}<footer`)
      .replaceAll("junca-j-r21.svg", "icon-192.png")
      .replaceAll('icon-192.png" type="image/svg+xml"', 'icon-192.png" type="image/png"')
      .replaceAll("junca-j-r21-192.png", "icon-192.png")
      .replaceAll("junca-j-r21-apple-touch.png", "apple-touch-icon.png")
      .replaceAll("junca-j-r21.webmanifest", "manifest.webmanifest")
      .replaceAll("Revision · 2026.07.27 / R21", "Revision · 2026.07.28 / R31")
      .replaceAll("20260727-r29", "20260728-r31")
      .replaceAll("official-brand-lockup-r29.js", "official-brand-lockup-r31.js")
      .replaceAll('"dateModified":"2026-07-27"', '"dateModified":"2026-07-28"')
      .replaceAll('"version":"2026.07.27-R21"', '"version":"2026.07.28-R31"')
      .replaceAll('"inLanguage":["en","ja"]', '"inLanguage":["en","ja","zh-Hans","es","it","ar"]')
      .replaceAll("Runtime Deployment in Progress", "Governed Read-only Operations")
      .replaceAll("Pending Live Acceptance", "Finality Certificate Observed")
      .replaceAll("Pending Runtime Binding", "Evidence-bound Read-only Access")
      .replaceAll("Runtime Unverified", "Operational Evidence Available")
      .replaceAll("Runtime unverified", "operational evidence available")
      .replaceAll("Public endpoint pending", "Read-only evidence access")
      .replaceAll("Pending Verification", "Verification in Progress")
      .replaceAll("Pending verification", "Verification in progress")
      .replaceAll("Pending Deployment", "Not Yet Published")
      .replaceAll("Runtime Binding Pending", "Verification in Progress")
      .replaceAll("pending verification", "verification in progress")
      .replaceAll("pending acceptance", "acceptance in progress")
      .replaceAll("pending runtime evidence", "runtime verification in progress")
      .replaceAll("Known, pending and blocked", "Known, under verification and blocked")
      .replaceAll("verified, targeted, pending and blocked", "verified, targeted, under-verification and blocked")
      .replaceAll("Verified, targeted, pending and blocked", "Verified, targeted, under-verification and blocked")
      .replaceAll("Meaning of verified, targeted, pending and blocked", "Meaning of verified, targeted, under-verification and blocked")
      .replaceAll("FINALITY_PENDING", "FINALITY_VERIFICATION")
      .replaceAll("finality_pending", "finality_verification")
      .replaceAll("保留中", "検証継続中")
      .replaceAll("No public endpoint is asserted", "Read-only evidence access is available; transaction submission remains disabled")
      .replaceAll("Three-validator quorum and advancing head require live evidence", "Three-validator finality quorum is observed; advancing-head activity is reported separately")
      .replaceAll("RPC parity and contract verification are not yet accepted", "Explorer and RPC evidence remain read-only and independently inspectable")
      .replaceAll("Continuous Production Under Review", "Read-only Runtime Snapshot")
      .replaceAll("Deployment in Progress", "Read-only Operations")
      .replaceAll("Under review · head at 1", "Finalized snapshot · height 1")
      .replaceAll("400 / 400 automated tests passed", "Developer Environment CI verified")
      .replaceAll("自動QA 400件すべてPASS", "開発環境CIの検証証跡を確認済み")
      .replace('<tr><td>Chain ID</td><td>Evidence-bound Read-only Access</td><td>Candidate values are not public wallet configuration</td></tr>', '<tr><td>Chain ID</td><td><code>20260723</code></td><td>Verified operational readback; wallet registration remains separately governed</td></tr>')
      .replace('<tr><td>Public RPC URL</td><td>Evidence-bound Read-only Access</td><td>HTTPS endpoint and method allow-list require acceptance</td></tr>', '<tr><td>Public RPC URL</td><td>Read-only policy</td><td>Transaction submission is disabled; use the Operational API for published status</td></tr>')
      .replace('<tr><td>WebSocket URL</td><td>Evidence-bound Read-only Access</td><td>Subscription boundary and rate limits require acceptance</td></tr>', '<tr><td>WebSocket URL</td><td>Not published in this reference</td><td>No endpoint is inferred from implementation state</td></tr>')
      .replace('<tr><td>Explorer URL</td><td>Evidence-bound Read-only Access</td><td>Canonical RPC parity and verification workflow require acceptance</td></tr>', '<tr><td>Explorer URL</td><td><a href="https://explorer.jaios-governance.org/">explorer.jaios-governance.org</a></td><td>Finalized, read-only public evidence surface</td></tr>')
      .replace('<tr><td>Currency Symbol</td><td>Evidence-bound Read-only Access</td><td>No test asset symbol is asserted before registry approval</td></tr>', '<tr><td>Currency Symbol</td><td>Not asserted</td><td>No test asset symbol is published before registry approval</td></tr>')
      .replace('<tr><td>Faucet URL</td><td>Evidence-bound Read-only Access</td><td>Rate limits and auditable issuance require acceptance</td></tr>', '<tr><td>Faucet URL</td><td>Not asserted</td><td>No faucet endpoint is published without auditable issuance controls</td></tr>')
      .replace('<tr><td>Genesis Hash</td><td>Evidence-bound Read-only Access</td><td>Must match the deployed canonical genesis</td></tr>', '<tr><td>Genesis Hash</td><td>Not published in this reference</td><td>No value is inferred; it must match the deployed canonical genesis</td></tr>')
      .replace('<tr><td>Finality Policy</td><td>Certified finality / strict &gt;2/3 voting power</td><td>Implemented in source; runtime evidence pending</td></tr>', '<tr><td>Finality Policy</td><td>Certified finality · 3 / 3 observed</td><td>Verified against the current read-only Explorer snapshot</td></tr>')
      .replaceAll("34d838b8a59c", "052598647079")
      .replaceAll("052598647079", "6de0979b9725")
      .replaceAll("https://docs.jaios-governance.org/icon-192.png", "https://docs.jaios-governance.org/icon-192.png?v=20260728-r31")
      .replaceAll("https://docs.jaios-governance.org/apple-touch-icon.png", "https://docs.jaios-governance.org/apple-touch-icon.png?v=20260728-r31")
      .replaceAll("https://docs.jaios-governance.org/manifest.webmanifest", "https://docs.jaios-governance.org/manifest.webmanifest?v=20260728-r31")
      .replace("</body>", '<script defer src="/docs-controls-r31.js?v=20260728-r31"></script></body>'),
    route,
  );
  await writeFile(path, decorated, "utf8");
}
const installManifestPath = join(dist, "manifest.webmanifest");
const installManifest = JSON.parse(await readFile(installManifestPath, "utf8"));
for (const icon of installManifest.icons) {
  icon.src = icon.src.replace(/\?v=.*$/, "?v=20260728-r31");
}
await writeFile(
  installManifestPath,
  `${JSON.stringify(installManifest, null, 2)}\n`,
  "utf8",
);
const sitemapPath = join(dist, "sitemap.xml");
await writeFile(
  sitemapPath,
  (await readFile(sitemapPath, "utf8")).replaceAll("<lastmod>2026-07-27</lastmod>", "<lastmod>2026-07-28</lastmod>"),
  "utf8",
);
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
  network_label: "Public Testnet / Read-only / Finalized / No Monetary Value",
  runtime_status: "VERIFIED_READY_READ_ONLY",
  public_endpoint_status: "ACTIVE_READ_ONLY",
  runtime_evidence: {
    observed_at: observedAt,
    network: "VERIFIED",
    runtime: "READY_READ_ONLY",
    finality: "CERTIFICATE_OBSERVED",
    finalized_height: 1,
    signed_power: 3,
    total_power: 3,
    chain_id: 20260723,
    transaction_count: 0,
    peer_count: 0,
    block_timestamp: "NOT_CURRENTLY_PUBLISHED",
    block_timestamp_public_label: "NOT CURRENTLY PUBLISHED",
    block_timestamp_public_label_ja: "現在は公開対象外",
    block_activity_conclusion: "NOT_INFERRED_FROM_FINALIZED_HEIGHT",
    source_evidence: {
      operational_api: "https://chain.jaios-governance.org/api/operational",
      explorer_json: "https://explorer.jaios-governance.org/explorer.json",
      exact_commit: chainSource,
      repository_workflow: "https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/actions/runs/30373515280",
    },
    mainnet_changed: false,
    assets_moved: false,
    bridge_activated: false,
    mainnet_activation_authorized: false,
  },
  development_governance: {
    canonical_foundation: {
      pull_request: 237,
      state: "MERGED",
      commit: chainSource,
      url: "https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/237",
    },
    auxiliary_gateway: {
      pull_request: 236,
      state: "OPEN_DRAFT_UNMERGED_UNDEPLOYED",
      url: "https://github.com/JAIOS-Governance/junca-social-ecosystem-chain/pull/236",
    },
  },
  governance: "JAIOS Institutional Governance",
  routes,
  files,
}, null, 2)}\n`, "utf8");

console.log(`Built ${routes.length} canonical routes from the approved Version 15 design system, revision ${revision}`);
