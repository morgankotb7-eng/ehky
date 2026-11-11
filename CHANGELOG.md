# Changelog

## 0.1.0 (2026-11-11)

First release.

- `ehky init` with three templates: `fact` (9:16), `tutorial` (16:9), `ad` (1:1).
- `ehky make` for a project folder or a plain `.txt` script.
- Voices: VoiceTut-TTS Egyptian voices (local, optional), Edge voices (online, free), or your own
  recording with `--audio`.
- Arabic subtitles with correct shaping and right-to-left order, highlighting the spoken word.
- Animated backgrounds (`charcoal`, `sand`, `forest`, `ember`) and crossfades between media.
- Early validation of every input, `--dry-run`, `--force`, `--timeout`, `ehky doctor`.
- Edge voice retries on dropped requests; proxy support with certificate checks kept on.
- Clear early error when ffmpeg was built without libass (e.g. Homebrew on macOS).
- CI on Linux, Windows and macOS with Python 3.11 to 3.13, rendering a real video each run.
