"""ASS subtitles. libass does the Arabic shaping and right-to-left ordering.

The style uses Encoding -1 so libass picks the base direction from the text itself; with the
default value it lays an Arabic line out left-to-right as soon as one word has its own colour.

Words are grouped into short lines; the word being spoken is highlighted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tts import Word

HIGHLIGHT = "&H0045C8F5&"  # warm yellow (ASS colours are BGR)


@dataclass(frozen=True)
class Line:
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def group_lines(words: list[Word], max_chars: int = 32, max_pause: float = 0.6) -> list[Line]:
    """Start a new line when it would get too long, after a sentence end, or after a pause."""
    lines: list[Line] = []
    current: list[Word] = []
    for word in words:
        if current:
            length = len(" ".join(w.text for w in current)) + 1 + len(word.text)
            ends_sentence = current[-1].text[-1:] in ".!?؟"
            pause = word.start - current[-1].end
            if length > max_chars or ends_sentence or pause > max_pause:
                lines.append(Line(current))
                current = []
        current.append(word)
    if current:
        lines.append(Line(current))
    return lines


def _ts(seconds: float) -> str:
    cs = max(round(seconds * 100), 0)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def events(lines: list[Line], highlight: bool = True, hold: float = 0.35) -> list[tuple[float, float, str]]:
    """(start, end, ass_text) events. With highlight, one event per word, else one per line."""
    out: list[tuple[float, float, str]] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1].start if i + 1 < len(lines) else line.end + hold
        line_end = min(line.end + hold, nxt)
        if not highlight:
            out.append((line.start, line_end, _escape(line.text)))
            continue
        for j, word in enumerate(line.words):
            end = line.words[j + 1].start if j + 1 < len(line.words) else line_end
            parts = [
                f"{{\\c{HIGHLIGHT}}}{_escape(w.text)}{{\\r}}" if k == j else _escape(w.text)
                for k, w in enumerate(line.words)
            ]
            out.append((word.start if j else line.start, end, " ".join(parts)))
    return out


def max_chars_for(width: int, font_size: int, margin: int = 70) -> int:
    """Characters that fit on one line, so libass never has to wrap (wrapping breaks RTL order)."""
    return max(int((width - 2 * margin) / (font_size * 0.62)), 8)


def build_ass(words: list[Word], width: int, height: int, font: str, font_size: int, highlight: bool = True) -> str:
    margin_v = round(height * 0.14)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H00141414,&H96000000,"
        f"-1,0,0,0,100,100,0,0,1,5,2,2,70,70,{margin_v},-1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = [
        f"Dialogue: 0,{_ts(s)},{_ts(e)},Default,,0,0,0,,{t}"
        for s, e, t in events(group_lines(words, max_chars_for(width, font_size)), highlight)
        if e > s
    ]
    return header + "\n".join(body) + "\n"
