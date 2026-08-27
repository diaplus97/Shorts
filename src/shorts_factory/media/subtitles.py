"""SRT generation (spec section 40).

Mobile-first rules: at most two lines, short cues, and a bottom margin that
keeps text clear of the Shorts UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import SubtitleSettings
from ..utils import (
    atomic_write_text,
    distribute_durations,
    split_for_subtitles,
    visible_length,
    wrap_cue,
)

Position = Literal["bottom", "top"]


class SubtitleSegment(BaseModel):
    """One scene's worth of on-screen text and where it belongs."""

    model_config = ConfigDict(extra="forbid")

    text: str
    start: float = Field(ge=0)
    duration: float = Field(ge=0)
    position: Position = "bottom"


class SubtitleCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str
    #: Moves the cue off important action (spec v0.2 section 40).
    position: Position = "bottom"
    #: At most one word is stressed. Two highlights in one cue is no highlight.
    emphasis: str | None = None

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def format_ass_timestamp(seconds: float) -> str:
    """ASS uses H:MM:SS.cc with centisecond precision."""
    if seconds < 0:
        seconds = 0.0
    centiseconds = round(seconds * 100)
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def cues_for_segment(
    text: str,
    start: float,
    duration: float,
    settings: SubtitleSettings,
) -> list[tuple[float, float, str]]:
    """Split one narration segment into timed cues covering ``duration``."""
    max_chars = settings.max_chars_per_line * settings.max_lines
    chunks = [chunk for chunk in split_for_subtitles(text, max_chars) if chunk.strip()]
    if not chunks:
        return []

    # A segment too short to hold one cue at the minimum length keeps a single cue.
    max_cues = max(1, int(duration // settings.min_cue_duration_sec))
    while len(chunks) > max_cues:
        lengths = [len(chunks[i]) + len(chunks[i + 1]) for i in range(len(chunks) - 1)]
        index = lengths.index(min(lengths))
        chunks[index : index + 2] = [f"{chunks[index]} {chunks[index + 1]}"]

    weights = [float(max(visible_length(chunk), 1)) for chunk in chunks]
    spans = distribute_durations(
        weights,
        duration,
        min_each=min(settings.min_cue_duration_sec, duration / len(chunks)),
        max_each=duration,
    )

    out: list[tuple[float, float, str]] = []
    cursor = start
    for chunk, span in zip(chunks, spans, strict=True):
        out.append(
            (
                round(cursor, 3),
                round(cursor + span, 3),
                wrap_cue(chunk, settings.max_chars_per_line, settings.max_lines),
            )
        )
        cursor += span
    return out


def build_cues(
    segments: list[SubtitleSegment],
    settings: SubtitleSettings,
) -> list[SubtitleCue]:
    """Turn per-scene segments into numbered cues, in playback order."""
    cues: list[SubtitleCue] = []
    for segment in segments:
        if segment.duration <= 0 or not segment.text.strip():
            continue
        spans = cues_for_segment(segment.text, segment.start, segment.duration, settings)
        for cue_start, cue_end, cue_text in spans:
            cues.append(
                SubtitleCue(
                    index=len(cues) + 1,
                    start=cue_start,
                    end=cue_end,
                    text=cue_text,
                    position=segment.position,
                )
            )
    return cues


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks = [
        f"{cue.index}\n{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n{cue.text}\n"
        for cue in cues
    ]
    return "\n".join(blocks)


def write_srt(cues: list[SubtitleCue], path: str | Path) -> Path:
    return atomic_write_text(path, render_srt(cues))


def render_ass(cues: list[SubtitleCue], settings: SubtitleSettings, width: int, height: int) -> str:
    """Render cues as ASS with an explicit PlayRes.

    Burning the SRT directly and styling it with ``force_style`` does not work:
    ffmpeg converts SRT to ASS with the default 384x288 script resolution, so a
    pixel-based MarginV pushes the text off screen. Declaring PlayRes here means
    every style number below is in real output pixels.
    """
    header = "\n".join(
        [
            "[Script Info]",
            "; Generated by shorts_factory. Burn-in source; narration.srt is the deliverable.",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            _style_line("Default", 2, settings),
            # Alignment 8 anchors to the top, for shots whose action sits low.
            _style_line("Top", 8, settings),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )
    events = [
        (
            f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},"
            f"{'Top' if cue.position == 'top' else 'Default'},,0,0,0,,"
            f"{_ass_text(cue, settings)}"
        )
        for cue in cues
    ]
    return header + "\n" + "\n".join(events) + "\n"


def _ass_text(cue: SubtitleCue, settings: SubtitleSettings) -> str:
    """Cue text with the stressed word coloured, line breaks escaped for ASS."""
    text = cue.text
    word = (cue.emphasis or "").strip()
    if word and word in text:
        highlighted = f"{{\\c{settings.emphasis_colour}}}{word}{{\\r}}"
        text = text.replace(word, highlighted, 1)
    return text.replace("\n", "\\N")


def _style_line(name: str, alignment: int, settings: SubtitleSettings) -> str:
    return (
        f"Style: {name},{settings.font_name},{settings.font_size},"
        "&H00FFFFFF,&H000000FF,&H00101010,&H80000000,"
        "-1,0,0,0,100,100,0,0,"
        f"1,{settings.outline},{settings.shadow},{alignment},"
        f"{settings.margin_h},{settings.margin_h},{settings.margin_v},1"
    )


def write_ass(
    cues: list[SubtitleCue], path: str | Path, settings: SubtitleSettings, width: int, height: int
) -> Path:
    return atomic_write_text(path, render_ass(cues, settings, width, height))


def force_style(settings: SubtitleSettings) -> str:
    """libass style string, used only when burning a bare SRT.

    Kept for callers that supply their own SRT. The pipeline burns the generated
    ASS instead, because ``force_style`` numbers are in ASS script units.
    """
    return ",".join(
        [
            f"FontName={settings.font_name}",
            f"FontSize={settings.font_size}",
            "PrimaryColour=&H00FFFFFF",
            "OutlineColour=&H00000000",
            "BackColour=&H80000000",
            "BorderStyle=1",
            "Outline=3",
            "Shadow=1",
            "Bold=1",
            "Alignment=2",
            f"MarginV={settings.margin_v}",
            "MarginL=60",
            "MarginR=60",
        ]
    )
