"""Composition stage: normalised clips + voice + subtitles -> final.mp4.

normalize scenes -> concat -> voiceover -> bgm ducking -> subtitle -> encode
"""

from __future__ import annotations

from pathlib import Path

from ..domain import AssetLedger, AssetType, Manifest, PipelineState
from ..errors import MediaError, PipelineValidationError
from ..media import compose, normalize_image, normalize_video, probe
from ..pipeline.checkpoint import load_assets, require_manifest, save_project
from ..pipeline.context import RunContext
from ..quality import QAReport, check_clip, check_final_video
from ..utils import atomic_write_model, relative_to
from ._plan import StagePlan

STAGE_NAME = "compose"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def resolve_source(context: RunContext, relative_path: str) -> Path:
    candidate = context.workspace.root / relative_path
    return candidate if candidate.exists() else Path(relative_path)


def clip_is_current(clip: Path, duration: float) -> bool:
    if not clip.exists():
        return False
    try:
        info = probe(clip)
    except MediaError:
        return False
    return abs(info.duration_sec - duration) <= 0.05


async def normalize_scene_clips(
    context: RunContext, manifest: Manifest, ledger: AssetLedger
) -> list[Path]:
    """Bring every scene to identical codec parameters and its final duration."""
    clips: list[Path] = []
    for index, entry in enumerate(manifest.scenes):
        record = ledger.get(entry.scene_id)
        if record is None or not record.local_path:
            raise PipelineValidationError(f"scene {entry.scene_id} has no asset to compose")

        clip = context.workspace.scene_clip(entry.scene_id)
        if not context.force and clip_is_current(clip, entry.duration):
            context.log.debug("clip_reused", scene=entry.scene_id)
            clips.append(clip)
            continue

        source = resolve_source(context, record.local_path)
        if not source.exists():
            raise PipelineValidationError(f"scene {entry.scene_id}: {source} is missing")

        if source.suffix.lower() in _IMAGE_SUFFIXES:
            await normalize_image(
                source,
                clip,
                duration_sec=entry.duration,
                output=context.settings.output,
                motion_index=index,
                static=record.asset_type is AssetType.IMAGE,
            )
        else:
            await normalize_video(
                source,
                clip,
                duration_sec=entry.duration,
                output=context.settings.output,
            )
        context.log.info("clip_normalized", scene=entry.scene_id, duration=entry.duration)
        clips.append(clip)
    return clips


def plan(context: RunContext) -> StagePlan:
    return StagePlan(
        stage=STAGE_NAME,
        notes=["local ffmpeg work only, no paid calls"],
    )


async def run(context: RunContext) -> Path:
    manifest = require_manifest(context.workspace)
    ledger = load_assets(context.workspace)

    clips = await normalize_scene_clips(context, manifest, ledger)

    report = QAReport()
    for clip, entry in zip(clips, manifest.scenes, strict=True):
        report.extend(check_clip(clip, entry.duration, context.settings.output, entry.scene_id))
    if not report.ok:
        raise MediaError(
            "normalised clips failed technical QA:\n"
            + "\n".join(issue.render() for issue in report.errors)
        )

    voice = context.workspace.root / manifest.voice if manifest.voice else None
    # Burn the styled ASS when it exists; fall back to the plain SRT.
    subtitle_ref = manifest.subtitle_burn or manifest.subtitle
    subtitle = context.workspace.root / subtitle_ref if subtitle_ref else None

    output_path = await compose(
        clips=clips,
        destination=context.workspace.final_video,
        total_duration_sec=manifest.total_duration_sec,
        work_dir=context.workspace.work_dir,
        output=context.settings.output,
        audio=context.settings.audio,
        subtitles=context.settings.subtitles,
        voice_path=voice if voice and voice.exists() else None,
        bgm_path=context.bgm_path,
        subtitle_path=subtitle if subtitle and subtitle.exists() else None,
    )

    final_report = QAReport(
        issues=check_final_video(output_path, manifest.total_duration_sec, context.settings.output)
    )
    report.extend(final_report.issues)
    atomic_write_model(context.workspace.logs_dir / "technical_qa.json", report)
    if not final_report.ok:
        raise MediaError(
            "final video failed technical QA:\n"
            + "\n".join(issue.render() for issue in final_report.errors)
        )

    context.project.final_video_path = relative_to(output_path, context.workspace.root)
    context.project.cost_breakdown = context.tracker.summary()
    context.project.actual_cost_usd = context.tracker.total_usd()
    context.project.state = PipelineState.COMPOSED
    save_project(context.workspace, context.project)

    context.log.info(
        "composition_completed",
        path=str(output_path),
        duration=manifest.total_duration_sec,
        cost_usd=context.project.actual_cost_usd,
    )
    return output_path
