"""Subtitle stage (spec v0.3 sections 26-27).

Captions are built from speech units, not by re-cutting a narration string. A
unit is one breath and one idea, which is exactly the right size for a caption,
so a cue can never change in the middle of a thought.

A unit longer than the cue box still gets wrapped onto two lines, but it is
never split into two cues with different timings.
"""

from __future__ import annotations

from pathlib import Path

from ..domain import ScenePlan, SpeechPlan, SpeechTimeline
from ..media import SubtitleCue, write_ass, write_srt
from ..pipeline.context import RunContext
from ..utils import wrap_cue

STAGE_NAME = "subtitles"


def build(
    context: RunContext,
    plan: ScenePlan,
    speech: SpeechPlan,
    timeline: SpeechTimeline,
) -> list[SubtitleCue]:
    """One cue per speech unit, timed by measurement and placed by its scene."""
    settings = context.settings.subtitles
    position_by_unit = {
        unit_id: scene.subtitle_position
        for scene in plan.scenes
        for unit_id in scene.speech_unit_ids
    }

    cues: list[SubtitleCue] = []
    for unit in speech.units:
        entry = timeline.entry_for(unit.id)
        if entry is None or entry.duration <= 0 or not unit.text.strip():
            continue
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start=entry.start,
                # Hold the cue through the pause that follows, so text does not
                # flash off during a deliberate silence.
                end=round(entry.end + entry.gap_after, 3),
                text=wrap_cue(unit.text, settings.max_chars_per_line, settings.max_lines),
                position=position_by_unit.get(unit.id, "bottom"),
            )
        )
    return cues


def write(context: RunContext, cues: list[SubtitleCue]) -> tuple[Path, Path]:
    """Write the SRT deliverable and the ASS used for burn-in."""
    output = context.settings.output
    srt_path = write_srt(cues, context.workspace.narration_srt)
    ass_path = write_ass(
        cues,
        context.workspace.narration_ass,
        context.settings.subtitles,
        output.width,
        output.height,
    )
    context.log.info("subtitles_written", cues=len(cues), srt=str(srt_path), ass=str(ass_path))
    return srt_path, ass_path
