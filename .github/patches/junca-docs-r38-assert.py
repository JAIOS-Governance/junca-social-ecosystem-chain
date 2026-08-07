import html as html_module
import json
import re
from pathlib import Path

root = Path("docs/technical-reference/dist")
index_bytes = (root / "index.html").stat().st_size
if index_bytes > 140_000:
    raise SystemExit(f"Overview output exceeds bounded R38 gate: {index_bytes} bytes")
print(f"Overview output size: {index_bytes} bytes")

patterns = [
    r"No Monetary Value",
    r"\bNo Active\b",
    r"\bNot Activated\b",
    r"\bNot Yet Published\b",
    r"\bNOT CURRENTLY PUBLISHED\b",
    r"\bEVIDENCE REFRESHING\b",
    r"\bNot Launched\b",
    r"\bPENDING\b",
    r"\bBLOCKED\b",
    r"does not represent monetary value",
    r"金銭的価値を表さない",
    r"does not guarantee the economic value",
    r"経済価値、流動性、法的分類、規制適合性を保証するものではありません",
    r"no platform guarantee",
]
failures = []
for path in root.rglob("*.html"):
    source = path.read_text(encoding="utf-8")
    visible = re.sub(r"<script[\s\S]*?</script>", " ", source, flags=re.I)
    visible = re.sub(r"<style[\s\S]*?</style>", " ", visible, flags=re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = html_module.unescape(re.sub(r"\s+", " ", visible))
    for pattern in patterns:
        match = re.search(pattern, visible, flags=re.I)
        if match:
            failures.append(f"{path}: {match.group(0)}")
if failures:
    raise SystemExit("Prohibited visible status or no-value language remains:\n" + "\n".join(failures))

status_audit = json.loads((root / "status-language-audit.json").read_text(encoding="utf-8"))
runtime_audit = json.loads((root / "current-runtime-audit.json").read_text(encoding="utf-8"))
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
if status_audit.get("result") != "PASS":
    raise SystemExit("Status-language audit did not pass")
if runtime_audit.get("result") != "PASS":
    raise SystemExit("Current-runtime audit did not pass")
if manifest.get("public_status_language_policy", {}).get("result") != "PASS":
    raise SystemExit("Release manifest status-language gate did not pass")
if manifest.get("runtime_evidence_endpoint") not in {
    "https://explorer.jaios-governance.org/explorer.json",
    "https://docs.jaios-governance.org/explorer.json",
}:
    raise SystemExit("Runtime evidence endpoint is outside the approved canonical/fallback routes")
if manifest.get("runtime_evidence_source_mode") not in {
    "CANONICAL EXPLORER",
    "VERIFIED SAME-ORIGIN PROXY",
}:
    raise SystemExit("Runtime evidence source mode is not verified")

print("Independent R38 visible-language, no-value wording, manifest and endpoint assertion PASS")
