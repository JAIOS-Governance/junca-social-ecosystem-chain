#!/usr/bin/env python3
"""Apply a release-bound browser cache convergence boundary to one public HTML artifact."""

from __future__ import annotations

import argparse
from pathlib import Path


def apply(source: Path, output: Path, marker: str, surface: str) -> None:
    html = source.read_text(encoding="utf-8")
    if "</head>" not in html:
        raise SystemExit("HTML head boundary is missing")
    release_meta = f'<meta name="official-surface-release" content="{marker}">'
    cache_block = (
        release_meta
        + '<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">'
        + '<meta http-equiv="Pragma" content="no-cache">'
        + '<meta http-equiv="Expires" content="0">'
        + f'<script id="official-cache-convergence">(function(){{var r={marker!r},k="official-surface-release:{surface}";try{{if(localStorage.getItem(k)!==r){{localStorage.setItem(k,r);if("serviceWorker" in navigator){{navigator.serviceWorker.getRegistrations().then(function(xs){{xs.forEach(function(x){{x.unregister();}});}});}}if("caches" in window){{caches.keys().then(function(xs){{xs.forEach(function(x){{caches.delete(x);}});}});}}}}}}catch(e){{}}}})();</script>'
    )
    if 'name="official-surface-release"' in html:
        import re

        html = re.sub(
            r'<meta name="official-surface-release"[^>]*>.*?<script id="official-cache-convergence">.*?</script>',
            cache_block,
            html,
            count=1,
            flags=re.DOTALL,
        )
    else:
        html = html.replace("</head>", f"{cache_block}</head>", 1)
    output.write_text(html, encoding="utf-8")
    print(f"PUBLIC_CACHE_CONVERGENCE_PASS surface={surface} marker={marker} bytes={len(html.encode('utf-8'))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--surface", required=True)
    args = parser.parse_args()
    apply(args.source, args.output, args.marker, args.surface)


if __name__ == "__main__":
    main()
