"""Narration engines. Every engine returns word timings so subtitles can follow the voice.

* ``voicetut`` - Egyptian Arabic neural voice that runs on your machine (VoiceTut-TTS).
* ``edge``     - Microsoft Edge online voices: light, fast, free, no API key.
"""

from __future__ import annotations

import asyncio
import os
import re
import ssl
import tempfile
import time
import wave
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

ENGINES = ("auto", "voicetut", "edge")
DEFAULT_SPEAKER = "Tareq"
VOICETUT_SPEAKERS = {
    "male": [
        "Tareq",
        "Ahmed",
        "Ali",
        "Hassan",
        "Karim",
        "Mahmoud",
        "Mohammed",
        "Mostafa",
        "Ramy",
        "Shaker",
        "Yehia",
        "Youssef",
    ],
    "female": ["Hadeer", "Hanan", "Mariam", "Rana", "Sarah", "Yasmin", "Yara"],
}
VOICETUT_SETUP = "https://github.com/morgankotb7-eng/ehky#egyptian-voice-setup"
DEFAULT_VOICE = "ar-EG-ShakirNeural"
EDGE_VOICES = {
    "ar-EG-ShakirNeural": "Egyptian, male",
    "ar-EG-SalmaNeural": "Egyptian, female",
    "ar-SA-HamedNeural": "Saudi, male",
    "ar-SA-ZariyahNeural": "Saudi, female",
}
VOICE_PATTERN = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$")
SPEAKER_PATTERN = re.compile(r"^[A-Za-z]{2,20}$")
RATE_PATTERN = re.compile(r"^[+-]\d{1,3}%$")
SENTENCE_GAP = 0.28  # seconds of silence between sentences (voicetut)
_TICKS = 10_000_000  # Edge offsets are in 100 ns units


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Narration:
    words: list[Word]
    exact: bool  # True when timings come from the voice engine, False when estimated


def validate_voice(name: str) -> str:
    if not VOICE_PATTERN.match(name):
        raise ValueError(f"invalid voice name: {name!r} (example: {DEFAULT_VOICE})")
    return name


def validate_speaker(name: str) -> str:
    if not SPEAKER_PATTERN.match(name):
        raise ValueError(f"invalid speaker name: {name!r} (example: {DEFAULT_SPEAKER})")
    return name


def validate_rate(rate: str) -> str:
    if not RATE_PATTERN.match(rate):
        raise ValueError(f"invalid rate: {rate!r} (use e.g. -10% or +15%)")
    return rate


def voicetut_available() -> bool:
    """The Egyptian voice needs three packages: voicetut-tts, its OmniVoice backbone and PyTorch."""
    return all(find_spec(name) is not None for name in ("voicetut_tts", "omnivoice", "torch"))


def resolve_engine(engine: str) -> str:
    if engine == "auto":
        return "voicetut" if voicetut_available() else "edge"
    if engine == "voicetut" and not voicetut_available():
        raise RuntimeError(f"the Egyptian voice is not installed. Setup steps: {VOICETUT_SETUP} (or use --engine edge)")
    return engine


def estimate_words(sentence: str, start: float, end: float) -> list[Word]:
    """Split a sentence's time span across its words by character share."""
    tokens = sentence.split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    words, cursor = [], start
    for token, weight in zip(tokens, weights, strict=True):
        piece = (end - start) * weight / total
        words.append(Word(token, cursor, cursor + piece))
        cursor += piece
    return words


AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def from_recording(sentences: list[str], duration: float) -> Narration:
    """Your own recorded voice: spread the script over the recording by character share (estimated)."""
    total = sum(len(s) for s in sentences) or 1
    words: list[Word] = []
    cursor = 0.0
    for sentence in sentences:
        span = duration * len(sentence) / total
        words.extend(estimate_words(sentence, cursor, cursor + span))
        cursor += span
    return Narration(words, exact=False)


# ---------------------------------------------------------------- voicetut


def synthesize_voicetut(sentences: list[str], speaker: str, out: Path) -> Narration:
    """One clip per sentence (exact sentence timing), joined into one .wav file."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # keep the terminal output clean
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    from voicetut_tts import VoiceTutTTS

    model = VoiceTutTTS.from_pretrained("mohammedaly22/VoiceTut-TTS")
    words: list[Word] = []
    with tempfile.TemporaryDirectory(prefix="ehky-tts-") as tmp, wave.open(str(out), "wb") as dst:
        cursor = 0.0
        for i, sentence in enumerate(sentences):
            clip = Path(tmp) / f"{i}.wav"
            model.synthesize(sentence, speaker=speaker, num_step=16, output=str(clip))
            with wave.open(str(clip), "rb") as src:
                if i == 0:
                    dst.setparams(src.getparams())
                rate = src.getframerate()
                frame_bytes = src.getsampwidth() * src.getnchannels()
                length = src.getnframes() / rate
                dst.writeframes(src.readframes(src.getnframes()))
            words.extend(estimate_words(sentence, cursor, cursor + length))
            dst.writeframes(b"\x00" * int(SENTENCE_GAP * rate) * frame_bytes)
            cursor += length + SENTENCE_GAP
    return Narration(words, exact=False)


# -------------------------------------------------------------------- edge


def _network_settings() -> str | None:
    """Behind a TLS-inspecting proxy, trust EHKY_CA_BUNDLE and use HTTPS_PROXY.

    Certificate verification always stays on. Returns the proxy URL to use, if any.
    """
    import edge_tts.communicate as comm

    bundle = os.environ.get("EHKY_CA_BUNDLE")
    if not bundle:
        return None
    comm._SSL_CTX = ssl.create_default_context(cafile=os.path.expanduser(bundle))
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


async def _edge_once(text: str, voice: str, rate: str, proxy: str | None) -> tuple[bytes, list[Word]]:
    import edge_tts

    kwargs: dict[str, str] = {"rate": rate, "boundary": "WordBoundary"}
    if proxy:
        kwargs["proxy"] = proxy
    communicate = edge_tts.Communicate(text, voice, **kwargs)
    audio = bytearray()
    words: list[Word] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start = chunk["offset"] / _TICKS
            words.append(Word(chunk["text"], start, start + chunk["duration"] / _TICKS))
    return bytes(audio), words


def synthesize_edge(text: str, voice: str, out: Path, rate: str = "+0%", attempts: int = 3) -> Narration:
    """The online service sometimes drops a request, so retry a few times before failing."""
    proxy = _network_settings()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            audio, words = asyncio.run(_edge_once(text, voice, rate, proxy))
            if audio:
                out.write_bytes(audio)
                return Narration(words, exact=bool(words))
            last = RuntimeError("no audio received")
        except Exception as exc:  # noqa: BLE001 - network errors come in many types
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"the online voice failed after {attempts} tries: {last}")
