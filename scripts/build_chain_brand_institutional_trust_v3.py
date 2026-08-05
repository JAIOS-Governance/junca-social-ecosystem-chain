#!/usr/bin/env python3
"""Build a browser-visible JSEC Institutional Trust root without inline-script encoding."""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

CONTENT_RELEASE = "20260805-chain-institutional-trust"
DELIVERY_RELEASE = "20260805-chain-institutional-trust-v3"
RUNTIME_URL = (
    "https://docs.jaios-governance.org/chain-brand-root/"
    "trust-runtime-v3.js"
)


def trust_markup() -> str:
    return f"""<section class="jsec-institutional-trust" data-jsec-trust-release="{CONTENT_RELEASE}" aria-labelledby="jsec-trust-title">
  <div class="jsec-institutional-trust-shell">
    <header>
      <small>INSTITUTIONAL GOVERNANCE · VERIFIABLE NETWORK OPERATION</small>
      <h2 id="jsec-trust-title">Managed under JAIOS Institutional Governance</h2>
      <p>JUNCA Social Ecosystem Chain is developed and operated under JAIOS management standards. International legal developments, jurisdictional frameworks, technology and financial conditions, user-protection requirements and global affairs are continuously organized into maintained audit and governance criteria.</p>
      <p lang="ja">JUNCA Social Ecosystem Chainは、JAIOS Institutional Governanceの管理基準のもとで開発・運営されています。国際法令、各国制度、技術・金融環境、利用者保護の要件および国際情勢を継続的に整理し、監査・統治基準へ反映します。</p>
    </header>
    <div class="jsec-institutional-trust-grid">
      <article><span>01</span><h3>International standards</h3><p>Network governance is reviewed against standards that evolve with international legal, institutional and technological conditions.</p><p lang="ja">ネットワークの統治を、国際的な法制度・機構・技術環境の変化に応じて更新される基準に基づき確認します。</p></article>
      <article><span>02</span><h3>Controlled operation</h3><p>Network evidence, release decisions and public status are governed through reviewable records and controlled activation procedures.</p><p lang="ja">ネットワーク証跡、公開判断、公開状態を、確認可能な記録と統制された稼働手続に基づいて管理します。</p></article>
      <article><span>03</span><h3>Publicly verifiable evidence</h3><p>Technical documentation and the Public Explorer provide separate, reviewable records supporting transparency and continuing accountability.</p><p lang="ja">技術文書とPublic Explorerを独立した確認可能な記録として公開し、透明性と継続的な説明責任を支えます。</p></article>
    </div>
    <div class="jsec-institutional-trust-links">
      <a href="https://jaios-governance.org/">JAIOS Institutional Governance ↗</a>
      <a href="https://docs.jaios-governance.org/institutional-trust/">Institutional trust record ↗</a>
      <a href="https://docs.jaios-governance.org/">Technical Reference ↗</a>
      <a href="https://explorer.jaios-governance.org/">Public Explorer ↗</a>
    </div>
  </div>
</section>"""


def trust_css() -> str:
    return """.jsec-institutional-trust{position:relative;background:#071827;color:#f4ead1;border-top:1px solid rgba(215,189,120,.34);border-bottom:1px solid rgba(215,189,120,.22);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.jsec-institutional-trust-shell{width:min(1240px,calc(100% - 2rem));margin:0 auto;padding:clamp(3rem,7vw,6rem) 0}.jsec-institutional-trust header{max-width:1000px}.jsec-institutional-trust header small{color:#d7bd78;font-size:.72rem;font-weight:800;letter-spacing:.15em}.jsec-institutional-trust h2{max-width:1000px;margin:.75rem 0 1.3rem;color:#f4ead1;font-family:Georgia,"Times New Roman",serif;font-size:clamp(2.3rem,5vw,4.8rem);font-weight:500;line-height:1.02}.jsec-institutional-trust header p{max-width:930px;margin:.65rem 0;color:#c6d0d9;font-size:1rem;line-height:1.75}.jsec-institutional-trust-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:2.4rem;background:rgba(215,189,120,.22)}.jsec-institutional-trust-grid article{min-width:0;padding:clamp(1.25rem,2.7vw,2rem);background:#0b2236}.jsec-institutional-trust-grid span{color:#d7bd78;font-size:.72rem;letter-spacing:.13em}.jsec-institutional-trust-grid h3{margin:.8rem 0;color:#f4ead1;font-family:Georgia,"Times New Roman",serif;font-size:1.42rem;font-weight:500}.jsec-institutional-trust-grid p{margin:.55rem 0 0;color:#b9c5cf;font-size:.9rem;line-height:1.67}.jsec-institutional-trust-links{display:flex;flex-wrap:wrap;gap:1.15rem;margin-top:1.8rem}.jsec-institutional-trust-links a{color:#ead49e;font-size:.78rem;font-weight:800;text-decoration:none}.jsec-institutional-trust-links a:hover{text-decoration:underline}.jsec-institutional-trust-links a:focus-visible{outline:2px solid #ead49e;outline-offset:4px}@media(max-width:960px){.jsec-institutional-trust-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.jsec-institutional-trust-grid article:last-child{grid-column:1/-1}}@media(max-width:640px){.jsec-institutional-trust-shell{width:min(100% - 1.5rem,1240px)}.jsec-institutional-trust-grid{grid-template-columns:1fr}.jsec-institutional-trust-grid article:last-child{grid-column:auto}}"""


