# Contributing

Thanks for helping. Bug reports, Arabic script fixes, new templates and new voices are all welcome.

## Setup

```bash
git clone https://github.com/morgankotb7-eng/ehky && cd ehky
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e . ruff
```

You also need ffmpeg on your PATH.

## Before you open a pull request

```bash
python -m unittest discover -s tests
ruff check . && ruff format --check .
ehky doctor
```

- Keep the core dependency-free apart from `edge-tts`. Heavy features stay optional.
- Add a test for every bug fix and every new option.
- Arabic text in templates should be natural Egyptian colloquial, not MSA.
- If you change subtitle code, render a video with `--subtitles` and check the word order by eye.

## Reporting a bug

Include the output of `ehky doctor`, the exact command, and the full error message.
