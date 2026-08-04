#!/usr/bin/env python3
"""Replace the JAIOS edge News injection with six article-related photographs.

The current public HTML is preserved except for the governed JAIOS edge
News/trust style, templates and runtime. The replacement remains client-side so
React hydration cannot permanently restore the former five-card Observatory.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

RELEASE = "20260805-six-card-photo-news"
TRUST_RELEASE = "20260804-institutional-trust"
EDGE_IDS = (
    ("style", "jaios-edge-news-style"),
    ("template", "jaios-edge-news-template"),
    ("template", "jaios-edge-trust-template"),
    ("script", "jaios-edge-news-runtime"),
)


def esc(value: str, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def remove_previous_edge_injection(source: str) -> str:
    cleaned = source
    for tag, element_id in EDGE_IDS:
        pattern = rf"<{tag}\b[^>]*\bid=['\"]{re.escape(element_id)}['\"][^>]*>.*?</{tag}>"
        cleaned, count = re.subn(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if count > 1:
            raise SystemExit(f"Unexpected duplicate edge element: {element_id} ({count})")
    return cleaned


def validate_items(items: list[dict[str, str]]) -> None:
    if len(items) != 6:
        raise SystemExit("JAIOS photo News requires exactly six items")
    required = {
        "id",
        "date",
        "category",
        "source",
        "url",
        "title_en",
        "title_ja",
        "summary_en",
        "summary_ja",
        "image_url",
        "image_alt",
        "image_credit",
        "image_credit_url",
    }
    seen_ids: set[str] = set()
    seen_images: set[str] = set()
    for item in items:
        missing = sorted(required.difference(item))
        if missing:
            raise SystemExit(f"{item.get('id', 'unknown')}: missing fields {missing}")
        if item["id"] in seen_ids:
            raise SystemExit(f"Duplicate News id: {item['id']}")
        seen_ids.add(item["id"])
        if item["image_url"] in seen_images:
            raise SystemExit(f"Duplicate News photo: {item['image_url']}")
        seen_images.add(item["image_url"])
        for field in ("url", "image_url", "image_credit_url"):
            parsed = urlparse(item[field])
            if parsed.scheme != "https" or not parsed.netloc:
                raise SystemExit(f"{item['id']}: {field} must be an absolute HTTPS URL")
        if any(token in item["image_url"].lower() for token in (".svg", "data:image/svg")):
            raise SystemExit(f"{item['id']}: geometric SVG images are prohibited")


def card(item: dict[str, str]) -> str:
    return f"""<article class='jaios-edge-news-card' data-jaios-news-card='{esc(item['id'], quote=True)}'>
      <figure class='jaios-edge-news-media'>
        <img src='{esc(item['image_url'], quote=True)}' alt='{esc(item['image_alt'], quote=True)}' loading='lazy' decoding='async' referrerpolicy='no-referrer'/>
        <figcaption><a href='{esc(item['image_credit_url'], quote=True)}' target='_blank' rel='noopener noreferrer'>{esc(item['image_credit'])}</a></figcaption>
      </figure>
      <div class='jaios-edge-news-body'>
        <div class='jaios-edge-news-meta'><time datetime='{esc(item['date'], quote=True)}'>{esc(item['date'])}</time><span>{esc(item['category'])}</span></div>
        <h3>{esc(item['title_en'])}</h3><p class='jaios-edge-news-ja' lang='ja'>{esc(item['title_ja'])}</p>
        <p>{esc(item['summary_en'])}</p><p class='jaios-edge-news-ja' lang='ja'>{esc(item['summary_ja'])}</p>
        <div class='jaios-edge-news-source'><span>{esc(item['source'])}</span><a href='{esc(item['url'], quote=True)}' target='_blank' rel='noopener noreferrer'>Primary source ↗</a></div>
      </div>
    </article>"""


def news_markup(items: list[dict[str, str]]) -> str:
    return f"""<div class='jaios-edge-news-shell' data-jaios-news-release='{RELEASE}'>
      <header class='jaios-edge-news-heading'><div><small>GLOBAL OBSERVATORY · INSTITUTIONAL INTELLIGENCE</small><h2>Governance, infrastructure and technology developments</h2><p lang='ja'>JUNCA／JAIOSの制度・AI・Blockchain・デジタル公共基盤と親和性の高い一次情報を、記事に対応する写真とともに掲載しています。</p></div><span>PRIMARY SOURCES · 6</span></header>
      <div class='jaios-edge-news-grid'>{''.join(card(item) for item in items)}</div>
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
    source = remove_previous_edge_injection(source_path.read_text(encoding="utf-8"))
    data = json.loads(data_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    validate_items(items)
    if "GLOBAL OBSERVATORY" not in source or "WORLD NOW" not in source:
        raise SystemExit("Current JAIOS Global Observatory section was not found")
    if "</head>" not in source or "</body>" not in source:
        raise SystemExit("Current JAIOS HTML lacks required document boundaries")

    news = news_markup(items)
    trust = trust_markup()
    css = """<style id='jaios-edge-news-style'>
    .jaios-edge-trust{background:#071827;color:#f4ead1;border-top:1px solid rgba(215,189,120,.35);border-bottom:1px solid rgba(215,189,120,.25)}.jaios-edge-trust-shell{max-width:1240px;margin:0 auto;padding:clamp(3rem,7vw,6rem) clamp(1rem,3vw,2.5rem)}.jaios-edge-trust header{max-width:980px}.jaios-edge-trust small{color:#d7bd78;font-weight:800;letter-spacing:.14em}.jaios-edge-trust h2{margin:.65rem 0 1.2rem;font-family:Georgia,'Times New Roman',serif;font-size:clamp(2rem,4.8vw,4.7rem);font-weight:500;line-height:1.02}.jaios-edge-trust header p{max-width:900px;color:#c6d0d9;line-height:1.72}.jaios-edge-trust-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:2.3rem;background:rgba(215,189,120,.22)}.jaios-edge-trust-grid article{min-width:0;padding:clamp(1.2rem,2.6vw,2rem);background:#0b2236}.jaios-edge-trust-grid span{color:#d7bd78;font-size:.72rem;letter-spacing:.13em}.jaios-edge-trust-grid h3{margin:.8rem 0;font-family:Georgia,'Times New Roman',serif;font-size:1.45rem;font-weight:500}.jaios-edge-trust-grid p{margin:.55rem 0 0;color:#b9c5cf;line-height:1.65}.jaios-edge-trust-links{display:flex;flex-wrap:wrap;gap:1rem;margin-top:1.7rem}.jaios-edge-trust-links a{color:#ead49e;font-size:.78rem;font-weight:800;text-decoration:none}.jaios-edge-trust-links a:hover{text-decoration:underline}
    .world-now.jaios-photo-news-section{padding:0;background:linear-gradient(180deg,#faf9f5,#f1ede2)}.jaios-edge-news-shell{max-width:1240px;margin:0 auto;padding:clamp(2rem,5vw,5rem) clamp(1rem,3vw,2.5rem);color:#10233a}.jaios-edge-news-heading{display:flex;justify-content:space-between;gap:2rem;align-items:end;margin-bottom:2rem;border-bottom:1px solid rgba(13,35,68,.18);padding-bottom:1.25rem}.jaios-edge-news-heading small{color:#8a6d2f;font-weight:800;letter-spacing:.12em}.jaios-edge-news-heading h2{max-width:850px;margin:.5rem 0;font-family:Georgia,'Times New Roman',serif;font-size:clamp(2rem,4vw,4rem);font-weight:500;line-height:1.06}.jaios-edge-news-heading p{max-width:850px;margin:.65rem 0 0;color:#526171}.jaios-edge-news-heading>span{white-space:nowrap;color:#8a6d2f;font-size:.72rem;font-weight:800;letter-spacing:.1em}
    .jaios-edge-news-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(1rem,2vw,1.6rem);align-items:stretch}.jaios-edge-news-card{display:grid;grid-template-rows:auto 1fr;min-width:0;overflow:hidden;background:#fff;border:1px solid rgba(13,35,68,.16);box-shadow:0 18px 44px rgba(8,24,47,.08)}.jaios-edge-news-media{position:relative;aspect-ratio:16/9;margin:0;background:#061426;overflow:hidden}.jaios-edge-news-media img{display:block;width:100%;height:100%;object-fit:cover;object-position:center;filter:saturate(.94) contrast(1.03)}.jaios-edge-news-media figcaption{position:absolute;right:.55rem;bottom:.45rem;max-width:82%;padding:.25rem .45rem;background:rgba(5,18,34,.72);font-size:.58rem;line-height:1.25}.jaios-edge-news-media figcaption a{color:#f4ead1;text-decoration:none}.jaios-edge-news-body{display:flex;min-height:22rem;flex-direction:column;padding:clamp(1rem,2vw,1.45rem)}.jaios-edge-news-meta{display:flex;flex-wrap:wrap;gap:.4rem .75rem;color:#8a6d2f;font-size:.65rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.jaios-edge-news-card h3{margin:.75rem 0 0;font-family:Georgia,'Times New Roman',serif;font-size:1.35rem;font-weight:500;line-height:1.28}.jaios-edge-news-card p{margin:.65rem 0 0;color:#526171;font-size:.9rem;line-height:1.62}.jaios-edge-news-card .jaios-edge-news-ja{color:#24384d}.jaios-edge-news-source{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.7rem;margin-top:auto;padding-top:1rem;border-top:1px solid rgba(13,35,68,.12);color:#6b7784;font-size:.7rem}.jaios-edge-news-source a{color:#755d27;font-weight:800;text-decoration:none}.jaios-edge-news-source a:hover{text-decoration:underline}.jaios-edge-news-source a:focus-visible,.jaios-edge-news-media a:focus-visible{outline:2px solid #9a7225;outline-offset:3px}
    @media(max-width:960px){.jaios-edge-trust-grid,.jaios-edge-news-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.jaios-edge-trust-grid article:last-child{grid-column:1/-1}.jaios-edge-news-heading{align-items:start;flex-direction:column}.jaios-edge-news-body{min-height:20rem}}
    @media(max-width:640px){.jaios-edge-trust-grid,.jaios-edge-news-grid{grid-template-columns:1fr}.jaios-edge-trust-grid article:last-child{grid-column:auto}.jaios-edge-news-shell{padding-inline:1rem}.jaios-edge-news-body{min-height:0}.jaios-edge-news-heading>span{white-space:normal}}
    </style>"""
    script = f"""<template id='jaios-edge-news-template'>{news}</template><template id='jaios-edge-trust-template'>{trust}</template><script id='jaios-edge-news-runtime'>(function(){{
      const newsRelease={json.dumps(RELEASE)}; const trustRelease={json.dumps(TRUST_RELEASE)};
      const newsMarkup={json.dumps(news, ensure_ascii=False)}; const trustMarkup={json.dumps(trust, ensure_ascii=False)};
      function apply(){{
        const target=document.querySelector('section.world-now,section#world-now'); if(!target) return false;
        const cards=target.querySelectorAll('[data-jaios-news-card]'); const photos=target.querySelectorAll('.jaios-edge-news-media img');
        if(target.getAttribute('data-jaios-news-release')!==newsRelease || cards.length!==6 || photos.length!==6){{
          target.classList.add('jaios-photo-news-section'); target.innerHTML=newsMarkup; target.setAttribute('data-jaios-news-release',newsRelease);
        }}
        if(!document.querySelector('[data-jaios-trust-release="'+trustRelease+'"]')) target.insertAdjacentHTML('beforebegin',trustMarkup);
        return true;
      }}
      let attempts=0; const timer=setInterval(function(){{apply(); attempts+=1; if(attempts>120) clearInterval(timer);}},250);
      const observer=new MutationObserver(function(){{apply();}}); observer.observe(document.documentElement,{{childList:true,subtree:true}});
      if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',apply); else apply(); window.addEventListener('load',apply);
    }})();</script>"""

    result = source.replace("</head>", css + "</head>").replace("</body>", script + "</body>")
    if result.count(f"data-jaios-news-release='{RELEASE}'") < 1:
        raise SystemExit("Photo News release marker was not written")
    if result.count("data-jaios-news-card=") != 12:
        raise SystemExit("Expected exactly six cards in template and six in runtime payload")
    if result.count("<img src=") < 6:
        raise SystemExit("Expected six article-related photo elements")
    if "visual_svg(" in result or "<svg viewBox='0 0 640 360'" in result:
        raise SystemExit("Legacy geometric News SVG remains in output")
    if len(result.encode("utf-8")) >= 1_000_000:
        raise SystemExit("Generated JAIOS root HTML exceeds the 1 MB gate")
    output_path.write_text(result, encoding="utf-8")
    print(f"JAIOS_NEWS_PHOTO_BUILD_PASS cards=6 bytes={len(result.encode('utf-8'))}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: build_jaios_root_news_photo.py SOURCE_HTML NEWS_JSON OUTPUT_HTML")
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
