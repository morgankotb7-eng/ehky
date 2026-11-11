"""Project folders and starter templates.

A project is a folder with ``script.txt``, an optional ``ehky.toml`` and an optional ``media/`` folder.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

DEFAULTS: dict[str, object] = {
    "aspect": "9:16",
    "theme": "charcoal",
    "engine": "auto",
    "speaker": "Tareq",
    "voice": "ar-EG-ShakirNeural",
    "rate": "+0%",
    "subtitles": False,
    "music": "",
    "music_volume": 0.3,
    "output": "video.mp4",
}
_TYPES = {k: type(v) for k, v in DEFAULTS.items()}
NAME_PATTERN = re.compile(r"^[\w\-. ]{1,64}$")

TEMPLATES: dict[str, dict[str, object]] = {
    # Each line is read by the voice in one breath, so keep related sentences on the same line.
    "fact": {
        "about": "short vertical 'did you know' video (Reels, TikTok, Shorts)",
        "settings": {"aspect": "9:16", "theme": "charcoal"},
        "script": (
            "تعرف إن العسل مبيبوظش؟ أيوه، ممكن يقعد آلاف السنين.\n"
            "علماء لقوا عسل في مقابر فرعونية عمره أكتر من تلات آلاف سنة، ولسه ينفع يتاكل.\n"
            "السبب إن فيه سكر كتير ومية قليلة، فالبكتيريا مبتعرفش تعيش فيه.\n"
            "لو عجبتك المعلومة، تابعني وهقولك واحدة جديدة كل يوم.\n"
        ),
    },
    "tutorial": {
        "about": "horizontal how-to video with steps (YouTube, LinkedIn)",
        "settings": {"aspect": "16:9", "theme": "forest", "subtitles": True},
        "script": (
            "النهارده هوريك إزاي تعمل باسوورد قوي، في تلات خطوات بس.\n"
            "أول حاجة، خليه طويل. اتناشر حرف على الأقل.\n"
            "تاني حاجة، استخدم جملة انت فاكرها بدل كلمة واحدة.\n"
            "وتالت حاجة، متكررش نفس الباسوورد في أكتر من موقع.\n"
            "بس كده. جرّب، وقولّي عملت إيه.\n"
        ),
    },
    "ad": {
        "about": "square promo video for a product or shop (Facebook, Instagram)",
        "settings": {"aspect": "1:1", "theme": "ember"},
        "script": (
            "لو بتدوّر على هدية حلوة ومش غالية، استنى ثانية.\n"
            "إحنا لسه منزّلين تشكيلة جديدة، والأسعار هتعجبك بجد.\n"
            "بنوصّل لحد البيت، ولو حاجة مش عاجباك بنبدّلها ببلاش.\n"
            "ابعتلنا رسالة دلوقتي، قبل ما الكمية تخلص.\n"
        ),
    },
}


def load_settings(folder: Path) -> dict[str, object]:
    """Read ehky.toml (if any) and check every key and type, so typos fail loudly."""
    settings = dict(DEFAULTS)
    path = folder / "ehky.toml"
    if not path.is_file():
        return settings
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    for key, value in data.items():
        if key not in DEFAULTS:
            raise ValueError(f"{path}: unknown setting {key!r} (known: {', '.join(DEFAULTS)})")
        kind = _TYPES[key]
        accepted = (int, float) if kind is float else kind
        # bool is a subclass of int, so `music_volume = true` must be rejected explicitly
        if not isinstance(value, accepted) or (kind is not bool and isinstance(value, bool)):
            raise ValueError(f"{path}: {key} must be {_TYPES[key].__name__}")
        settings[key] = value
    return settings


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def create(folder: Path, template: str) -> Path:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r} (choose: {', '.join(TEMPLATES)})")
    if not NAME_PATTERN.match(folder.name):
        raise ValueError(f"invalid project name: {folder.name!r}")
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"{folder} already exists and is not empty")
    spec = TEMPLATES[template]
    settings = {**DEFAULTS, **spec["settings"]}  # type: ignore[dict-item]
    (folder / "media").mkdir(parents=True, exist_ok=True)
    (folder / "script.txt").write_text(str(spec["script"]), encoding="utf-8")
    lines = [f"# ehky settings ({template} template). Remove a line to use the default."]
    notes = {"music": '  # e.g. "music.mp3", a file in this folder; it gets quieter while the voice speaks'}
    lines += [f"{k} = {_toml_value(v)}{notes.get(k, '')}" for k, v in settings.items()]
    (folder / "ehky.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "media" / "README.txt").write_text(
        "Put your images or video clips here (png, jpg, webp, mp4, mov, mkv, webm).\n"
        "They are used in name order. Leave the folder empty to use the animated background.\n",
        encoding="utf-8",
    )
    return folder
