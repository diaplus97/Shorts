# 0003 — Call FFmpeg directly

## Status

Accepted.

## Context

Python video frameworks add a large dependency, hide the actual filtergraph and
tend to lag ffmpeg's own features. The composition here is not complicated:
normalise, concat, mix, burn subtitles, encode.

## Decision

A thin wrapper (`media/ffmpeg.py`) runs the binary and turns a non-zero exit
into `MediaError` with the tail of stderr. Normalisation, composition and
probing build their own argument lists.

Every scene is normalised to identical codec parameters first, so the concat
demuxer can stitch them without a second re-encode.

## Consequences

- The exact command is visible in the logs and can be pasted into a shell.
- ffmpeg becomes a hard runtime dependency, which `shorts doctor` checks.
- Media tests are marked and skipped when ffmpeg is absent.
