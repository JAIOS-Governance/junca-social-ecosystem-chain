#!/usr/bin/env python3
"""Bind the governed six-card JAIOS News records to controlled Docs-hosted photo URLs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def build(base_path: Path, mapping_path: Path, output_path: Path) -> None:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    items = base.get("items", [])
    mapped = mapping.get("items", [])
    if len(items) != 6 or len(mapped) != 6:
        raise SystemExit("JAIOS controlled image binding requires exactly six records")

    by_id = {item["id"]: item for item in mapped}
    if len(by_id) != 6:
        raise SystemExit("Controlled image mapping IDs must be unique")

    for item in items:
        binding = by_id.get(item.get("id"))
        if binding is None:
            raise SystemExit(f"Missing controlled image mapping for {item.get('id')}")
        parsed = urlparse(binding["public_url"])
        if parsed.scheme != "https" or parsed.netloc != "docs.jaios-governance.org":
            raise SystemExit(f"Uncontrolled public image URL: {binding['public_url']}")
        item["image_url"] = binding["public_url"]
        item["image_delivery"] = "controlled-docs-origin"

    base["schema"] = "jaios-institutional-news-photo/v3"
    base["delivery_release"] = mapping["delivery_release"]
    base.setdefault("selection_policy", {})["controlled_docs_delivery_required"] = True
    base["selection_policy"]["external_image_hotlink_prohibited"] = True
    output_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"JAIOS_DOCS_HOSTED_DATA_PASS records={len(items)} release={mapping['delivery_release']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.base, args.mapping, args.output)


if __name__ == "__main__":
    main()