def b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def runtime_javascript(markup: str, css: str) -> str:
    return f"""(function(){{
  'use strict';
  const release='{CONTENT_RELEASE}';
  const markupB64='{b64(markup)}';
  const cssB64='{b64(css)}';
  const decode=(value)=>new TextDecoder().decode(Uint8Array.from(atob(value),c=>c.charCodeAt(0)));
  const markup=decode(markupB64);
  const css=decode(cssB64);
  function ensureStyle(){{
    let style=document.getElementById('jsec-institutional-trust-style-v3');
    if(!style){{style=document.createElement('style');style.id='jsec-institutional-trust-style-v3';style.textContent=css;document.head.appendChild(style);}}
  }}
  function target(){{
    return document.querySelector('main > .live-status-board')||
      document.querySelector('main > section:nth-of-type(3)')||
      document.querySelector('main > section:nth-of-type(2)')||
      document.querySelector('main');
  }}
  function apply(){{
    ensureStyle();
    const nodes=Array.from(document.querySelectorAll('[data-jsec-trust-release="'+release+'"]'));
    if(nodes.length>1)nodes.slice(1).forEach(node=>node.remove());
    if(nodes.length)return true;
    const anchor=target();
    if(!anchor)return false;
    if(anchor.matches('main'))anchor.insertAdjacentHTML('beforeend',markup);
    else anchor.insertAdjacentHTML('beforebegin',markup);
    return true;
  }}
  function start(){{
    apply();
    const observer=new MutationObserver(()=>apply());
    observer.observe(document.documentElement,{{childList:true,subtree:true}});
    let attempts=0;
    const timer=setInterval(()=>{{apply();attempts+=1;if(attempts>=240){{clearInterval(timer);observer.disconnect();}}}},500);
    window.addEventListener('pageshow',apply);
    window.addEventListener('load',apply,{{once:true}});
  }}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{{once:true}});else start();
}})();
"""


def build(source: str) -> tuple[str, str]:
    lower = source.lower()
    if "</head>" not in lower or "</body>" not in lower:
        raise SystemExit("Brand root lacks HTML document boundaries")

    source = re.sub(
        r"<meta\b[^>]*\bname\s*=\s*(['\"])official-surface-release\1[^>]*>\s*",
        "",
        source,
        flags=re.I,
    )
    source = re.sub(
        r"<style\b[^>]*id\s*=\s*(['\"])jsec-institutional-trust-style(?:-v3)?\1[^>]*>.*?</style>\s*",
        "",
        source,
        flags=re.I | re.S,
    )
    source = re.sub(
        r"<template\b[^>]*id\s*=\s*(['\"])jsec-institutional-trust-template\1[^>]*>.*?</template>\s*",
        "",
        source,
        flags=re.I | re.S,
    )
    source = re.sub(
        r"<script\b[^>]*(?:id\s*=\s*(['\"])jsec-institutional-trust-runtime\1|src\s*=\s*(['\"])[^'\"]*trust-runtime-v3\.js\2)[^>]*>.*?</script>\s*",
        "",
        source,
        flags=re.I | re.S,
    )

    markup = trust_markup()
    css = trust_css()
    prohibited = (
        "JUNCA Point",
        "Point exchange",
        "Point交換",
        "revenue model",
        "revenue allocation",
        "収益モデル",
        "収益配分",
    )
    if any(value.lower() in markup.lower() for value in prohibited):
        raise SystemExit("Closed information detected in public markup")

    delivery_meta = (
        f'<meta name="official-surface-release" content="{DELIVERY_RELEASE}">'
    )
    inline_style = f'<style id="jsec-institutional-trust-style-v3">{css}</style>'
    source = source.replace("</head>", delivery_meta + inline_style + "</head>", 1)

    template = f'<template id="jsec-institutional-trust-template">{markup}</template>'
    external_runtime = (
        f'<script id="jsec-institutional-trust-runtime-v3" '
        f'src="{RUNTIME_URL}" defer></script>'
    )
    source = source.replace("</body>", template + external_runtime + "</body>", 1)

    if source.count(f'data-jsec-trust-release="{CONTENT_RELEASE}"') != 1:
        raise SystemExit("Static trust marker is not singular")
    if source.count(
        f'<meta name="official-surface-release" content="{DELIVERY_RELEASE}">'
    ) != 1:
        raise SystemExit("Delivery marker is not singular")
    if source.count(RUNTIME_URL) != 1:
        raise SystemExit("External runtime URL is not singular")
    return source, runtime_javascript(markup, css)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: build_chain_brand_institutional_trust_v3.py "
            "INPUT_HTML OUTPUT_HTML OUTPUT_JS"
        )
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
    html, runtime = build(source)
    Path(sys.argv[2]).write_text(html, encoding="utf-8")
    Path(sys.argv[3]).write_text(runtime, encoding="utf-8")
    print(
        f"Built {sys.argv[2]} and {sys.argv[3]} with "
        f"{CONTENT_RELEASE} / {DELIVERY_RELEASE}"
    )


if __name__ == "__main__":
    main()
