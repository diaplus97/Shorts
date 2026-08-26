"""Composition stage: normalised clips + voice + subtitles -> a video file.

    normalize scenes -> concat -> voiceover -> bgm ducking -> subtitle -> encode
    -> production readiness gate -> publish

Two things changed in v0.2 and both matter more than the encode itself:

* The encode goes to a staging path. Nothing is published until the result has
  passed the readiness gate, so ``final.mp4`` cannot exist in a bad state.
* A run containing any mock provider publishes ``mock_preview.mp4`` with a
  burned-in MOCK PIPELINE label instead. It is never called final.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..config import HighlightStyle
from ..domain import AssetLedger, AssetType, Manifest, PipelineState, Scene, ScenePlan
from ..errors import MediaError, PipelineValidationError
from ..media import (
    HighlightBox,
    SfxPlacement,
    compose,
    normalize_image,
    normalize_video,
    probe,
)
from ..pipeline.checkpoint import load_assets, require_manifest, require_scenes, save_project
from ..pipeline.context import RunContext
from ..quality import QAReport, assess, check_clip, check_final_video
from ..utils import atomic_write_json, atomic_write_model, read_json, relative_to, sha256_text
from ._plan import StagePlan

STAGE_NAME = "compose"

MOCK_WATERMARK = "MOCK PIPELINE"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def resolve_source(context: RunContext, relative_path: str) -> Path:
    candidate = context.workspace.root / relative_path
    return candidate if candidate.exists() else Path(relative_path)


def clip_recipe(
    source: Path, duration: float, box: HighlightBox | None, style: HighlightStyle
) -> str:
    """Everything that decides what a normalised clip looks like.

    Duration alone used to be the whole test, which meant a clip survived any
    change that did not move its length -- a regenerated source asset, or now a
    highlight box appearing on it. Both produce a clip that looks nothing like
    the one on disk and measures the same.
    """
    parts = [
        str(source),
        f"{duration:.3f}",
        box.model_dump_json() if box is not None else "none",
        style.model_dump_json() if box is not None else "none",
    ]
    return sha256_text("|".join(parts))


def clip_is_current(
    clip: Path, duration: float, recipe: str | None = None, meta: Path | None = None
) -> bool:
    if not clip.exists():
        return False
    if recipe is not None and meta is not None:
        try:
            recorded = read_json(meta).get("recipe")
        except (OSError, ValueError):
            # No recipe recorded means the clip predates this check. Re-encoding
            # once is cheaper than shipping a stale frame nobody looked at.
            return False
        if recorded != recipe:
            return False
    try:
        info = probe(clip)
    except MediaError:
        return False
    return abs(info.duration_sec - duration) <= 0.05


def highlight_for(context: RunContext, scene: Scene, duration: float) -> HighlightBox | None:
    """The box to draw on one scene, clamped to the duration it actually gets.

    A scene's planned duration and its manifest duration are not the same
    number: the manifest one is measured from the voice, and the last scene
    additionally absorbs the tail padding. A box timed against the plan would
    drift, and on a shortened scene it could be scheduled entirely past the end
    of the clip, where ffmpeg draws nothing and says nothing about it.
    """
    if scene.highlight is None or not context.settings.highlight.enabled:
        return None

    box = scene.highlight
    start = min(box.start_sec, max(duration - 0.2, 0.0))
    remaining = duration - start
    if remaining <= 0:
        context.log.warning("highlight_dropped", scene=scene.id, reason="no room in the shot")
        return None
    span = remaining if box.duration_sec is None else min(box.duration_sec, remaining)
    return HighlightBox(
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
        start_sec=round(start, 3),
        duration_sec=round(span, 3),
    )


async def normalize_scene_clips(
    context: RunContext, manifest: Manifest, ledger: AssetLedger, plan: ScenePlan | None = None
) -> list[Path]:
    """Bring every scene to identical codec parameters and its final duration."""
    clips: list[Path] = []
    for index, entry in enumerate(manifest.scenes):
        record = ledger.get(entry.scene_id)
        if record is None or not record.local_path:
            raise PipelineValidationError(f"scene {entry.scene_id} has no asset to compose")

        clip = context.workspace.scene_clip(entry.scene_id)
        source = resolve_source(context, record.local_path)
        scene = plan.scene_by_id(entry.scene_id) if plan else None
        box = highlight_for(context, scene, entry.duration) if scene else None
        recipe = clip_recipe(source, entry.duration, box, context.settings.highlight)

        meta = context.workspace.clip_meta(entry.scene_id)
        if not context.force and clip_is_current(clip, entry.duration, recipe, meta):
            context.log.debug("clip_reused", scene=entry.scene_id)
            clips.append(clip)
            continue

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
                highlight=box,
                highlight_style=context.settings.highlight,
            )
        else:
            await normalize_video(
                source,
                clip,
                duration_sec=entry.duration,
                output=context.settings.output,
                highlight=box,
                highlight_style=context.settings.highlight,
            )
        atomic_write_json(meta, {"recipe": recipe})
        context.log.info(
            "clip_normalized",
            scene=entry.scene_id,
            duration=entry.duration,
            highlight=bool(box),
        )
        clips.append(clip)
    return clips


def publish(context: RunContext, staged: Path, destination: Path) -> Path:
    """Move the staged render into place and clear the counterpart output.

    A stale ``final.mp4`` sitting next to a fresh ``mock_preview.mp4`` is exactly
    the confusion this stage exists to prevent, so only one of them survives.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(destination))
    counterpart = (
        context.workspace.mock_preview
        if destination == context.workspace.final_video
        else context.workspace.final_video
    )
    if counterpart.exists():
        counterpart.unlink()
        context.log.info("stale_output_removed", path=str(counterpart))
    return destination


