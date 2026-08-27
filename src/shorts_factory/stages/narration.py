"""Narration stage: speech units -> a real voice track with measured timings.

The v0.3 change is that each speech unit is synthesised on its own and the
planned pauses are inserted as real silence. That costs the same per character
as one long call, and it buys the thing the old proportional-scaling approach
could never give: a *measured* start and duration for every unit, so scene cuts
and subtitles sit exactly where the voice does.

Unit audio is cached on disk by its text, so a re-render never re-synthesises a
line that has not changed.
"""

from __future__ import annotations

from pathlib import Path

from ..cost import CostEvent
from ..domain import (
    Manifest,
    ManifestScene,
    ScenePlan,
    SpeechPlan,
    SpeechTimeline,
    SpeechTimingEntry,
)
from ..errors import MediaError
from ..media import concat_with_gaps, probe, retime
from ..pipeline.checkpoint import (
    require_scenes,
    require_speech_plan,
    save_manifest,
    save_project,
    save_speech_timeline,
)
from ..pipeline.context import RunContext
from ..providers import with_retry
from ..providers.tts.speech_adapter import lead_silence_sec, segments_for
from ..utils import atomic_write_json, read_json, relative_to, sha256_text
from . import subtitles as subtitle_stage
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "narrate"


def unit_fingerprint(context: RunContext, text: str) -> str:
    """What makes one cached unit different from another.

    ``speed`` belongs in here even though it is applied after synthesis: the
    cached file on disk is already retimed, so without it a changed pace would
    reuse every unit at the old one and only new lines would move.
    """
    tts = context.providers.tts
    settings = context.settings.tts
    return sha256_text(
        "|".join(
            [
                tts.name,
                tts.model,
                settings.voice,
                settings.format,
                f"{settings.speed:g}",
                text,
            ]
        )
    )


def _load_cache(context: RunContext) -> dict[str, str]:
    path = context.workspace.narration_meta
    if not path.exists():
        return {}
    try:
        meta = read_json(path)
    except (OSError, ValueError):
        return {}
    units = meta.get("units")
    return units if isinstance(units, dict) else {}


async def synthesize_units(context: RunContext, speech: SpeechPlan) -> SpeechTimeline:
    """Synthesise each unit, insert the planned pauses, and measure the result."""
    tts = context.providers.tts
    segments = segments_for(speech)
    cache = {} if context.force else _load_cache(context)
    fresh_cache: dict[str, str] = {}
    speed = context.settings.tts.speed

    total_chars = sum(len(segment.text) for segment in segments)
    estimated = context.guard.estimate_tts_usd(tts.name, total_chars)
    context.guard.check_total(estimated, operation="tts")

    parts: list[tuple[Path, float]] = []
    entries: list[SpeechTimingEntry] = []
    cursor = lead_silence_sec(speech)
    synthesised = 0

    for segment in segments:
        destination = context.workspace.unit_audio(segment.unit_id)
        fingerprint = unit_fingerprint(context, segment.text)
        fresh_cache[segment.unit_id] = fingerprint

        if not (destination.exists() and cache.get(segment.unit_id) == fingerprint):
            await with_retry(
                f"tts:{segment.unit_id}",
                lambda s=segment, d=destination: tts.synthesize(s.text, d),
                context.settings.retry,
            )
            # Retime before measuring, never after. Every downstream duration --
            # the scene cuts, the subtitle cues, the manifest -- is read off
            # this file, so changing the pace here is the whole change.
            if speed != 1.0:
                await retime(
                    destination,
                    destination,
                    speed=speed,
                    sample_rate=context.settings.tts.sample_rate,
                )
            synthesised += 1

        info = probe(destination)
        if info.duration_sec <= 0:
            raise MediaError(f"{segment.unit_id}: TTS returned an empty clip")

        entries.append(
            SpeechTimingEntry(
                unit_id=segment.unit_id,
                start=round(cursor, 3),
                duration=info.duration_sec,
                gap_after=segment.gap_after_sec,
            )
        )
        parts.append((destination, segment.gap_after_sec))
        cursor = round(cursor + info.duration_sec + segment.gap_after_sec, 3)

    if synthesised:
        context.tracker.record(
            CostEvent(
                kind="tts",
                provider=tts.name,
                operation="synthesize",
                estimated_cost_usd=estimated,
                actual_cost_usd=context.guard.estimate_tts_usd(
                    tts.name,
                    sum(len(s.text) for s in segments if fresh_cache.get(s.unit_id)),
                ),
                metadata={"model": tts.model, "units": synthesised, "characters": total_chars},
            )
        )

    await concat_with_gaps(
        parts,
        context.workspace.narration_wav,
        sample_rate=context.settings.tts.sample_rate,
        lead_silence_sec=lead_silence_sec(speech),
    )
    measured = probe(context.workspace.narration_wav)
    if measured.duration_sec <= 0:
        raise MediaError("the assembled narration has zero duration")

    atomic_write_json(
        context.workspace.narration_meta,
        {
            "provider": tts.name,
            "model": tts.model,
            "voice": context.settings.tts.voice,
            "speed": speed,
            "characters": total_chars,
            "duration_sec": measured.duration_sec,
            "units": fresh_cache,
        },
    )
    context.log.info(
        "narration_completed",
        duration=measured.duration_sec,
        units=len(segments),
        synthesised=synthesised,
        reused=len(segments) - synthesised,
        speed=speed,
    )
    return SpeechTimeline(entries=entries, total_duration_sec=measured.duration_sec)


