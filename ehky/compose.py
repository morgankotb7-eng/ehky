"""ffmpeg composition: media (or an animated background) + narration + optional subtitles -> mp4."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
THEMES = {  # two-colour slow animated gradient + light film grain + vignette
    "charcoal": ("0x121417", "0x2b2f36"),
    "sand": ("0xf3ece0", "0xd8c6a6"),
    "forest": ("0x0d1a16", "0x24453a"),
    "ember": ("0x1a0f0c", "0x5a2a1a"),
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
FPS = 30
FADE = 0.5  # crossfade between media items, seconds


def find_media(folder: Path) -> list[Path]:
    exts = IMAGE_EXT | VIDEO_EXT
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts)


def _esc_filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument (handles Windows drive colons)."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def segment_length(duration: float, count: int, fade: float = FADE) -> float:
    """Length of each media segment so that, after crossfades, the total equals ``duration``."""
    return (duration + (count - 1) * fade) / count


def _media_inputs(media: list[Path], width: int, height: int, duration: float):
    args: list[str] = []
    filters: list[str] = []
    per = segment_length(duration, len(media))
    for i, path in enumerate(media):
        if path.suffix.lower() in IMAGE_EXT:
            args += ["-loop", "1", "-t", f"{per:.3f}", "-i", str(path)]
            frames = max(round(per * FPS), 1)
            filters.append(
                f"[{i}:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2},"
                f"zoompan=z='min(1+0.0005*on,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s={width}x{height}:fps={FPS},setsar=1,format=yuv420p[v{i}]"
            )
        else:
            args += ["-stream_loop", "-1", "-t", f"{per:.3f}", "-i", str(path)]
            filters.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={FPS},setsar=1,format=yuv420p[v{i}]"
            )
    last = "[v0]"
    for i in range(1, len(media)):
        offset = i * (per - FADE)
        label = "[bg]" if i == len(media) - 1 else f"[x{i}]"
        filters.append(f"{last}[v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}{label}")
        last = label
    if len(media) == 1:
        filters.append("[v0]null[bg]")
    return args, filters


def build_ffmpeg_args(
    media: list[Path],
    audio: Path,
    ass: Path | None,
    out: Path,
    duration: float,
    aspect: str,
    theme: str = "charcoal",
    fonts_dir: Path | None = None,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Pure function: the complete ffmpeg argv (easy to test, shown with --dry-run)."""
    width, height = ASPECTS[aspect]
    args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if media:
        inputs, filters = _media_inputs(media, width, height, duration)
        args += inputs
        audio_index = len(media)
    else:
        c0, c1 = THEMES[theme]
        args += [
            "-f",
            "lavfi",
            "-i",
            f"gradients=s={width}x{height}:c0={c0}:c1={c1}:n=2:speed=0.015:rate={FPS}:duration={duration:.3f}",
        ]
        filters = ["[0:v]format=yuv420p,noise=c0s=4:c0f=t,vignette=PI/6,setsar=1[bg]"]
        audio_index = 1

    args += ["-i", str(audio)]
    if ass is not None:
        sub = f"ass='{_esc_filter_path(ass)}'"
        if fonts_dir:
            sub += f":fontsdir='{_esc_filter_path(fonts_dir)}'"
        filters.append(f"[bg]{sub}[out]")
    else:
        filters.append("[bg]null[out]")
    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-map",
        f"{audio_index}:a",
        "-af",
        f"afade=t=out:st={max(duration - 0.4, 0):.3f}:d=0.4",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    return args


def probe_duration(path: Path, ffprobe: str = "ffprobe") -> float:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(result.stdout.strip())


def require_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found on PATH. Install ffmpeg: https://ffmpeg.org/download.html")
    return ffmpeg, ffprobe


def run(args: list[str], timeout: int) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg timed out after {timeout}s (raise it with --timeout)") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed:\n{exc.stderr.strip()[-2000:]}") from exc
