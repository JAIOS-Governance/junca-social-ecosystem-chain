import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const target = path.join(root, 'snapshot', 'index.html');
let html = await fs.readFile(target, 'utf8');

const markerStart = '<!-- JSEC-CANONICAL-SEARCH-STATUS:START -->';
const markerEnd = '<!-- JSEC-CANONICAL-SEARCH-STATUS:END -->';
const existing = new RegExp(`${markerStart}[\\s\\S]*?${markerEnd}`, 'g');
html = html.replace(existing, '');

const replacements = new Map([
  ['Revision · 2026.07.28 / R30', 'Revision · 2026.08.06 / R37'],
  ['Public Testnet Endpoints Active', 'Governed Read-only Operations'],
  ['No Monetary Value', 'Protocol Validation Environment'],
  ['AWS Runtime Deployment in Progress', 'AWS Runtime Evidence-Gated'],
  ['Infrastructure binding and runtime acceptance remain open', 'Runtime publication is controlled by the canonical parity record.'],
  ['Validator Network Continuous Production Under Review', 'Validator Network Evidence-Gated'],
  ['Three-validator quorum and advancing head require live evidence', 'Validator values are displayed only when Health, Explorer and RPC parity is verified.'],
  ['No public endpoint is asserted', 'Current endpoint state is provided by the canonical runtime parity record.'],
  ['RPC parity and contract verification are not yet accepted', 'Explorer values are published only when canonical runtime parity is verified.'],
  ['Documentation Live · Network Public Services Restored', 'Documentation Live · Runtime Evidence Parity-Gated'],
  ['Current state: Core source verified · CI verified · public services restored · Public endpoint active.', 'Current state: Core source verified · CI verified · public runtime values are parity-gated.'],
  ['Public Services Restored', 'Parity-Gated Runtime Evidence'],
  ['Latest verified recovery evidence · 28 July 2026', 'Current values are issued only through the canonical runtime parity record'],
  ['Height 1', 'See runtime parity record'],
  ['Peer Count\n    0', 'Peer Count\n    See runtime parity record'],
  ['Under review · head at 1', 'Evidence-gated'],
  ['Public services restored. Continuous block production remains under review.', 'Runtime values are published only after Health, Explorer and RPC parity verification.'],
  ['Continuous block production and historical indexing remain under test. Mainnet, asset movement and bridge activation are not active.', 'Consult the canonical runtime parity record for current observable values. Mainnet Changed=false, Assets Moved=false and Bridge Activated=false.']
]);
for (const [from, to] of replacements) html = html.split(from).join(to);

html = html.replace(/<meta name="date-modified"[^>]*>\s*/gi, '');
html = html.replace(/<link rel="alternate" type="application\/json" href="\/runtime-parity\.json"[^>]*>\s*/gi, '');
html = html.replace(/<link rel="alternate" type="application\/json" href="\/network-registry\.json"[^>]*>\s*/gi, '');
html = html.replace('</head>', '<meta name="date-modified" content="2026-08-06"><link rel="alternate" type="application/json" href="/runtime-parity.json"><link rel="alternate" type="application/json" href="/network-registry.json"></head>');

const banner = `${markerStart}<section data-jsec-canonical-search-status="20260806-r37" style="background:#071827;color:#f4ead1;padding:1rem 1.25rem;border-bottom:1px solid #b89a5c;font-family:Inter,system-ui,sans-serif"><div style="width:min(1200px,100%);margin:auto"><strong>Current official identity / 現行公式情報</strong><p style="margin:.45rem 0">JUNCA Social Ecosystem Chain (JSEC) · Public Testnet / Governed Read-only Operations · Chain ID 20260723 (0x1352773)</p><p style="margin:.45rem 0">Mainnet Changed=false · Assets Moved=false · Bridge Activated=false</p><p style="margin:.45rem 0"><a href="/runtime-parity.json" style="color:#ead49e">Canonical runtime parity</a> · <a href="/network-registry/" style="color:#ead49e">Network registry and legacy chain-ID clarification</a> · <a href="/current-identity/" style="color:#ead49e">Current identity</a></p></div></section>${markerEnd}`;
html = html.replace(/<body([^>]*)>/i, `<body$1>${banner}`);

const prohibited = ['No Monetary Value', '金銭価値なし', '>PENDING<'];
for (const value of prohibited) {
  if (html.includes(value)) throw new Error(`Prohibited search-surface wording remains: ${value}`);
}
for (const required of ['20260806-r37', 'Chain ID 20260723', '/runtime-parity.json', '/network-registry/', 'Mainnet Changed=false']) {
  if (!html.includes(required)) throw new Error(`Required canonical search marker missing: ${required}`);
}
await fs.writeFile(target, html, 'utf8');
console.log('JSEC_SEARCH_SURFACE_NORMALIZED');