def resolve_sfx(context: RunContext, plan: ScenePlan, manifest: Manifest) -> list[SfxPlacement]:
    """Turn each scene's cue into a placed sound, skipping what is not installed.

    No audio ships with this repository, so a cue with no file behind it is a
    warning rather than a failed render.
    """
    config = context.config.sfx
    if not config.enabled:
        return []

    starts = {entry.scene_id: entry.start for entry in manifest.scenes}
    placements: list[SfxPlacement] = []
    missing: set[str] = set()

    for scene in plan.scenes:
        entry = config.entry_for(scene.sfx_cue)
        if entry is None:
            if scene.sfx_cue and scene.sfx_cue != "none":
                missing.add(scene.sfx_cue)
            continue
        path = Path(entry.file)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            missing.add(f"{scene.sfx_cue} ({entry.file})")
            continue
        placements.append(
            SfxPlacement(
                path=str(path),
                start_sec=starts.get(scene.id, 0.0),
                gain_db=config.gain_for(entry),
                cue=scene.sfx_cue,
            )
        )

    if missing:
        context.log.warning("sfx_cue_unavailable", cues=sorted(missing))
    if placements:
        context.log.info("sfx_placed", count=len(placements))
    return placements


def plan(context: RunContext) -> StagePlan:
    notes = ["local ffmpeg work only, no paid calls"]
    if not context.production_ready:
        notes.append("mock providers in use: this run can only produce mock_preview.mp4")
    return StagePlan(stage=STAGE_NAME, notes=notes)


async def run(context: RunContext) -> Path:
    manifest = require_manifest(context.workspace)
    scene_plan: ScenePlan = require_scenes(context.workspace)
    ledger = load_assets(context.workspace)
    production = context.production_ready

    clips = await normalize_scene_clips(context, manifest, ledger, scene_plan)

    report = QAReport()
    for clip, entry in zip(clips, manifest.scenes, strict=True):
        report.extend(check_clip(clip, entry.duration, context.settings.output, entry.scene_id))
    if not report.ok:
        raise MediaError(
            "normalised clips failed technical QA:\n"
            + "\n".join(issue.render() for issue in report.errors)
        )

    voice = context.workspace.root / manifest.voice if manifest.voice else None
    subtitle_ref = manifest.subtitle_burn or manifest.subtitle
    subtitle = context.workspace.root / subtitle_ref if subtitle_ref else None

    sfx = resolve_sfx(context, scene_plan, manifest)
    staged = context.workspace.work_dir / "render.mp4"
    await compose(
        clips=clips,
        destination=staged,
        total_duration_sec=manifest.total_duration_sec,
        work_dir=context.workspace.work_dir,
        output=context.settings.output,
        audio=context.settings.audio,
        subtitles=context.settings.subtitles,
        voice_path=voice if voice and voice.exists() else None,
        bgm_path=context.bgm_path,
        subtitle_path=subtitle if subtitle and subtitle.exists() else None,
        watermark=None if production else MOCK_WATERMARK,
        sfx=sfx,
    )

    readiness = assess(
        config=context.config,
        providers=context.providers,
        plan=scene_plan,
        ledger=ledger,
        video_path=staged,
        voice_path=voice,
    )
    atomic_write_model(context.workspace.logs_dir / "production_readiness.json", readiness)

    final_report = QAReport(
        issues=check_final_video(staged, manifest.total_duration_sec, context.settings.output)
    )
    report.extend(final_report.issues)
    atomic_write_model(context.workspace.logs_dir / "technical_qa.json", report)

    # Nothing is published until the picture and the sound are both real.
    blocking = list(final_report.errors)
    if not readiness.video_valid or not readiness.audio_valid:
        staged.unlink(missing_ok=True)
        raise MediaError(
            "render rejected before publishing:\n" + "\n".join(readiness.blocking_reasons)
        )
    if blocking:
        staged.unlink(missing_ok=True)
        raise MediaError(
            "final video failed technical QA:\n" + "\n".join(issue.render() for issue in blocking)
        )
    if production and not readiness.ready:
        staged.unlink(missing_ok=True)
        raise MediaError(
            "a production render may not be published:\n" + "\n".join(readiness.blocking_reasons)
        )

    destination = context.workspace.output_video(production_ready=production)
    output_path = publish(context, staged, destination)

    if production:
        context.project.final_video_path = relative_to(output_path, context.workspace.root)
        context.project.preview_video_path = None
    else:
        context.project.preview_video_path = relative_to(output_path, context.workspace.root)
        context.project.final_video_path = None
    context.project.cost_breakdown = context.tracker.summary()
    context.project.actual_cost_usd = context.tracker.total_usd()
    context.project.state = PipelineState.COMPOSED
    save_project(context.workspace, context.project)

    context.log.info(
        "composition_completed",
        path=str(output_path),
        production=production,
        duration=manifest.total_duration_sec,
        cost_usd=context.project.actual_cost_usd,
    )
    for warning in readiness.warnings:
        context.log.warning("production_warning", detail=warning)
    return output_path
