"""Subtitle stage (spec section 40).

Cues are derived from scene narration and the final scene timings, so a cue can
never drift away from the picture it belongs to.
"""

from __future__ import annotations

from pathlib import Path

from ..domain import Manifest, ScenePlan
from ..media import SubtitleCue, build_cues, write_ass, write_srt
from ..pipeline.context import RunContext

STAGE_NAME = "subtitles"


def segments_from(plan: ScenePlan, manifest: Manifest) -> list[tuple[str, float, float]]:
    by_id = {scene.scene_id: scene for scene in manifest.scenes}
    segments: list[tuple[str, float, float]] = []
    for scene in plan.scenes:
        entry = by_id.get(scene.id)
        if entry is None:
            continue
        segments.append((scene.narration, entry.start, entry.duration))
    return segments


def build(context: RunContext, plan: ScenePlan, manifest: Manifest) -> list[SubtitleCue]:
    return build_cues(segments_from(plan, manifest), context.settings.subtitles)


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
