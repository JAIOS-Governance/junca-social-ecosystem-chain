#!/usr/bin/env python3
"""Build a hydration-resilient JSEC brand root with JAIOS institutional trust copy."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RELEASE = "20260805-chain-institutional-trust"


def trust_markup() -> str:
    return f"""<section class='jsec-institutional-trust' data-jsec-trust-release='{RELEASE}' aria-labelledby='jsec-trust-title'>
      <div class='jsec-institutional-trust-shell'>
        <header><small>INSTITUTIONAL GOVERNANCE · VERIFIABLE NETWORK OPERATION</small><h2 id='jsec-trust-title'>Managed under JAIOS Institutional Governance</h2><p>JUNCA Social Ecosystem Chain is developed and operated under JAIOS management standards. International legal developments, jurisdictional frameworks, technology and financial conditions, user-protection requirements and global affairs are continuously organized into maintained audit and governance criteria.</p><p lang='ja'>JUNCA Social Ecosystem Chainは、JAIOS Institutional Governanceの管理基準のもとで開発・運営されています。国際法令、各国制度、技術・金融環境、利用者保護の要件および国際情勢を継続的に整理し、監査・統治基準へ反映します。</p></header>
        <div class='jsec-institutional-trust-grid'>
          <article><span>01</span><h3>International standards</h3><p>Network governance is reviewed against standards that evolve with international legal, institutional and technological conditions.</p><p lang='ja'>ネットワークの統治を、国際的な法制度・機構・技術環境の変化に応じて更新される基準に基づき確認します。</p></article>
          <article><span>02</span><h3>Controlled operation</h3><p>Network evidence, release decisions and public status are governed through reviewable records and controlled activation procedures.</p><p lang='ja'>ネットワーク証跡、公開判断、公開状態を、確認可能な記録と統制された稼働手続に基づいて管理します。</p></article>
          <article><span>03</span><h3>Publicly verifiable evidence</h3><p>Technical documentation and the Public Explorer provide separate, reviewable records supporting transparency and continuing accountability.</p><p lang='ja'>技術文書とPublic Explorerを独立した確認可能な記録として公開し、透明性と継続的な説明責任を支えます。</p></article>
        </div>
        <div class='jsec-institutional-trust-links'><a href='https://jaios-governance.org/'>JAIOS Institutional Governance ↗</a><a href='https://docs.jaios-governance.org/institutional-trust/'>Institutional trust record ↗</a><a href='https://docs.jaios-governance.org/'>Technical Reference ↗</a><a href='https://explorer.jaios-governance.org/'>Public Explorer ↗</a></div>
      </div>
    </section>"""


def build(source: str) -> str:
    if "</head>" not in source.lower() or "</body>" not in source.lower():
        raise SystemExit("Brand root lacks HTML document boundaries")
    if RELEASE in source:
        raise SystemExit("Brand root already contains this release")

    markup = trust_markup()
    prohibited = (
        "JUNCA Point",
        "Point exchange",
        "Point交換",
        "revenue model",
        "revenue allocation",
        "収益モデル",
        "収益配分",
    )
    for value in prohibited:
        if value.lower() in markup.lower():
            raise SystemExit(f"Closed information detected: {value}")

    required = (
        "Managed under JAIOS Institutional Governance",
        "JAIOS Institutional Governanceの管理基準",
        "International standards",
        "Controlled operation",
        "Publicly verifiable evidence",
    )
    for value in required:
        if value not in markup:
            raise SystemExit(f"Required trust copy missing: {value}")

    css = """<style id='jsec-institutional-trust-style'>
    .jsec-institutional-trust{position:relative;background:#071827;color:#f4ead1;border-top:1px solid rgba(215,189,120,.34);border-bottom:1px solid rgba(215,189,120,.22);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.jsec-institutional-trust-shell{width:min(1240px,calc(100% - 2rem));margin:0 auto;padding:clamp(3rem,7vw,6rem) 0}.jsec-institutional-trust header{max-width:1000px}.jsec-institutional-trust header small{color:#d7bd78;font-size:.72rem;font-weight:800;letter-spacing:.15em}.jsec-institutional-trust h2{max-width:1000px;margin:.75rem 0 1.3rem;color:#f4ead1;font-family:Georgia,"Times New Roman",serif;font-size:clamp(2.3rem,5vw,4.8rem);font-weight:500;line-height:1.02}.jsec-institutional-trust header p{max-width:930px;margin:.65rem 0;color:#c6d0d9;font-size:1rem;line-height:1.75}.jsec-institutional-trust-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:2.4rem;background:rgba(215,189,120,.22)}.jsec-institutional-trust-grid article{min-width:0;padding:clamp(1.25rem,2.7vw,2rem);background:#0b2236}.jsec-institutional-trust-grid span{color:#d7bd78;font-size:.72rem;letter-spacing:.13em}.jsec-institutional-trust-grid h3{margin:.8rem 0;color:#f4ead1;font-family:Georgia,"Times New Roman",serif;font-size:1.42rem;font-weight:500}.jsec-institutional-trust-grid p{margin:.55rem 0 0;color:#b9c5cf;font-size:.9rem;line-height:1.67}.jsec-institutional-trust-links{display:flex;flex-wrap:wrap;gap:1.15rem;margin-top:1.8rem}.jsec-institutional-trust-links a{color:#ead49e;font-size:.78rem;font-weight:800;text-decoration:none}.jsec-institutional-trust-links a:hover{text-decoration:underline}.jsec-institutional-trust-links a:focus-visible{outline:2px solid #ead49e;outline-offset:4px}@media(max-width:960px){.jsec-institutional-trust-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.jsec-institutional-trust-grid article:last-child{grid-column:1/-1}}@media(max-width:640px){.jsec-institutional-trust-shell{width:min(100% - 1.5rem,1240px)}.jsec-institutional-trust-grid{grid-template-columns:1fr}.jsec-institutional-trust-grid article:last-child{grid-column:auto}}
    </style>"""
    encoded = json.dumps(markup, ensure_ascii=False)
    runtime = f"""<template id='jsec-institutional-trust-template'>{markup}</template><script id='jsec-institutional-trust-runtime'>(function(){{"use strict";const release={json.dumps(RELEASE)};const markup={encoded};function existing(){{return document.querySelector('[data-jsec-trust-release="'+release+'"]');}}function target(){{const sections=Array.from(document.querySelectorAll('main section,section'));return sections.find(function(s){{const t=(s.textContent||'').toUpperCase();return t.includes('GOVERNANCE')||t.includes('EVIDENCE')||t.includes('NETWORK');}})||sections[1]||sections[0]||document.querySelector('main');}}function apply(){{if(existing())return true;const node=target();if(!node)return false;node.insertAdjacentHTML('beforebegin',markup);return true;}}function start(){{apply();const observer=new MutationObserver(function(){{apply();}});observer.observe(document.documentElement,{{childList:true,subtree:true}});setTimeout(function(){{apply();observer.disconnect();}},30000);}}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{{once:true}});else start();}})();</script>"""

    output = re.sub(r"</head>", css + "</head>", source, count=1, flags=re.I)
    output = re.sub(r"</body>", runtime + "</body>", output, count=1, flags=re.I)
    if output.count(f"data-jsec-trust-release='{RELEASE}'") != 2:
        raise SystemExit("Trust release dual representation is incomplete")
    return output


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_chain_brand_institutional_trust.py INPUT_HTML OUTPUT_HTML")
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
    output = build(source)
    Path(sys.argv[2]).write_text(output, encoding="utf-8")
    print(f"Built {sys.argv[2]} with {RELEASE}")


if __name__ == "__main__":
    main()
