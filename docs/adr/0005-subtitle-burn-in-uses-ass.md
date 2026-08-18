# 0005 — Burn subtitles from generated ASS, ship SRT

## Status

Accepted.

## Context

Burning `narration.srt` with `subtitles=...:force_style='MarginV=320,FontSize=64'`
silently produced no visible text. ffmpeg converts SRT to ASS using the default
384x288 script resolution, so a margin expressed in output pixels pushes the
text off screen and a pixel font size is meaningless.

## Decision

The subtitle stage writes both files from the same cues:

- `subtitles/narration.srt` — the deliverable, for upload and review;
- `subtitles/narration.ass` — the burn-in source, with an explicit
  `PlayResX/PlayResY` matching the output and a full style line.

Composition burns the ASS when it exists and skips `force_style` entirely; the
style already lives in the file.

## Consequences

- Every subtitle setting in `config/settings.yaml` is in real output pixels.
- Typography (outline, shadow, margins, weight) is under our control and visible
  in a diffable text file.
- `force_style` remains supported for a caller that supplies only an SRT.
