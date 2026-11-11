"""Find an installed font that can draw Arabic, so subtitles never show empty boxes."""

from __future__ import annotations

import os
from pathlib import Path

# (ASS family name, file name to look for). Ordered by preference.
CANDIDATES = [
    ("Cairo", "Cairo"),
    ("Noto Sans Arabic", "NotoSansArabic"),
    ("Noto Naskh Arabic", "NotoNaskhArabic"),
    ("Tahoma", "tahoma"),
    ("Arial", "arial"),
    ("Segoe UI", "segoeui"),
    ("Geeza Pro", "GeezaPro"),
    ("DejaVu Sans", "DejaVuSans-Bold"),
    ("DejaVu Sans", "DejaVuSans"),
]


def search_dirs() -> list[Path]:
    home = Path.home()
    dirs = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".fonts",
        home / ".local/share/fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        home / "Library/Fonts",
    ]
    windir = os.environ.get("WINDIR")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    return [d for d in dirs if d.is_dir()]


def find_arabic_font(dirs: list[Path] | None = None) -> tuple[str, Path] | None:
    """Return (family, containing directory) for the first usable font, or None."""
    roots = dirs if dirs is not None else search_dirs()
    files: list[Path] = []
    for root in roots:
        files.extend(p for p in root.rglob("*") if p.suffix.lower() in {".ttf", ".otf", ".ttc"})
    for family, stem in CANDIDATES:
        for path in files:
            if path.stem.lower().startswith(stem.lower()):
                return family, path.parent
    return None