def build_manifest(context: RunContext, plan: ScenePlan, timeline: SpeechTimeline) -> Manifest:
    """Scene durations come from where the voice actually is, not from a guess."""
    output = context.settings.output
    if not plan.scenes:
        raise MediaError("scene plan is empty")

    entries: list[ManifestScene] = []
    cursor = 0.0
    for index, scene in enumerate(plan.scenes):
        span = timeline.span_for(scene.speech_unit_ids)
        if span is None:
            raise MediaError(f"scene {scene.id} covers no speech units")
        _, duration = span
        if index == len(plan.scenes) - 1:
            # The last scene absorbs the tail padding so the voice is never cut.
            duration = round(timeline.total_duration_sec + output.tail_padding_sec - cursor, 3)
        entries.append(
            ManifestScene(
                scene_id=scene.id,
                asset=relative_to(context.workspace.scene_clip(scene.id), context.workspace.root),
                start=round(cursor, 3),
                duration=max(round(duration, 3), 0.1),
            )
        )
        cursor = round(cursor + entries[-1].duration, 3)

    return Manifest(
        resolution=output.resolution,
        fps=output.fps,
        scenes=entries,
        voice=relative_to(context.workspace.narration_wav, context.workspace.root),
        subtitle=relative_to(context.workspace.narration_srt, context.workspace.root),
        subtitle_burn=relative_to(context.workspace.narration_ass, context.workspace.root),
    )


def plan(context: RunContext) -> StagePlan:
    try:
        speech = require_speech_plan(context.workspace)
    except Exception:
        return StagePlan(stage=STAGE_NAME, notes=["no speech plan yet; run `shorts speak` first"])
    characters = sum(len(unit.text) for unit in speech.units)
    return StagePlan(
        stage=STAGE_NAME,
        calls=[
            PlannedCall(
                kind="tts",
                provider=context.providers.tts.name,
                operation="synthesize",
                count=len(speech.units),
                estimated_cost_usd=context.guard.estimate_tts_usd(
                    context.providers.tts.name, characters
                ),
                detail=(
                    f"{len(speech.units)} units, {characters} characters "
                    "(per-unit synthesis gives measured timings)"
                ),
            )
        ],
        notes=["subtitles and manifest are generated locally at no cost"],
    )


async def run(context: RunContext) -> Manifest:
    speech = require_speech_plan(context.workspace)
    scene_plan = require_scenes(context.workspace)

    timeline = await synthesize_units(context, speech)
    save_speech_timeline(context.workspace, timeline)

    manifest = build_manifest(context, scene_plan, timeline)
    cues = subtitle_stage.build(context, scene_plan, speech, timeline)
    subtitle_stage.write(context, cues)

    save_manifest(context.workspace, manifest)
    context.project.audio_path = relative_to(
        context.workspace.narration_wav, context.workspace.root
    )
    context.project.subtitle_path = relative_to(
        context.workspace.narration_srt, context.workspace.root
    )
    context.project.manifest_path = relative_to(
        context.workspace.manifest_json, context.workspace.root
    )
    save_project(context.workspace, context.project)

    context.log.info(
        "manifest_written",
        scenes=len(manifest.scenes),
        total=manifest.total_duration_sec,
        audio=timeline.total_duration_sec,
    )
    return manifest
