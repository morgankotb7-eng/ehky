"""Script parsing: split Arabic text into sentences and subtitle-sized chunks."""

from __future__ import annotations

import re

MAX_SCRIPT_CHARS = 5000
_SENTENCE_END = re.compile(r"(?<=[.!?؟!۔\n])\s+")


def normalize(script: str) -> str:
    """Collapse whitespace and strip control characters (keeps newlines as spaces)."""
    cleaned = "".join(ch for ch in script if ch == "\n" or ch.isprintable())
    return re.sub(r"\s+", " ", cleaned).strip()


def validate(script: str) -> str:
    text = normalize(script)
    if not text:
        raise ValueError("script is empty")
    if len(text) > MAX_SCRIPT_CHARS:
        raise ValueError(f"script is {len(text)} characters; the limit is {MAX_SCRIPT_CHARS}")
    return text


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def split_lines(script: str, max_chars: int = 220) -> list[str]:
    """Speech chunks for the voice model: one per line of the script, as the writer grouped them.

    Reading a whole line (often two or three sentences) in one go keeps natural intonation;
    reading every sentence alone sounds choppy. Very long lines are split at sentence ends.
    """
    chunks: list[str] = []
    for raw in script.splitlines():
        line = normalize(raw)
        if not line:
            continue
        current = ""
        for sentence in split_sentences(line):
            if current and len(current) + 1 + len(sentence) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
    return chunks
