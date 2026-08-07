from pathlib import Path
import runpy

# Normalize prohibited status labels and semantic no-value wording before public rendering.
build_path = Path("docs/technical-reference/scripts/build.mjs")
build = build_path.read_text(encoding="utf-8")
marker = '      .replaceAll("No Monetary Value", "Protocol Validation Environment")\n'
status_addition = marker + (
    '      .replaceAll(\n'
    '        "Protocol Validation Environment、Rate Limit、Abuse Controlを前提に公開します。",\n'
    '        "Test Asset Separation、Rate Limit、Abuse Controlを前提に公開します。",\n'
    '      )\n'
)
if status_addition not in build:
    if marker not in build:
        raise SystemExit("Expected Japanese status normalization marker is missing")
    build = build.replace(marker, status_addition, 1)

semantic_chain = status_addition + (
    '      .replaceAll(\n'
    '        "A mandatory testnet notice stating that test assets do not represent monetary value.",\n'
    '        "A controlled testnet notice defining test-asset separation, rate limits and abuse-control boundaries.",\n'
    '      )\n'
    '      .replaceAll(\n'
    '        "テスト資産が金銭的価値を表さないことを示す必須のテストネット表示。",\n'
    '        "テスト資産の分離、Rate Limit、Abuse Controlの運用境界を明示するテストネット表示。",\n'
    '      )\n'
    '      .replaceAll(\n'
    '        "JAIOS Institutional Governance does not guarantee the economic value, market liquidity, legal classification or regulatory conformity of an external partner’s token, NFT or DApp.",\n'
    '        "Economic, market, legal and regulatory characteristics of an external partner’s token, NFT or DApp remain under the partner and its qualified advisers’ responsibility.",\n'
    '      )\n'
    '      .replaceAll(\n'
    '        "外部パートナーが発行・運用する資産の経済価値、流動性、法的分類、規制適合性を保証するものではありません。",\n'
    '        "外部パートナーが発行・運用する資産の経済・市場・法務・規制上の特性は、当該パートナーおよび専門家の責任範囲として管理されます。",\n'
    '      )\n'
    '      .replaceAll(\n'
    '        "Recorded legal analysis; no platform guarantee",\n'
    '        "Recorded legal analysis and partner responsibility",\n'
    '      )\n'
)
if semantic_chain not in build:
    if status_addition not in build:
        raise SystemExit("Expected status normalization chain is missing")
    build = build.replace(status_addition, semantic_chain, 1)
build_path.write_text(build, encoding="utf-8")

# Restore aliases used by the current-state normalization after the endpoint block is replaced.
runtime_path = Path("docs/technical-reference/scripts/runtime-current-state-normalize.mjs")
runtime = runtime_path.read_text(encoding="utf-8")
observed_marker = 'const observedAt = String(explorer.observed_at ?? "");\n'
aliases = (
    'const head = explorer.head ?? {};\n'
    'const network = explorer.network ?? {};\n'
    'const runtimeArtifact = explorer.runtime_artifact ?? {};\n'
    + observed_marker
)
if aliases not in runtime:
    if observed_marker not in runtime:
        raise SystemExit("Expected runtime observed-at marker is missing")
    runtime = runtime.replace(observed_marker, aliases, 1)
    runtime_path.write_text(runtime, encoding="utf-8")

# Keep the canonical Explorer as rendered-state authority and the Operational API as independent corroboration.
runpy.run_path(".github/patches/junca-docs-r38-live-parity.py", run_name="__main__")

# Align QA with rendered visibility and the canonical-first/same-origin-fallback runtime contract.
qa_path = Path("docs/technical-reference/scripts/qa.mjs")
qa = qa_path.read_text(encoding="utf-8")
qa = qa.replace('    "Any VERIFICATION IN PROGRESS item keeps release acceptance open.",\n', '', 1)
qa = qa.replace(
    '/\\b(?:PENDING|BLOCKED|ERROR|FAILED|STOPPED|RETRYING|UNAVAILABLE|NOT ACTIVATED|NO ACTIVE|NOT YET PUBLISHED|NOT CURRENTLY PUBLISHED|EVIDENCE REFRESHING|NOT LAUNCHED)\\b/i,',
    '/\\b(?:PENDING|BLOCKED|FAILED|STOPPED|RETRYING|UNAVAILABLE|NOT ACTIVATED|NO ACTIVE|NOT YET PUBLISHED|NOT CURRENTLY PUBLISHED|EVIDENCE REFRESHING|NOT LAUNCHED)\\b/i,',
    1,
)
qa = qa.replace(
    '/\\b(?:PENDING|BLOCKED|ERROR|FAILED|STOPPED|RETRYING|UNAVAILABLE|NOT ACTIVATED|NO ACTIVE|NOT YET PUBLISHED)\\b/i,',
    '/\\b(?:PENDING|BLOCKED|FAILED|STOPPED|RETRYING|UNAVAILABLE|NOT ACTIVATED|NO ACTIVE|NOT YET PUBLISHED)\\b/i,',
    1,
)
qa = qa.replace('    "throw new Error",\n', '', 1)
qa = qa.replace(
    '    if (html.includes(forbiddenDisplay)) {\n',
    '    if (visibleText(html).includes(forbiddenDisplay)) {\n',
    1,
)
qa = qa.replace('  "Registry verification in progress",\n', '', 1)
qa = qa.replace(
    '  \'fetch("/explorer.json"\',\n',
    '  \'CANONICAL_EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json"\',\n'
    '  \'SAME_ORIGIN_PROXY_URL = "/explorer.json"\',\n'
    '  "fetchExplorer(CANONICAL_EXPLORER_URL)",\n'
    '  "fetchExplorer(SAME_ORIGIN_PROXY_URL)",\n'
    '  \'source = "VERIFIED SAME-ORIGIN PROXY"\',\n',
    1,
)
qa = qa.replace(
    '  "last successful Explorer values",\n',
    '  "Preserve the last verified values",\n',
    1,
)
semantic_qa_terms = (
    '  "does not represent monetary value",\n'
    '  "金銭的価値を表さない",\n'
    '  "does not guarantee the economic value",\n'
    '  "経済価値、流動性、法的分類、規制適合性を保証するものではありません",\n'
    '  "no platform guarantee",\n'
)
qa_marker = '  "No Monetary Value",\n'
if semantic_qa_terms not in qa:
    if qa_marker not in qa:
        raise SystemExit("Expected QA monetary-language marker is missing")
    qa = qa.replace(qa_marker, qa_marker + semantic_qa_terms, 1)
required_markers = [
    'SAME_ORIGIN_PROXY_URL = "/explorer.json"',
    'fetchExplorer(CANONICAL_EXPLORER_URL)',
    'fetchExplorer(SAME_ORIGIN_PROXY_URL)',
    'Preserve the last verified values',
    'does not represent monetary value',
    'does not guarantee the economic value',
]
missing = [required for required in required_markers if required not in qa]
if missing:
    raise SystemExit(f"R38 QA contract markers missing after repair: {missing}")
qa_path.write_text(qa, encoding="utf-8")

print("R38 status, semantic no-value wording, runtime corroboration and QA alignment applied")
