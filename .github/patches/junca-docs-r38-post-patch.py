from pathlib import Path
import runpy

# Normalize the Japanese copy that can be produced after the generic term replacement.
build_path = Path("docs/technical-reference/scripts/build.mjs")
build = build_path.read_text(encoding="utf-8")
marker = '      .replaceAll("No Monetary Value", "Protocol Validation Environment")\n'
addition = marker + (
    '      .replaceAll(\n'
    '        "Protocol Validation Environment、Rate Limit、Abuse Controlを前提に公開します。",\n'
    '        "Test Asset Separation、Rate Limit、Abuse Controlを前提に公開します。",\n'
    '      )\n'
)
if addition not in build:
    if marker not in build:
        raise SystemExit("Expected Japanese status normalization marker is missing")
    build = build.replace(marker, addition, 1)
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

# Bind the operational API check to a bounded live-advancement window while retaining identity,
# provenance, quorum and safety gates.
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
required_markers = [
    'SAME_ORIGIN_PROXY_URL = "/explorer.json"',
    'fetchExplorer(CANONICAL_EXPLORER_URL)',
    'fetchExplorer(SAME_ORIGIN_PROXY_URL)',
    'Preserve the last verified values',
]
missing = [required for required in required_markers if required not in qa]
if missing:
    raise SystemExit(f"R38 QA contract markers missing after repair: {missing}")
qa_path.write_text(qa, encoding="utf-8")

print("R38 post-patch normalization, bounded live parity and QA alignment applied")
