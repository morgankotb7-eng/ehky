"""The make pipeline, shared by the command line and the browser UI.

``make_plan`` checks every input before any slow work starts; ``render`` does the slow work.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import compose, fonts, project, subs, text, tts

OVERRIDABLE = ("engine", "speaker", "voice", "rate", "aspect", "theme", "subtitles", "music_volume")


@dataclass
class Plan:
    script: str
    lines: list[str]
    settings: dict
    media: list[Path]
    out: Path
    font: tuple[str, Path] | None
    engine: str
    audio: Path | None
    music: Path | None
    ffmpeg: str
    ffprobe: str
    font_size: int

    @property
    def voice_label(self) -> str:
        s = self.settings
        return {"voicetut": s["speaker"], "edge": s["voice"], "recording": str(self.audio)}[self.engine]

    def summary(self) -> list[str]:
        s = self.settings
        width, height = compose.ASPECTS[s["aspect"]]
        background = f"{len(self.media)} media file(s)" if self.media else f"{s['theme']} background"
        music = f"{self.music.name} (ducked under the voice)" if self.music else "none"
        return [
            f"voice:      {self.voice_label} ({self.engine})",
            f"format:     {s['aspect']} ({width}x{height}), {background}",
            f"subtitles:  {'on (' + self.font[0] + ')' if self.font else 'off'}",
            f"music:      {music}",
            f"script:     {len(self.script)} characters, {len(text.split_sentences(self.script))} sentence(s)",
            f"output:     {self.out}",
        ]


def _existing_file(path: Path, allowed: set[str], what: str) -> Path:
    if not (path.is_file() and path.suffix.lower() in allowed):
        raise ValueError(f"{what} must be an existing {'/'.join(sorted(allowed))} file: {path}")
    return path


def make_plan(
    source: Path,
    overrides: dict | None = None,
    *,
    output: Path | None = None,
    media: Path | None = None,
    audio: Path | None = None,
    music: Path | None = None,
    font_size: int = 0,
    force: bool = False,
    dry_run: bool = False,
) -> Plan:
    """Resolve and validate every input. Raises ValueError/RuntimeError with a clear message."""
    if source.is_dir():
        settings = project.load_settings(source)
        script_path = source / "script.txt"
        media_dir = source / "media" if (source / "media").is_dir() else None
        base = source
    elif source.is_file():
        settings, script_path, media_dir, base = dict(project.DEFAULTS), source, None, Path(".")
        settings["output"] = source.with_suffix(".mp4").name
    else:
        raise ValueError(f"not found: {source}")
    if not script_path.is_file():
        raise ValueError(f"no script.txt in {source}")

    for key, value in (overrides or {}).items():
        if key in OVERRIDABLE and value is not None:
            settings[key] = value
    if media is not None:
        if not media.is_dir():
            raise ValueError(f"media folder not found: {media}")
        media_dir = media
    out = output if output else base / str(settings["output"])

    raw_script = script_path.read_text(encoding="utf-8-sig")
    script = text.validate(raw_script)
    if settings["aspect"] not in compose.ASPECTS:
        raise ValueError(f"unknown aspect {settings['aspect']!r}")
    if settings["theme"] not in compose.THEMES:
        raise ValueError(f"unknown theme {settings['theme']!r}")
    if settings["engine"] not in tts.ENGINES:
        raise ValueError(f"unknown engine {settings['engine']!r}")
    tts.validate_speaker(str(settings["speaker"]))
    tts.validate_voice(str(settings["voice"]))
    tts.validate_rate(str(settings["rate"]))
    volume = float(settings["music_volume"])
    if not 0.0 <= volume <= 1.0:
        raise ValueError("music_volume must be between 0 and 1")
    settings["music_volume"] = volume
    if font_size and not 16 <= font_size <= 300:
        raise ValueError("--font-size must be between 16 and 300")
    if out.suffix.lower() != ".mp4":
        raise ValueError("output must end with .mp4")
    if out.exists() and not force and not dry_run:
        raise ValueError(f"{out} already exists (use --force to overwrite)")

    media_files = compose.find_media(media_dir) if media_dir else []
    if media is not None and not media_files:
        raise ValueError(f"no images or videos in {media_dir}")
    if music is None and settings["music"]:
        music = base / str(settings["music"])
    if music is not None:
        music = _existing_file(music, tts.AUDIO_EXT, "music")
    if audio is not None:
        audio = _existing_file(audio, tts.AUDIO_EXT, "--audio")

    font = fonts.find_arabic_font() if settings["subtitles"] else None
    if settings["subtitles"] and font is None:
        raise ValueError("no Arabic font found for subtitles; install Noto Sans Arabic or Cairo")
    engine = "recording" if audio else tts.resolve_engine(str(settings["engine"]))
    ffmpeg, ffprobe = compose.require_tools()
    if settings["subtitles"] and not compose.has_libass(ffmpeg):
        raise ValueError(
            "your ffmpeg cannot draw subtitles (it was built without libass). "
            "Use --no-subtitles, or install an ffmpeg with libass (see the README)"
        )
    return Plan(
        script=script,
        lines=text.split_lines(raw_script),
        settings=settings,
        media=media_files,
        out=out,
        font=font,
        engine=engine,
        audio=audio,
        music=music,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        font_size=font_size,
    )


STEPS = {
    "recording": "Reading your recording",
    "voicetut": "Recording the voice (local model, can take a few minutes)",
    "edge": "Recording the voice",
}


def render(plan: Plan, timeout: int = 1800, log: Callable[[str], None] = print) -> float:
    """Make the video. Returns its duration in seconds."""
    s = plan.settings
    width, height = compose.ASPECTS[s["aspect"]]
    plan.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ehky-") as tmp:
        tmpdir = Path(tmp)
        log(f"[1/2] {STEPS[plan.engine]}...")
        if plan.engine == "recording":
            audio = plan.audio
            length = compose.probe_duration(audio, plan.ffprobe)
            narration = tts.from_recording(text.split_sentences(plan.script), length)
        elif plan.engine == "voicetut":
            audio = tmpdir / "voice.wav"
            narration = tts.synthesize_voicetut(plan.lines, str(s["speaker"]), audio)
        else:
            audio = tmpdir / "voice.mp3"
            narration = tts.synthesize_edge(plan.script, str(s["voice"]), audio, str(s["rate"]))
        duration = compose.probe_duration(audio, plan.ffprobe) + 0.5
        ass = None
        if plan.font:
            size = plan.font_size or round(min(width, height) * 0.065)
            ass = tmpdir / "subs.ass"
            ass.write_text(subs.build_ass(narration.words, width, height, plan.font[0], size), encoding="utf-8")
        log("[2/2] Rendering the video...")
        compose.run(
            compose.build_ffmpeg_args(
                plan.media,
                audio,
                ass,
                plan.out,
                duration,
                str(s["aspect"]),
                str(s["theme"]),
                plan.font[1] if plan.font else None,
                plan.ffmpeg,
                music=plan.music,
                music_volume=float(s["music_volume"]),
            ),
            timeout,
        )
    return duration
