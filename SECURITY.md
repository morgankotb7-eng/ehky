# Security

Please report security problems privately through
[GitHub security advisories](https://github.com/morgankotb7-eng/ehky/security/advisories/new),
not in public issues.

ehky runs ffmpeg as a subprocess with an argument list (never through a shell), validates voice
and speaker names against strict patterns, and never disables TLS certificate checks.
