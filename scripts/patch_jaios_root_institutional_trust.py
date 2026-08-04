#!/usr/bin/env python3
"""Replace only the JAIOS root Institutional Trust section in an existing edge artifact."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TRUST_RELEASE = "20260804-institutional-trust"


def trust_markup() -> str:
    return f"""<section class='jaios-edge-trust' data-jaios-trust-release='{TRUST_RELEASE}' aria-labelledby='jaios-edge-trust-title'>
      <div class='jaios-edge-trust-shell'>
        <header><small>INSTITUTIONAL TRUST ARCHITECTURE</small><h2 id='jaios-edge-trust-title'>Internationally informed governance, independent audit and verifiable operations</h2><p>JAIOS Institutional Governance continuously organizes international legal developments, jurisdictional frameworks, technology and financial conditions, user-protection requirements and global affairs into maintained audit and management standards. Its institutional mandate is not defined by, or limited to, any single company or project.</p><p lang='ja'>JAIOS Institutional Governanceは、国際法令、各国の制度、技術・金融環境、利用者保護に関する要件および国際情勢を継続的に整理し、監査・管理基準へ反映する機構です。その機構的役割は、特定の法人や単一プロジェクトに限定されるものではありません。</p></header>
        <div class='jaios-edge-trust-grid'>
          <article><span>01</span><h3>International standards</h3><p>International legal, institutional and technological developments are translated into continuously maintained audit criteria, governance controls and review procedures.</p><p lang='ja'>国際法令、各国制度、技術環境の変化を、継続的に更新される監査基準、統制手続および評価方法へ反映します。</p></article>
          <article><span>02</span><h3>Governed JSEC environment</h3><p>JUNCA Social Ecosystem Chain is operated under JAIOS management standards, separating network evidence and release decisions from a single operator's unsupported judgment.</p><p lang='ja'>JUNCA Social Ecosystem ChainはJAIOSの管理基準のもとで運営され、ネットワーク証跡と公開判断を特定事業者だけの判断から分離します。</p></article>
          <article><span>03</span><h3>Verifiable credibility</h3><p>Continuous review, transparent records and controlled publication support fairness, accountability and an operating environment capable of earning international trust.</p><p lang='ja'>継続的な監査、透明な記録、統制された公開により、公平性、説明責任、国際的な信頼に耐え得る運営環境を形成します。</p></article>
        </div>
        <div class='jaios-edge-trust-links'><a href='https://docs.jaios-governance.org/institutional-trust/'>Institutional trust record ↗</a><a href='https://docs.jaios-governance.org/'>Technical reference ↗</a><a href='https://explorer.jaios-governance.org/'>Public network evidence ↗</a></div>
      </div>
    </section>"""


def patch(source: str) -> str:
    markup = trust_markup()
    template_pattern = re.compile(
        r"<template id=['\"]jaios-edge-trust-template['\"]>.*?</template>",
        re.DOTALL,
    )
    source, template_count = template_pattern.subn(
        f"<template id='jaios-edge-trust-template'>{markup}</template>", source, count=1
    )
    if template_count != 1:
        raise SystemExit(f"expected one trust template, found {template_count}")

    constant_pattern = re.compile(r"const trustMarkup=(\"(?:\\.|[^\"\\])*\");")
    encoded = json.dumps(markup, ensure_ascii=False)
    source, constant_count = constant_pattern.subn(
        lambda _match: f"const trustMarkup={encoded};", source, count=1
    )
    if constant_count != 1:
        raise SystemExit(f"expected one trust runtime constant, found {constant_count}")

    template_match = template_pattern.search(source)
    if not template_match:
        raise SystemExit("patched trust template is missing")
    trust_surface = template_match.group(0)

    required = (
        "Its institutional mandate is not defined by, or limited to, any single company or project.",
        "特定の法人や単一プロジェクトに限定されるものではありません",
        "International standards",
        "JAIOSの管理基準",
        "Verifiable credibility",
        "国際的な信頼に耐え得る運営環境",
    )
    for value in required:
        if value not in trust_surface:
            raise SystemExit(f"required trust copy missing: {value}")

    prohibited = (
        "JUNCA HOLDINGS",
        "JUNCA Point",
        "Point conversion",
        "Point交換",
        "revenue model",
        "収益モデル",
    )
    for value in prohibited:
        if value.lower() in trust_surface.lower():
            raise SystemExit(f"prohibited trust copy detected: {value}")

    if source.count("data-jaios-news-card=") != 12:
        raise SystemExit("six-card News dual representation was not preserved")
    if source.count("data-jaios-news-release=") < 2:
        raise SystemExit("News release markers were not preserved")
    return source


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_jaios_root_institutional_trust.py INPUT_HTML OUTPUT_HTML")
    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    output = patch(source_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    print(f"Patched JAIOS institutional trust section: {output_path}")


if __name__ == "__main__":
    main()
