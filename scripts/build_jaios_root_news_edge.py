#!/usr/bin/env python3
"""Inject governed institutional-trust and six-card News surfaces into JAIOS root HTML.

The upstream HTML is preserved byte-for-byte except for insertions immediately
before </head> and </body>. Browser patches add the institutional-trust section
and replace only the existing Global Observatory section after framework
hydration when necessary.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

RELEASE = "20260804-six-card-news"
TRUST_RELEASE = "20260804-institutional-trust"


def visual_svg(kind: str, title: str) -> str:
    motifs = {
        "infrastructure": "<path d='M80 220h480M140 170h360M200 120h240' stroke='#d7bd78' stroke-width='3'/><circle cx='160' cy='220' r='18'/><circle cx='320' cy='170' r='18'/><circle cx='480' cy='220' r='18'/>",
        "ai": "<circle cx='320' cy='180' r='92' fill='none' stroke='#d7bd78' stroke-width='3'/><path d='M320 72v216M212 180h216M244 104l152 152M396 104L244 256' stroke='#d7bd78' stroke-width='2'/>",
        "government": "<path d='M120 245h400M155 225h330M190 115h260L320 70zM205 130v90M270 130v90M370 130v90M435 130v90' stroke='#d7bd78' stroke-width='3' fill='none'/>",
        "blockchain": "<g fill='none' stroke='#d7bd78' stroke-width='3'><rect x='115' y='100' width='120' height='80'/><rect x='405' y='100' width='120' height='80'/><rect x='260' y='210' width='120' height='80'/><path d='M235 140h170M205 180l75 45M435 180l-75 45'/></g>",
        "interoperability": "<g fill='none' stroke='#d7bd78' stroke-width='3'><circle cx='190' cy='180' r='76'/><circle cx='450' cy='180' r='76'/><path d='M266 150h108l-28-26M374 210H266l28 26'/></g>",
        "finance": "<path d='M105 245h430M150 220l90-75 75 42 110-102 75 46' stroke='#d7bd78' stroke-width='4' fill='none'/><g fill='#d7bd78'><circle cx='150' cy='220' r='8'/><circle cx='240' cy='145' r='8'/><circle cx='315' cy='187' r='8'/><circle cx='425' cy='85' r='8'/><circle cx='500' cy='131' r='8'/></g>",
    }
    motif = motifs[kind]
    safe_title = html.escape(title)
    return f"""<svg viewBox='0 0 640 360' role='img' aria-label='{safe_title}' xmlns='http://www.w3.org/2000/svg'>
      <defs><linearGradient id='g-{kind}' x1='0' y1='0' x2='1' y2='1'><stop stop-color='#061426'/><stop offset='1' stop-color='#173552'/></linearGradient></defs>
      <rect width='640' height='360' fill='url(#g-{kind})'/><circle cx='540' cy='60' r='130' fill='#b48a35' opacity='.12'/><g fill='none'>{motif}</g>
      <text x='48' y='315' fill='#f4ead1' font-size='18' font-family='Arial, sans-serif' letter-spacing='2'>{safe_title}</text>
    </svg>"""


def card(item: dict[str, str]) -> str:
    title_en = html.escape(item["title_en"])
    title_ja = html.escape(item["title_ja"])
    summary_en = html.escape(item["summary_en"])
    summary_ja = html.escape(item["summary_ja"])
    source = html.escape(item["source"])
    category = html.escape(item["category"])
    url = html.escape(item["url"], quote=True)
    return f"""<article class='jaios-edge-news-card' data-jaios-news-card='{html.escape(item['id'])}'>
      <div class='jaios-edge-news-media'>{visual_svg(item['visual'], category)}</div>
      <div class='jaios-edge-news-body'>
        <div class='jaios-edge-news-meta'><time datetime='{item['date']}'>{item['date']}</time><span>{category}</span></div>
        <h3>{title_en}</h3><p class='jaios-edge-news-ja' lang='ja'>{title_ja}</p>
        <p>{summary_en}</p><p class='jaios-edge-news-ja' lang='ja'>{summary_ja}</p>
        <div class='jaios-edge-news-source'><span>{source}</span><a href='{url}' target='_blank' rel='noopener noreferrer'>Primary source ↗</a></div>
      </div>
    </article>"""


def news_markup(items: list[dict[str, str]]) -> str:
    cards = "".join(card(item) for item in items)
    return f"""<div class='jaios-edge-news-shell' data-jaios-news-release='{RELEASE}'>
      <header class='jaios-edge-news-heading'><div><small>GLOBAL OBSERVATORY · INSTITUTIONAL INTELLIGENCE</small><h2>Governance, infrastructure and technology developments</h2><p lang='ja'>JUNCA／JAIOSの制度・AI・Blockchain・デジタル公共基盤と親和性の高い一次情報を選定しています。</p></div><span>PRIMARY SOURCES · 6</span></header>
      <div class='jaios-edge-news-grid'>{cards}</div>
    </div>"""


def trust_markup() -> str:
    return f"""<section class='jaios-edge-trust' data-jaios-trust-release='{TRUST_RELEASE}' aria-labelledby='jaios-edge-trust-title'>
      <div class='jaios-edge-trust-shell'>
        <header><small>INSTITUTIONAL TRUST ARCHITECTURE</small><h2 id='jaios-edge-trust-title'>Internationally informed governance, independent audit and verifiable operations</h2><p>JAIOS Institutional Governance continuously organizes international legal developments, jurisdictional frameworks, technology and financial conditions, user-protection requirements and global affairs into maintained audit and management standards.</p><p lang='ja'>JAIOS Institutional Governanceは、国際法令、各国の制度、技術・金融環境、利用者保護に関する要件および国際情勢を継続的に整理し、監査・管理基準へ反映する機関です。</p></header>
        <div class='jaios-edge-trust-grid'>
          <article><span>01</span><h3>Independent audit</h3><p>JUNCA HOLDINGS advances its business, development and public disclosures while subject to JAIOS review and evidence-based assessment.</p><p lang='ja'>JUNCA HOLDINGSは、JAIOSによる監査と証拠に基づく評価を受けながら、事業・開発・公開を進めています。</p></article>
          <article><span>02</span><h3>Governed JSEC environment</h3><p>JUNCA Social Ecosystem Chain is operated under JAIOS management standards, separating network evidence and release decisions from a single operator's unsupported judgment.</p><p lang='ja'>JUNCA Social Ecosystem ChainはJAIOSの管理基準のもとで運営され、ネットワーク証跡と公開判断を特定事業者だけの判断から分離します。</p></article>
          <article><span>03</span><h3>International credibility</h3><p>Continuous review, transparent records and controlled publication support a fair, accountable and internationally credible operating environment.</p><p lang='ja'>継続的な監査、透明な記録、統制された公開により、公平性、説明責任、国際的な信頼に耐え得る運営環境を形成します。</p></article>
        </div>
        <div class='jaios-edge-trust-links'><a href='https://docs.jaios-governance.org/current-identity/'>Current identity ↗</a><a href='https://docs.jaios-governance.org/institutional-trust/'>Institutional trust record ↗</a><a href='https://explorer.jaios-governance.org/'>Public network evidence ↗</a></div>
      </div>
    </section>"""


def build(source_path: Path, data_path: Path, output_path: Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if len(items) != 6:
        raise SystemExit("JAIOS News edge build requires exactly six items")
    if "GLOBAL OBSERVATORY" not in source or "WORLD NOW" not in source:
        raise SystemExit("Current JAIOS Global Observatory section was not found")
    if RELEASE in source or TRUST_RELEASE in source:
        raise SystemExit("Release marker already exists in source HTML")
    if "</head>" not in source or "</body>" not in source:
        raise SystemExit("Current JAIOS HTML lacks required document boundaries")

    news = news_markup(items)
    trust = trust_markup()
    css = """<style id='jaios-edge-news-style'>
    .jaios-edge-trust{background:#071827;color:#f4ead1;border-top:1px solid rgba(215,189,120,.35);border-bottom:1px solid rgba(215,189,120,.25)}.jaios-edge-trust-shell{max-width:1240px;margin:0 auto;padding:clamp(3rem,7vw,6rem) clamp(1rem,3vw,2.5rem)}.jaios-edge-trust header{max-width:980px}.jaios-edge-trust small{color:#d7bd78;font-weight:800;letter-spacing:.14em}.jaios-edge-trust h2{margin:.65rem 0 1.2rem;font-family:Georgia,'Times New Roman',serif;font-size:clamp(2rem,4.8vw,4.7rem);font-weight:500;line-height:1.02}.jaios-edge-trust header p{max-width:900px;color:#c6d0d9;line-height:1.72}.jaios-edge-trust-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:2.3rem;background:rgba(215,189,120,.22)}.jaios-edge-trust-grid article{min-width:0;padding:clamp(1.2rem,2.6vw,2rem);background:#0b2236}.jaios-edge-trust-grid span{color:#d7bd78;font-size:.72rem;letter-spacing:.13em}.jaios-edge-trust-grid h3{margin:.8rem 0;font-family:Georgia,'Times New Roman',serif;font-size:1.45rem;font-weight:500}.jaios-edge-trust-grid p{margin:.55rem 0 0;color:#b9c5cf;line-height:1.65}.jaios-edge-trust-links{display:flex;flex-wrap:wrap;gap:1rem;margin-top:1.7rem}.jaios-edge-trust-links a{color:#ead49e;font-size:.78rem;font-weight:800;text-decoration:none}.jaios-edge-trust-links a:hover{text-decoration:underline}
    .jaios-edge-news-shell{max-width:1240px;margin:0 auto;padding:clamp(2rem,5vw,5rem) clamp(1rem,3vw,2.5rem);color:#10233a;background:linear-gradient(180deg,#faf9f5,#f1ede2)}
    .jaios-edge-news-heading{display:flex;justify-content:space-between;gap:2rem;align-items:end;margin-bottom:2rem;border-bottom:1px solid rgba(13,35,68,.18);padding-bottom:1.25rem}.jaios-edge-news-heading small{color:#8a6d2f;font-weight:800;letter-spacing:.12em}.jaios-edge-news-heading h2{max-width:850px;margin:.5rem 0;font-family:Georgia,'Times New Roman',serif;font-size:clamp(2rem,4vw,4rem);font-weight:500;line-height:1.06}.jaios-edge-news-heading p{max-width:850px;margin:.65rem 0 0;color:#526171}.jaios-edge-news-heading>span{white-space:nowrap;color:#8a6d2f;font-size:.72rem;font-weight:800;letter-spacing:.1em}
    .jaios-edge-news-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(1rem,2vw,1.6rem);align-items:stretch}.jaios-edge-news-card{display:grid;grid-template-rows:auto 1fr;min-width:0;overflow:hidden;background:#fff;border:1px solid rgba(13,35,68,.16);box-shadow:0 18px 44px rgba(8,24,47,.08)}.jaios-edge-news-media{aspect-ratio:16/9;background:#061426;overflow:hidden}.jaios-edge-news-media svg{display:block;width:100%;height:100%}.jaios-edge-news-body{display:flex;min-height:22rem;flex-direction:column;padding:clamp(1rem,2vw,1.45rem)}.jaios-edge-news-meta{display:flex;flex-wrap:wrap;gap:.4rem .75rem;color:#8a6d2f;font-size:.65rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.jaios-edge-news-card h3{margin:.75rem 0 0;font-family:Georgia,'Times New Roman',serif;font-size:1.35rem;font-weight:500;line-height:1.28}.jaios-edge-news-card p{margin:.65rem 0 0;color:#526171;font-size:.9rem;line-height:1.62}.jaios-edge-news-card .jaios-edge-news-ja{color:#24384d}.jaios-edge-news-source{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.7rem;margin-top:auto;padding-top:1rem;border-top:1px solid rgba(13,35,68,.12);color:#6b7784;font-size:.7rem}.jaios-edge-news-source a{color:#755d27;font-weight:800;text-decoration:none}.jaios-edge-news-source a:hover{text-decoration:underline}.jaios-edge-news-source a:focus-visible{outline:2px solid #9a7225;outline-offset:3px}
    @media(max-width:960px){.jaios-edge-trust-grid,.jaios-edge-news-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.jaios-edge-trust-grid article:last-child{grid-column:1/-1}.jaios-edge-news-heading{align-items:start;flex-direction:column}.jaios-edge-news-body{min-height:20rem}}
    @media(max-width:640px){.jaios-edge-trust-grid,.jaios-edge-news-grid{grid-template-columns:1fr}.jaios-edge-trust-grid article:last-child{grid-column:auto}.jaios-edge-news-shell{padding-inline:1rem}.jaios-edge-news-body{min-height:0}.jaios-edge-news-heading>span{white-space:normal}}
    </style>"""
    escaped_news = json.dumps(news, ensure_ascii=False)
    escaped_trust = json.dumps(trust, ensure_ascii=False)
    script = f"""<template id='jaios-edge-news-template'>{news}</template><template id='jaios-edge-trust-template'>{trust}</template><script id='jaios-edge-news-runtime'>(function(){{
      const newsRelease={json.dumps(RELEASE)}; const trustRelease={json.dumps(TRUST_RELEASE)}; const newsMarkup={escaped_news}; const trustMarkup={escaped_trust};
      function target(){{return Array.from(document.querySelectorAll('section')).find(function(s){{const t=(s.textContent||'').toUpperCase();return t.includes('GLOBAL OBSERVATORY')&&(t.includes('WORLD NOW')||t.includes('INSTITUTIONAL INTELLIGENCE'));}});}}
      function apply(){{const s=target();if(!s)return false;if(!document.querySelector('[data-jaios-trust-release="'+trustRelease+'"]'))s.insertAdjacentHTML('beforebegin',trustMarkup);if(!s.querySelector('[data-jaios-news-release="'+newsRelease+'"]')){{s.innerHTML=newsMarkup;s.setAttribute('data-jaios-news-section',newsRelease);}}return true;}}
      function start(){{apply();const observer=new MutationObserver(function(){{apply();}});observer.observe(document.documentElement,{{childList:true,subtree:true}});setTimeout(function(){{apply();observer.disconnect();}},30000);}}
      if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{{once:true}});else start();
    }})();</script>"""
    output = source.replace("</head>", css + "</head>", 1).replace("</body>", script + "</body>", 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")

    if output.count("data-jaios-news-card=") != 12:
        raise SystemExit("Generated HTML does not contain the expected six-card dual representation")
    if output.count(f"data-jaios-news-release='{RELEASE}'") != 2:
        raise SystemExit("Generated HTML News release markers are incomplete")
    if output.count(f"data-jaios-trust-release='{TRUST_RELEASE}'") != 2:
        raise SystemExit("Generated HTML trust release markers are incomplete")
    for required in (
        "Internationally informed governance",
        "JAIOS Institutional Governanceは",
        "JUNCA HOLDINGSは、JAIOSによる監査",
        "国際的な信頼に耐え得る運営環境",
    ):
        if required not in output:
            raise SystemExit(f"Generated HTML lacks required institutional trust copy: {required}")
    for prohibited in ("JUNCA Point", "PointとJSEC", "revenue model", "収益モデル"):
        if prohibited.lower() in output.lower():
            raise SystemExit(f"Prohibited closed or whitepaper-only copy detected: {prohibited}")
    print(f"Built {output_path} with institutional trust and six governed News cards")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: build_jaios_root_news_edge.py SOURCE_HTML NEWS_JSON OUTPUT_HTML")
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
