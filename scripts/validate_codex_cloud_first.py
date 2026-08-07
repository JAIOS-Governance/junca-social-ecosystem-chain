#!/usr/bin/env python3
"""Validate the mandatory PC-complete-independent Codex cloud baseline."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:
    raise SystemExit("Python 3.11 or newer is required.") from exc

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "evidence" / "codex-cloud-health"
EVIDENCE_FILE = EVIDENCE_DIR / "latest.json"

REQUIRED_FILES = (
    "AGENTS.md",
    ".codex/config.toml",
    ".codex/agents/production.toml",
    ".codex/agents/review.toml",
    ".codex/agents/deployment.toml",
    ".codex/agents/recovery.toml",
    ".agents/skills/junca-cloud-first-governance/SKILL.md",
    "docs/CODEX_PC_COMPLETE_INDEPENDENCE_POLICY.md",
    "scripts/validate_codex_cloud_first.py",
    ".github/workflows/codex-cloud-health.yml",
)

REQUIRED_POLICY_PHRASES = (
    "PC Complete Independence",
    "personal computer",
    "must never be a required execution dependency",
    "GitHub-hosted Actions",
    "CEO",
)

REQUIRED_CONFIG_FEATURES = (
    "apps",
    "hooks",
    "memories",
    "multi_agent",
    "remote_plugin",
    "shell_tool",
    "skill_mcp_dependency_install",
)

FORBIDDEN_CRITICAL_PATTERNS = {
    "self-hosted runner": re.compile(r"runs-on\s*:\s*(?:\[.*\bself-hosted\b.*\]|self-hosted)", re.I),
    "localhost dependency": re.compile(r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?", re.I),
    "Windows workstation path": re.compile(r"\b[A-Za-z]:\\(?:Users|Desktop|Documents)\\", re.I),
    "GitHub Desktop requirement": re.compile(r"\b(?:must|required|必須).{0,80}GitHub Desktop\b", re.I | re.S),
    "VS Code requirement": re.compile(r"\b(?:must|required|必須).{0,80}(?:VS Code|Visual Studio Code)\b", re.I | re.S),
    "PC always-on requirement": re.compile(r"(?:PC|desktop|workstation).{0,80}(?:always[- ]on|常時起動|常時オンライン)", re.I | re.S),
}

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

CRITICAL_TEXT_FILES = (
    "AGENTS.md",
    ".codex/config.toml",
    ".agents/skills/junca-cloud-first-governance/SKILL.md",
    ".github/workflows/codex-cloud-health.yml",
)


def load_toml(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid TOML: {exc}")
        return {}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(errors: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in REQUIRED_FILES:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing required file: {relative}")
            continue
        data = path.read_bytes()
        if not data.endswith(b"\n"):
            errors.append(f"{relative}: missing final newline")
        hashes[relative] = hashlib.sha256(data).hexdigest()
        text = data.decode("utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{relative}: possible secret material detected")

    policy_path = ROOT / "docs/CODEX_PC_COMPLETE_INDEPENDENCE_POLICY.md"
    if policy_path.is_file():
        policy = policy_path.read_text(encoding="utf-8")
        for phrase in REQUIRED_POLICY_PHRASES:
            if phrase not in policy:
                errors.append(f"policy: required phrase missing: {phrase}")

    config = load_toml(ROOT / ".codex/config.toml", errors)
    instructions = str(config.get("developer_instructions", ""))
    for phrase in ("every personal computer", "Codex Cloud", "GitHub-hosted Actions", "CEO"):
        if phrase not in instructions:
            errors.append(f"config: cloud-first instruction missing: {phrase}")

    features = config.get("features", {})
    if not isinstance(features, dict):
        errors.append("config: [features] table missing")
    else:
        for name in REQUIRED_CONFIG_FEATURES:
            if features.get(name) is not True:
                errors.append(f"config: feature must be enabled: {name}")

    if "file_opener" in config:
        errors.append("config: file_opener is prohibited in the mandatory cloud baseline")

    agents = config.get("agents", {})
    if not isinstance(agents, dict) or agents.get("enabled") is not True:
        errors.append("config: multi-agent layer must be enabled")
    else:
        for name in ("production", "review", "deployment", "recovery"):
            declaration = agents.get(name)
            if not isinstance(declaration, dict):
                errors.append(f"config: agent declaration missing: {name}")
                continue
            if declaration.get("config_file") != f"agents/{name}.toml":
                errors.append(f"config: agent path mismatch: {name}")

    workflow_path = ROOT / ".github/workflows/codex-cloud-health.yml"
    if workflow_path.is_file():
        workflow = workflow_path.read_text(encoding="utf-8")
        for token in ("schedule:", "workflow_dispatch:", "pull_request:", "push:", "ubuntu-latest", "upload-artifact@v4"):
            if token not in workflow:
                errors.append(f"workflow: required cloud audit token missing: {token}")

    for relative in CRITICAL_TEXT_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN_CRITICAL_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{relative}: prohibited local dependency: {label}")

    return hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    hashes = validate(errors)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    evidence = {
        "schema": "junca.codex-cloud-health.v1",
        "status": "PASS" if not errors else "FAIL",
        "generated_at_utc": now,
        "repository": os.getenv("GITHUB_REPOSITORY", ""),
        "ref": os.getenv("GITHUB_REF", ""),
        "commit_sha": os.getenv("GITHUB_SHA", ""),
        "runner_environment": os.getenv("RUNNER_ENVIRONMENT", ""),
        "runner_os": os.getenv("RUNNER_OS", ""),
        "pc_dependency_allowed": False,
        "required_files": list(REQUIRED_FILES),
        "file_sha256": hashes,
        "errors": errors,
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_FILE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"EVIDENCE: {EVIDENCE_FILE.relative_to(ROOT)}")
        return 1

    if not args.quiet:
        print("OK: PC-complete-independent Codex cloud baseline is valid.")
        print(f"OK: {len(hashes)} required files present and hashed.")
        print(f"EVIDENCE: {EVIDENCE_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
