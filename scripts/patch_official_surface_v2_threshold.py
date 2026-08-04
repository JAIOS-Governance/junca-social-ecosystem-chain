#!/usr/bin/env python3
"""One-time source repair for the controlled-photo dimensions in the V2 workflow."""

from pathlib import Path

path = Path('.github/workflows/official-surface-final-acceptance-v2.yml')
text = path.read_text(encoding='utf-8')
old = 'assert image.width > 500 and image.height > 250, image.size'
new = 'assert image.width >= 480 and image.height >= 270, image.size'
count = text.count(old)
if count == 0:
    print('OFFICIAL_SURFACE_V2_THRESHOLD_ALREADY_REPAIRED')
else:
    if count != 2:
        raise SystemExit(f'Unexpected threshold occurrence count: {count}')
    path.write_text(text.replace(old, new), encoding='utf-8')
    print(f'OFFICIAL_SURFACE_V2_THRESHOLD_REPAIRED occurrences={count}')
