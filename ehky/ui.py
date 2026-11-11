"""``ehky ui``: a small browser interface that runs on your machine.

Security model: the server binds to 127.0.0.1 only, checks the Host header (blocks DNS
rebinding), and every API call needs a random per-run token that only the opened page knows.
Uploads are renamed by the server, limited to known extensions and capped in size.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import shutil
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, compose, pipeline, project, tts

MAX_BODY = 200 * 1024 * 1024  # 200 MB of uploads per video
MAX_MEDIA_FILES = 30
MEDIA_EXT = compose.IMAGE_EXT | compose.VIDEO_EXT


class Job:
    """At most one video is rendered at a time; this holds its state."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"  # idle | running | done | error
        self.log: list[str] = []
        self.error = ""
        self.video: Path | None = None
        self.id = ""

    def snapshot(self) -> dict:
        with self.lock:
            return {"state": self.state, "log": list(self.log), "error": self.error, "id": self.id}


def _decode(item: dict, allowed: set[str], target: Path) -> Path:
    name = str(item.get("name", ""))
    ext = Path(name).suffix.lower()
    if ext not in allowed:
        raise ValueError(f"file type not allowed: {ext or name!r}")
    try:
        data = base64.b64decode(str(item.get("data", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("a file could not be read") from exc
    if not data:
        raise ValueError(f"empty file: {name!r}")
    path = target.with_suffix(ext)  # the server picks the name; user names never touch the disk
    path.write_bytes(data)
    return path


def prepare_project(payload: dict, root: Path) -> tuple[Path, dict, Path | None]:
    """Turn a request into a project folder. Returns (folder, overrides, music)."""
    script = str(payload.get("script", ""))
    folder = root / "project"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "media").mkdir(parents=True)
    (folder / "script.txt").write_text(script, encoding="utf-8")

    media = payload.get("media") or []
    if not isinstance(media, list) or len(media) > MAX_MEDIA_FILES:
        raise ValueError(f"up to {MAX_MEDIA_FILES} images or clips")
    for i, item in enumerate(media):
        _decode(item, MEDIA_EXT, folder / "media" / f"{i:02d}")
    music = None
    if payload.get("music"):
        music = _decode(payload["music"], tts.AUDIO_EXT, folder / "music")

    overrides = {key: payload.get(key) for key in pipeline.OVERRIDABLE}
    if overrides.get("music_volume") is not None:
        overrides["music_volume"] = float(overrides["music_volume"])
    if overrides.get("subtitles") is not None:
        overrides["subtitles"] = bool(overrides["subtitles"])
    return folder, overrides, music


def info() -> dict:
    ffmpeg = shutil.which("ffmpeg")
    return {
        "version": __version__,
        "voicetut": tts.voicetut_available(),
        "speakers": tts.VOICETUT_SPEAKERS,
        "default_speaker": tts.DEFAULT_SPEAKER,
        "edge_voices": tts.EDGE_VOICES,
        "aspects": list(compose.ASPECTS),
        "themes": list(compose.THEMES),
        "ffmpeg": bool(ffmpeg),
        "subtitles": bool(ffmpeg) and compose.has_libass(ffmpeg),
        "templates": {name: str(t["script"]) for name, t in project.TEMPLATES.items()},
    }


def make_handler(token: str, port: int, job: Job, root: Path):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    page = files("ehky").joinpath("ui.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ehky"

        def log_message(self, *_args) -> None:  # keep the terminal quiet
            return

        def _send(self, status: int, body: bytes, kind: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def _guard(self, need_token: bool) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._json(HTTPStatus.FORBIDDEN, {"error": "bad host"})
                return False
            if need_token:
                query = parse_qs(urlparse(self.path).query)
                given = self.headers.get("X-Ehky-Token") or (query.get("t") or [""])[0]
                if not secrets.compare_digest(given, token):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token"})
                    return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/":
                if self._guard(need_token=False):
                    csp = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
                    csp += "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
                    self._send(
                        HTTPStatus.OK,
                        page.encode("utf-8"),
                        "text/html; charset=utf-8",
                        {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"},
                    )
                return
            if not self._guard(need_token=True):
                return
            if route == "/api/info":
                self._json(HTTPStatus.OK, info())
            elif route == "/api/job":
                self._json(HTTPStatus.OK, job.snapshot())
            elif route == "/api/video":
                with job.lock:
                    video = job.video if job.state == "done" else None
                if not video or not video.is_file():
                    self._json(HTTPStatus.NOT_FOUND, {"error": "no video yet"})
                    return
                body = video.read_bytes()
                name = f"ehky-{job.id}.mp4"
                self._send(HTTPStatus.OK, body, "video/mp4", {"Content-Disposition": f'inline; filename="{name}"'})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard(need_token=True):
                return
            if urlparse(self.path).path != "/api/make":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "files are too big (limit 200 MB)"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("bad request")
            except (json.JSONDecodeError, ValueError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request"})
                return
            with job.lock:  # claim the single render slot before touching any files
                if job.state == "running":
                    self._json(HTTPStatus.CONFLICT, {"error": "a video is already being made"})
                    return
                previous = (job.state, job.error)
                job.state = "running"
            try:
                folder, overrides, music = prepare_project(payload, root)
                plan = pipeline.make_plan(folder, overrides, music=music, force=True)
            except (ValueError, RuntimeError, OSError, TypeError, AttributeError) as exc:
                with job.lock:
                    job.state, job.error = previous
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            with job.lock:
                job.log, job.error, job.video = plan.summary(), "", None
                job.id = secrets.token_hex(4)
            threading.Thread(target=_run, args=(plan, job), daemon=True).start()
            self._json(HTTPStatus.ACCEPTED, {"id": job.id})

    return Handler


def _run(plan: pipeline.Plan, job: Job) -> None:
    def log(line: str) -> None:
        with job.lock:
            job.log.append(line)

    try:
        duration = pipeline.render(plan, log=log)
        with job.lock:
            job.log.append(f"Done ({duration:.1f}s)")
            job.state, job.video = "done", plan.out
    except Exception as exc:  # noqa: BLE001 - anything that fails must reach the page
        with job.lock:
            job.state, job.error = "error", str(exc)


def serve(port: int = 8765, open_browser: bool = True) -> int:
    token = secrets.token_urlsafe(18)
    job = Job()
    with tempfile.TemporaryDirectory(prefix="ehky-ui-") as tmp:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, port, job, Path(tmp)))
        url = f"http://127.0.0.1:{port}/?t={token}"
        print(f"ehky is running at {url}")
        print("Only this computer can open it. Press Ctrl+C to stop.")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            server.server_close()
    return 0
