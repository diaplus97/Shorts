"""Narration stage: one TTS pass, then lock picture timing to the real audio.

The whole narration is synthesised in a single call for voice consistency and
fewer API calls (spec section 39). Scene durations are then rescaled to the
measured audio length, which is what keeps voice and picture together.
"""

from __future__ import annotations

from ..cost import CostEvent
from ..domain import Manifest, ManifestScene, ScenePlan, ScriptResult
from ..errors import MediaError, PipelineValidationError
from ..media import probe
from ..pipeline.checkpoint import (
    require_scenes,
    require_script,
    save_manifest,
    save_project,
)
from ..pipeline.context import RunContext
from ..providers import with_retry
from ..utils import atomic_write_json, distribute_durations, read_json, relative_to, sha256_text
from . import subtitles as subtitle_stage
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "narrate"


def narration_fingerprint(context: RunContext, text: str) -> str:
    tts = context.providers.tts
    settings = context.settings.tts
    return sha256_text("|".join([tts.name, tts.model, settings.voice, settings.format, text]))


def audio_is_current(context: RunContext, fingerprint: str) -> bool:
    """True when narration.wav was produced from exactly this text and voice."""
    meta_path = context.workspace.narration_meta
    if not context.workspace.narration_wav.exists() or not meta_path.exists():
        return False
    try:
        meta = read_json(meta_path)
    except (OSError, ValueError):
        return False
    return meta.get("fingerprint") == fingerprint


async def synthesize(context: RunContext, script: ScriptResult) -> float:
    """Produce narration.wav if needed and return its duration in seconds."""
    tts = context.providers.tts
    text = script.narration
    fingerprint = narration_fingerprint(context, text)

    if not context.force and audio_is_current(context, fingerprint):
        info = probe(context.workspace.narration_wav)
        context.log.info("narration_reused", duration=info.duration_sec)
        return info.duration_sec

    estimated = context.guard.estimate_tts_usd(tts.name, len(text))
    context.guard.check_total(estimated, operation="tts")

    result = await with_retry(
        "tts:narration",
        lambda: tts.synthesize(text, context.workspace.narration_wav),
        context.settings.retry,
    )
    context.tracker.record(
        CostEvent(
            kind="tts",
            provider=tts.name,
            operation="synthesize",
            estimated_cost_usd=estimated,
            actual_cost_usd=estimated,
            metadata={"model": tts.model, "characters": result.characters},
        )
    )

    info = probe(context.workspace.narration_wav)
    if info.duration_sec <= 0:
        raise MediaError("TTS produced an audio file with zero duration")

    atomic_write_json(
        context.workspace.narration_meta,
        {
            "fingerprint": fingerprint,
            "provider": tts.name,
            "model": tts.model,
            "voice": context.settings.tts.voice,
            "characters": result.characters,
            "duration_sec": info.duration_sec,
        },
    )
    context.log.info(
        "narration_completed", duration=info.duration_sec, characters=result.characters
    )
    return info.duration_sec


def build_manifest(context: RunContext, plan: ScenePlan, audio_duration: float) -> Manifest:
    """Rescale planned scene durations onto the real audio length."""
    output = context.settings.output
    total = round(audio_duration + output.tail_padding_sec, 3)
    count = len(plan.scenes)
    if count == 0:
        raise MediaError("scene plan is empty")

    scene_settings = context.settings.scenes
    min_each = min(scene_settings.min_scene_duration_sec, total / count)
    max_each = max(scene_settings.max_scene_duration_sec, total / count)
    durations = distribute_durations(
        [scene.duration_sec for scene in plan.scenes],
        total,
        min_each=min_each,
        max_each=max_each,
    )

    entries: list[ManifestScene] = []
    cursor = 0.0
    for scene, duration in zip(plan.scenes, durations, strict=True):
        entries.append(
            ManifestScene(
                scene_id=scene.id,
                asset=relative_to(context.workspace.scene_clip(scene.id), context.workspace.root),
                start=round(cursor, 3),
                duration=duration,
            )
        )
        cursor = round(cursor + duration, 3)

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
        script = require_script(context.workspace)
    except PipelineValidationError:
        return StagePlan(stage=STAGE_NAME, notes=["no script yet; run the writer stage first"])
    characters = len(script.narration)
    return StagePlan(
        stage=STAGE_NAME,
        calls=[
            PlannedCall(
                kind="tts",
                provider=context.providers.tts.name,
                operation="synthesize",
                estimated_cost_usd=context.guard.estimate_tts_usd(
                    context.providers.tts.name, characters
                ),
                detail=f"{characters} characters, one call",
            )
        ],
        notes=["subtitles and manifest are generated locally at no cost"],
    )


async def run(context: RunContext) -> Manifest:
    script = require_script(context.workspace)
    scene_plan = require_scenes(context.workspace)

    audio_duration = await synthesize(context, script)
    manifest = build_manifest(context, scene_plan, audio_duration)

    cues = subtitle_stage.build(context, scene_plan, manifest)
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
        audio=audio_duration,
    )
    return manifest
