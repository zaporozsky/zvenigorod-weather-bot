"""Season-aware photo selection, backed by the approved S1 manifest.

No fallback to a visually incompatible season. No I/O other than local reads.
"""
from __future__ import annotations

import csv
import hashlib
import os
import random
from pathlib import Path

SEASONS = frozenset({'spring', 'summer', 'autumn', 'bare', 'winter_snow'})
EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.webp'})


def select_weather_photo(scenario: str, photo_scenarios: dict[str, str],
                         photo_dir: str | Path = 'photos',
                         manifest: str | Path = 'photos/photo_seasons.csv',
                         season: str | None = None) -> str | None:
    """Return a matching image path, or None if anything is unconfigured/missing.

    season is the current *landscape* state, not the meteorological season.
    Only explicitly approved, hash-matching catalog entries are eligible.
    """
    current = (season if season is not None else os.getenv('PHOTO_SEASON', '')).strip().lower()
    if current not in SEASONS:
        print(f'PHOTO_SELECTION: no valid PHOTO_SEASON (got {current!r}); text-only', flush=True)
        return None

    root = Path(photo_dir)
    category = photo_scenarios.get(scenario, 'default')
    if category not in {*(photo_scenarios.values()), 'default'}:
        category = 'default'
    manifest_path = Path(manifest)
    if not manifest_path.is_file():
        print(f'PHOTO_SELECTION: manifest missing ({manifest_path}); text-only', flush=True)
        return None

    candidates: list[Path] = []
    try:
        with manifest_path.open('r', encoding='utf-8-sig', newline='') as src:
            reader = csv.DictReader(src)
            required = {'path', 'weather_category', 'filename', 'season', 'review_status', 'sha256'}
            if not required.issubset(reader.fieldnames or []):
                print('PHOTO_SELECTION: invalid manifest columns; text-only', flush=True)
                return None
            for row in reader:
                if row['weather_category'] != category or row['season'] != current:
                    continue
                if row['review_status'] != 'approved':
                    continue
                rel = Path(row['path'])
                # Manifest entries must be exactly photos/<category>/<filename>.
                if (rel.is_absolute() or len(rel.parts) != 3
                    or rel.parts[0] != root.name or rel.parts[1] != category
                    or rel.parts[2] != row['filename']
                    or Path(row['filename']).suffix.lower() not in EXTENSIONS):
                    continue
                file = root / category / row['filename']
                if not file.is_file():
                    continue
                sha = row['sha256'].lower()
                if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                    continue
                h = hashlib.sha256()
                with file.open('rb') as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b''):
                        h.update(chunk)
                if h.hexdigest() == sha:
                    candidates.append(file)
    except (OSError, csv.Error) as e:
        print(f'PHOTO_SELECTION: catalog unreadable ({type(e).__name__}); text-only', flush=True)
        return None

    if not candidates:
        print(f'PHOTO_SELECTION: no approved match for {category}/{current}; text-only', flush=True)
        return None
    selected = random.choice(candidates)
    print(f'PHOTO_SELECTION: {category}/{current} candidates={len(candidates)} chosen={selected.name}', flush=True)
    return str(selected)
