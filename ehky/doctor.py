"""``ehky doctor``: check the machine, explain how to fix anything missing."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__, fonts, tts


def _line(ok: bool, label: str, detail: str) -> bool:
    print(f"  [{'ok' if ok else '!!'}] {label}: {detail}")
    return ok


def _has_libass(ffmpeg: str) -> bool:
    result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    return " ass " in result.stdout


def run(online: bool = False) -> int:
    print(f"ehky {__version__} on {platform.system()} {platform.release()}, Python {platform.python_version()}")
    py_ok = sys.version_info >= (3, 11)
    required = [_line(py_ok, "Python", platform.python_version() + ("" if py_ok else " (3.11 or newer needed)"))]
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    required.append(_line(bool(ffmpeg), "ffmpeg", ffmpeg or "missing - https://ffmpeg.org/download.html"))
    required.append(_line(bool(ffprobe), "ffprobe", ffprobe or "missing (comes with ffmpeg)"))

    print("optional:")
    if ffmpeg:
        libass = _has_libass(ffmpeg)
        _line(
            libass,
            "subtitles (libass)",
            "ok" if libass else "this ffmpeg build cannot draw subtitles; videos without subtitles still work",
        )
    font = fonts.find_arabic_font()
    _line(bool(font), "Arabic font", font[0] if font else "none found (needed only for --subtitles)")
    _line(
        tts.voicetut_available(),
        "Egyptian voice (voicetut)",
        "installed"
        if tts.voicetut_available()
        else f"not installed, see {tts.VOICETUT_SETUP} (the online voice is used meanwhile)",
    )

    if online:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                tts.synthesize_edge("مرحبا", tts.DEFAULT_VOICE, Path(tmp) / "t.mp3", attempts=2)
                required.append(_line(True, "online voice", "reachable"))
            except RuntimeError as exc:
                required.append(_line(False, "online voice", str(exc)))

    ok = all(required)
    print("Ready." if ok else "Fix the [!!] items above, then run ehky doctor again.")
    return 0 if ok else 1
