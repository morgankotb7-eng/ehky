# Changelog

## 0.2.0 (2026-11-11)

- `ehky ui`: an Arabic browser interface that runs only on your computer (127.0.0.1, per-run key,
  uploads renamed by the server and size-limited). Write, pick voice/size/background, add images
  and music, download the video.
- Background music: `--music` / `music` in `ehky.toml`, looped to the video length and ducked under
  the voice automatically; `--music-volume` / `music_volume`.
- The command line and the UI now share one pipeline, so they behave the same.

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
