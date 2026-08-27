# Test fixtures

Media fixtures are generated on demand with ffmpeg (see
`tests/integration/test_media.py`) rather than committed, so the repository
stays free of binaries and the fixtures always match the current output spec.

Put a file here only when a test needs input that cannot be generated — a real
provider response captured for a regression test, for example.
