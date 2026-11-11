"""Command line interface.

ehky init my-video --template fact     # starter project
ehky make my-video                     # build the video (or: ehky my-video)
ehky make script.txt --media clips     # works with a plain text file too
ehky voices | ehky doctor
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import __version__, compose, doctor, fonts, project, subs, text, tts

COMMANDS = ("init", "make", "voices", "doctor")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ehky", description="Arabic text -> narrated short video. Free, no API key.")
    p.add_argument("--version", action="version", version=f"ehky {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", help="create a starter project from a template")
    i.add_argument("name", help="folder to create")
    i.add_argument("--template", choices=sorted(project.TEMPLATES), default="fact")

    m = sub.add_parser("make", help="build a video from a project folder or a script file")
    m.add_argument("source", help="project folder, or a UTF-8 .txt script")
    m.add_argument("-o", "--output", help="output .mp4")
    m.add_argument("--media", help="folder with your images/clips (overrides the project's media/)")
    m.add_argument("--audio", help="use your own recorded voice (wav/mp3/m4a/ogg/flac) instead of a model")
    m.add_argument("--engine", choices=tts.ENGINES, help="auto (default), voicetut (Egyptian, local) or edge")
    m.add_argument("--speaker", help="voicetut speaker (default: Tareq)")
    m.add_argument("--voice", help="edge voice (see: ehky voices)")
    m.add_argument("--rate", help="edge speaking speed, e.g. -10%% or +15%%")
    m.add_argument("--aspect", choices=sorted(compose.ASPECTS))
    m.add_argument("--theme", choices=sorted(compose.THEMES), help="background when there is no media")
    m.add_argument(
        "--subtitles",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="burn in Arabic subtitles with the spoken word highlighted",
    )
    m.add_argument("--font-size", type=int, default=0, help="subtitle size in px (default: automatic)")
    m.add_argument("--dry-run", action="store_true", help="check everything and print the plan, make nothing")
    m.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    m.add_argument("--timeout", type=int, default=1800, help="ffmpeg timeout in seconds (default: 1800)")

    sub.add_parser("voices", help="list voices")
    d = sub.add_parser("doctor", help="check that everything ehky needs is installed")
    d.add_argument("--online", action="store_true", help="also test the online voice service")
    return p


def _err(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def cmd_init(args: argparse.Namespace) -> int:
    try:
        folder = project.create(Path(args.name), args.template)
    except (ValueError, OSError) as exc:
        return _err(str(exc))
    print(f"Created {folder}/ ({project.TEMPLATES[args.template]['about']})")
    print(f"  1. edit {folder / 'script.txt'}")
    print(f"  2. (optional) put images or clips in {folder / 'media'}")
    print(f"  3. ehky make {folder}")
    return 0


def _plan(args: argparse.Namespace) -> dict:
    """Resolve and validate every input before any slow work starts."""
    source = Path(args.source)
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

    for key in ("engine", "speaker", "voice", "rate", "aspect", "theme", "subtitles"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    if args.media:
        media_dir = Path(args.media)
        if not media_dir.is_dir():
            raise ValueError(f"media folder not found: {media_dir}")
    out = Path(args.output) if args.output else base / str(settings["output"])

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
    if args.font_size and not 16 <= args.font_size <= 300:
        raise ValueError("--font-size must be between 16 and 300")
    if out.suffix.lower() != ".mp4":
        raise ValueError("output must end with .mp4")
    if out.exists() and not args.force and not args.dry_run:
        raise ValueError(f"{out} already exists (use --force to overwrite)")
    media = compose.find_media(media_dir) if media_dir else []
    if args.media and not media:
        raise ValueError(f"no images or videos in {media_dir}")
    font = fonts.find_arabic_font() if settings["subtitles"] else None
    if settings["subtitles"] and font is None:
        raise ValueError("no Arabic font found for subtitles; install Noto Sans Arabic or Cairo")
    audio = Path(args.audio) if args.audio else None
    if audio and not (audio.is_file() and audio.suffix.lower() in tts.AUDIO_EXT):
        raise ValueError(f"--audio must be an existing {'/'.join(sorted(tts.AUDIO_EXT))} file")
    engine = "recording" if audio else tts.resolve_engine(str(settings["engine"]))
    ffmpeg, ffprobe = compose.require_tools()
    return {
        "script": script,
        "lines": text.split_lines(raw_script),
        "settings": settings,
        "media": media,
        "out": out,
        "font": font,
        "engine": engine,
        "audio": audio,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
    }


def cmd_make(args: argparse.Namespace) -> int:
    try:
        plan = _plan(args)
    except (ValueError, RuntimeError, OSError) as exc:
        return _err(str(exc))
    s, media, out, font, engine = plan["settings"], plan["media"], plan["out"], plan["font"], plan["engine"]
    voice = {"voicetut": s["speaker"], "edge": s["voice"], "recording": plan["audio"]}[engine]
    width, height = compose.ASPECTS[s["aspect"]]
    background = f"{len(media)} media file(s)" if media else f"{s['theme']} background"
    print(f"voice:      {voice} ({engine})")
    print(f"format:     {s['aspect']} ({width}x{height}), {background}")
    print(f"subtitles:  {'on (' + font[0] + ')' if font else 'off'}")
    print(f"script:     {len(plan['script'])} characters, {len(text.split_sentences(plan['script']))} sentence(s)")
    print(f"output:     {out}")
    if args.dry_run:
        print("Dry run: nothing was generated.")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ehky-") as tmp:
        tmpdir = Path(tmp)
        try:
            step = {
                "recording": "Reading your recording",
                "voicetut": "Recording the voice (local model, can take a few minutes)",
                "edge": "Recording the voice",
            }[engine]
            print(f"[1/2] {step}...")
            if engine == "recording":
                audio = plan["audio"]
                length = compose.probe_duration(audio, plan["ffprobe"])
                narration = tts.from_recording(text.split_sentences(plan["script"]), length)
            elif engine == "voicetut":
                audio = tmpdir / "voice.wav"
                narration = tts.synthesize_voicetut(plan["lines"], str(s["speaker"]), audio)
            else:
                audio = tmpdir / "voice.mp3"
                narration = tts.synthesize_edge(plan["script"], str(s["voice"]), audio, str(s["rate"]))
            duration = compose.probe_duration(audio, plan["ffprobe"]) + 0.5
            ass = None
            if font:
                size = args.font_size or round(min(width, height) * 0.065)
                ass = tmpdir / "subs.ass"
                ass.write_text(subs.build_ass(narration.words, width, height, font[0], size), encoding="utf-8")
            print("[2/2] Rendering the video...")
            compose.run(
                compose.build_ffmpeg_args(
                    media,
                    audio,
                    ass,
                    out,
                    duration,
                    str(s["aspect"]),
                    str(s["theme"]),
                    font[1] if font else None,
                    plan["ffmpeg"],
                ),
                args.timeout,
            )
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"Done: {out} ({duration:.1f}s)")
    return 0


def cmd_voices(_: argparse.Namespace) -> int:
    state = "installed" if tts.voicetut_available() else f"not installed, see {tts.VOICETUT_SETUP}"
    print(f"voicetut (Egyptian, runs on your machine, {state})")
    for gender, names in tts.VOICETUT_SPEAKERS.items():
        print(
            f"  {gender}: {', '.join(names)}  (default: {tts.DEFAULT_SPEAKER})"
            if gender == "male"
            else f"  {gender}: {', '.join(names)}"
        )
    print("edge (online, free, no API key)")
    for name, label in tts.EDGE_VOICES.items():
        print(f"  {name}  ({label})")
    return 0


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "make")  # `ehky my-video` == `ehky make my-video`
    args = build_parser().parse_args(argv)
    handlers = {"init": cmd_init, "make": cmd_make, "voices": cmd_voices, "doctor": lambda a: doctor.run(a.online)}
    return handlers[args.command](args)


def main() -> None:
    sys.exit(run())
