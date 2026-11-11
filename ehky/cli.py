"""Command line interface.

ehky init my-video --template fact     # starter project
ehky make my-video                     # build the video (or: ehky my-video)
ehky make script.txt --media clips     # works with a plain text file too
ehky ui                                # browser interface on this computer
ehky voices | ehky doctor
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, compose, doctor, pipeline, project, tts

COMMANDS = ("init", "make", "ui", "voices", "doctor")


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
    m.add_argument("--music", help="background music file; it gets quieter while the voice speaks")
    m.add_argument("--music-volume", type=float, help="music level from 0 to 1 (default: 0.3)")
    m.add_argument("--font-size", type=int, default=0, help="subtitle size in px (default: automatic)")
    m.add_argument("--dry-run", action="store_true", help="check everything and print the plan, make nothing")
    m.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    m.add_argument("--timeout", type=int, default=1800, help="ffmpeg timeout in seconds (default: 1800)")

    u = sub.add_parser("ui", help="open the browser interface (runs only on this computer)")
    u.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: 8765)")
    u.add_argument("--no-browser", action="store_true", help="print the link instead of opening the browser")

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


def cmd_make(args: argparse.Namespace) -> int:
    overrides = {key: getattr(args, key) for key in pipeline.OVERRIDABLE}
    try:
        plan = pipeline.make_plan(
            Path(args.source),
            overrides,
            output=Path(args.output) if args.output else None,
            media=Path(args.media) if args.media else None,
            audio=Path(args.audio) if args.audio else None,
            music=Path(args.music) if args.music else None,
            font_size=args.font_size,
            force=args.force,
            dry_run=args.dry_run,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return _err(str(exc))
    for line in plan.summary():
        print(line)
    if args.dry_run:
        print("Dry run: nothing was generated.")
        return 0
    try:
        duration = pipeline.render(plan, args.timeout)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Done: {plan.out} ({duration:.1f}s)")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from . import ui

    if not 1024 <= args.port <= 65535:
        return _err("--port must be between 1024 and 65535")
    try:
        return ui.serve(args.port, open_browser=not args.no_browser)
    except OSError as exc:
        return _err(f"could not start on port {args.port}: {exc} (try --port 8766)")


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
    handlers = {
        "init": cmd_init,
        "make": cmd_make,
        "voices": cmd_voices,
        "doctor": lambda a: doctor.run(a.online),
        "ui": cmd_ui,
    }
    return handlers[args.command](args)


def main() -> None:
    sys.exit(run())
