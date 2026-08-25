"""Asset generation: scenes -> video or image files.

Three behaviours matter more than the happy path (spec sections 23-27):

* idempotency  -- a scene whose prompt hash already produced a usable asset is
  never re-billed;
* retry limits -- a scene gets at most ``video.max_scene_attempts`` paid video
  calls, ever, across resumes;
* fallback     -- when video generation is exhausted the scene becomes a still
  image with camera motion instead of a hole in the edit.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..cost import CostEvent
from ..domain import AssetLedger, AssetRecord, AssetStatus, AssetType, Scene, ScenePlan
from ..errors import (
    BudgetExceededError,
    ContentBlockedError,
    PipelineValidationError,
    ProviderError,
)
from ..pipeline.checkpoint import load_assets, require_scenes, save_assets, save_project
from ..pipeline.context import RunContext
from ..providers import with_retry
from ..utils import asset_prompt_hash, relative_to
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "generate"


def requested_video_seconds(context: RunContext, scene: Scene) -> float:
    """Clip length to ask the provider for.

    Capped at the configured maximum, then snapped to a length the provider
    actually returns. Doing it here rather than inside the provider keeps the
    prompt hash and the cost estimate agreeing with the request.
    """
    capped = min(scene.duration_sec, context.settings.video.max_clip_duration_sec)
    return round(context.providers.video.snap_duration(capped), 3)


def video_hash(context: RunContext, scene: Scene, prompt: str, negative: str) -> str:
    provider = context.providers.video
    return asset_prompt_hash(
        provider=provider.name,
        model=provider.model,
        prompt=prompt,
        duration_sec=requested_video_seconds(context, scene),
        aspect_ratio=context.settings.video.aspect_ratio,
        negative_constraints=[negative],
    )


def image_hash(context: RunContext, scene: Scene, prompt: str, negative: str) -> str:
    provider = context.providers.image
    image = context.settings.image
    return asset_prompt_hash(
        provider=provider.name,
        model=provider.model,
        prompt=prompt,
        duration_sec=0.0,
        aspect_ratio=f"{image.width}:{image.height}",
        negative_constraints=[negative],
    )


def wants_video(scene: Scene) -> bool:
    return scene.asset_type is AssetType.VIDEO


def can_reuse(context: RunContext, record: AssetRecord | None, hashes: set[str]) -> bool:
    if record is None or not record.is_usable or record.prompt_hash not in hashes:
        return False
    local_path = record.local_path
    if not local_path:
        return False
    return (context.workspace.root / local_path).exists() or Path(local_path).exists()


async def poll_until_done(context: RunContext, job_id: str) -> None:
    """Poll a submitted job until it finishes, fails, or the timeout expires."""
    video = context.providers.video
    settings = context.settings.video
    waited = 0.0
    while True:
        state = await with_retry(
            f"video_status:{job_id}",
            lambda: video.status(job_id),
            context.settings.retry,
        )
        if state.state == "completed":
            return
        if state.state == "failed":
            reason = state.error or "no reason given"
            if state.blocked:
                raise ContentBlockedError(
                    f"video job {job_id} was refused: {reason}",
                    provider=video.name,
                    reason=reason,
                )
            # The job was accepted and generation started, so a failure here can
            # be transient -- that is what the scene attempt budget is for. A
            # request the API rejects outright is a different case and is marked
            # non-retryable by the provider.
            raise ProviderError(
                f"video job {job_id} failed: {reason}",
                provider=video.name,
                retryable=True,
            )
        if waited >= settings.poll_timeout_sec:
            raise ProviderError(
                f"video job {job_id} still {state.state} after {waited:.0f}s",
                provider=video.name,
                retryable=True,
            )
        await asyncio.sleep(settings.poll_interval_sec)
        waited += settings.poll_interval_sec


async def generate_video_asset(
    context: RunContext, scene: Scene, prompt: str, negative: str
) -> AssetRecord:
    """One paid video attempt. Raises on failure; the caller decides what next."""
    video = context.providers.video
    seconds = requested_video_seconds(context, scene)
    estimated = context.guard.estimate_video_usd(video.name, seconds, video.model)

    context.guard.check_video_attempt(scene.id)
    context.guard.check_total(estimated, operation=f"video:{scene.id}")

    destination = context.workspace.scene_dir(scene.id) / "source.mp4"
    job_id = await with_retry(
        f"video_submit:{scene.id}",
        lambda: video.submit(
            prompt=prompt,
            duration_sec=seconds,
            aspect_ratio=context.settings.video.aspect_ratio,
            negative_prompt=negative or None,
        ),
        context.settings.retry,
    )
    context.log.info("render_submitted", scene=scene.id, job=job_id, seconds=seconds)

    # Bill the attempt as soon as it is submitted: a provider charges for a
    # started job whether or not we end up using the result.
    context.tracker.record(
        CostEvent(
            kind="video",
            provider=video.name,
            operation="generate_video",
            scene_id=scene.id,
            estimated_cost_usd=estimated,
            actual_cost_usd=estimated,
            metadata={"job_id": job_id, "seconds": seconds, "model": video.model},
        )
    )

    await poll_until_done(context, job_id)
    result = await with_retry(
        f"video_download:{scene.id}",
        lambda: video.download(job_id, destination),
        context.settings.retry,
    )

    return AssetRecord(
        scene_id=scene.id,
        provider=video.name,
        asset_type=AssetType.VIDEO,
        provider_job_id=job_id,
        status=AssetStatus.COMPLETED,
        prompt=prompt,
        prompt_hash=video_hash(context, scene, prompt, negative),
        local_path=relative_to(result.path, context.workspace.root),
        duration_sec=result.duration_sec or seconds,
        cost_usd=estimated,
    )


async def generate_image_asset(
    context: RunContext, scene: Scene, prompt: str, negative: str, *, fallback: bool
) -> AssetRecord:
    image = context.providers.image
    settings = context.settings.image
    estimated = context.guard.estimate_image_usd(image.name, 1)

    context.guard.check_image_attempt(scene.id)
    context.guard.check_total(estimated, operation=f"image:{scene.id}")

    destination = context.workspace.scene_dir(scene.id) / "source.png"
    result = await with_retry(
        f"image:{scene.id}",
        lambda: image.generate(
            prompt=prompt,
            width=settings.width,
            height=settings.height,
            destination=destination,
            negative_prompt=negative or None,
        ),
        context.settings.retry,
    )
    context.tracker.record(
        CostEvent(
            kind="image",
            provider=image.name,
            operation="generate_image",
            scene_id=scene.id,
            estimated_cost_usd=estimated,
            actual_cost_usd=estimated,
            metadata={"model": image.model, "fallback": fallback},
        )
    )
    return AssetRecord(
        scene_id=scene.id,
        provider=image.name,
        asset_type=AssetType.IMAGE_MOTION if fallback else scene.asset_type,
        status=AssetStatus.COMPLETED,
        prompt=prompt,
        prompt_hash=image_hash(context, scene, prompt, negative),
        local_path=relative_to(result.path, context.workspace.root),
        cost_usd=estimated,
        fallback_used=fallback,
    )


async def generate_scene(
    context: RunContext, scene: Scene, ledger: AssetLedger, plan: ScenePlan
) -> AssetRecord:
    adapter = context.providers.prompt_adapter
    prompt = adapter.build_prompt(scene, plan)
    # A still is ordered from its own prompt, so its hash has to be computed
    # from that one. Hashing the video prompt instead made every still miss the
    # reuse check and be re-billed on every resume.
    still_prompt = adapter.build_still_prompt(scene, plan)
    negative = adapter.build_negative_prompt(scene)

    hashes = {
        video_hash(context, scene, prompt, negative),
        image_hash(context, scene, still_prompt, negative),
    }
    existing = ledger.get(scene.id)
    if existing is not None and not context.force and can_reuse(context, existing, hashes):
        context.log.info("asset_reused", scene=scene.id, path=existing.local_path)
        return existing

    max_attempts = context.config.budgets.video.max_scene_attempts
    last_error: str | None = None

    if wants_video(scene):
        for attempt in range(1, max_attempts + 1):
            try:
                record = await generate_video_asset(context, scene, prompt, negative)
            except BudgetExceededError as exc:
                # Scene-level exhaustion falls back; a project-level overrun does not.
                if "attempt budget" not in str(exc):
                    raise
                last_error = str(exc)
                context.log.warning("video_attempts_exhausted", scene=scene.id, error=last_error)
                break
            except ContentBlockedError as exc:
                # Retrying a refused prompt costs money and fails again.
                last_error = str(exc)
                context.log.warning("render_blocked", scene=scene.id, error=last_error)
                break
            except ProviderError as exc:
                last_error = str(exc)
                context.log.warning(
                    "render_failed", scene=scene.id, attempt=attempt, error=last_error
                )
                ledger.put(
                    AssetRecord(
                        scene_id=scene.id,
                        provider=context.providers.video.name,
                        asset_type=AssetType.VIDEO,
                        status=AssetStatus.FAILED,
                        attempt=attempt,
                        prompt=prompt,
                        prompt_hash=video_hash(context, scene, prompt, negative),
                        error=last_error,
                    )
                )
                save_assets(context.workspace, ledger)
                if not exc.retryable:
                    # A malformed or rejected request fails identically every
                    # time; three attempts only delay the fallback.
                    break
                continue
            else:
                record.attempt = attempt
                context.log.info("render_completed", scene=scene.id, attempt=attempt)
                return record

    # Either the scene was planned as a still, or video generation is exhausted.
    fallback = wants_video(scene)
    if fallback:
        context.log.warning("scene_fallback_to_image", scene=scene.id, reason=last_error)
    # A frame has no camera move and no "change during the shot". Passing the
    # video prompt verbatim asked a still for both, which is part of why a
    # fallback never matched the clips on either side of it.
    record = await generate_image_asset(context, scene, still_prompt, negative, fallback=fallback)
    record.error = last_error
    return record


def plan(context: RunContext) -> StagePlan:
    try:
        scene_plan = require_scenes(context.workspace)
    except PipelineValidationError:
        return StagePlan(
            stage=STAGE_NAME,
            notes=["no scenes.json yet; run the director stage to see a per-scene plan"],
        )

    ledger = load_assets(context.workspace)
    adapter = context.providers.prompt_adapter
    calls: list[PlannedCall] = []
    notes: list[str] = []

    for scene in scene_plan.scenes:
        prompt = adapter.build_prompt(scene, scene_plan)
        negative = adapter.build_negative_prompt(scene)
        hashes = {
            video_hash(context, scene, prompt, negative),
            image_hash(context, scene, prompt, negative),
        }
        if not context.force and can_reuse(context, ledger.get(scene.id), hashes):
            notes.append(f"{scene.id}: reuse existing asset")
            continue
        if wants_video(scene):
            seconds = requested_video_seconds(context, scene)
            calls.append(
                PlannedCall(
                    kind="video",
                    provider=context.providers.video.name,
                    operation="generate_video",
                    estimated_cost_usd=context.guard.estimate_video_usd(
                        context.providers.video.name, seconds, context.providers.video.model
                    ),
                    detail=f"{scene.id} ({scene.priority}, {seconds:.1f}s): {prompt[:110]}",
                )
            )
        else:
            calls.append(
                PlannedCall(
                    kind="image",
                    provider=context.providers.image.name,
                    operation="generate_image",
                    estimated_cost_usd=context.guard.estimate_image_usd(
                        context.providers.image.name, 1
                    ),
                    detail=f"{scene.id} ({scene.priority}, still): {prompt[:110]}",
                )
            )
    notes.append(
        f"worst case adds up to {context.config.budgets.video.max_scene_attempts}x per video scene"
    )
    return StagePlan(stage=STAGE_NAME, calls=calls, notes=notes)


async def run(context: RunContext) -> AssetLedger:
    scene_plan: ScenePlan = require_scenes(context.workspace)
    ledger = load_assets(context.workspace)

    for scene in scene_plan.scenes:
        record = await generate_scene(context, scene, ledger, scene_plan)
        ledger.put(record)
        # Checkpoint after every scene so a crash never loses a paid asset.
        save_assets(context.workspace, ledger)

    context.project.assets_path = relative_to(context.workspace.assets_json, context.workspace.root)
    save_project(context.workspace, context.project)

    usable = len(ledger.usable_scene_ids())
    context.log.info(
        "asset_generation_completed",
        scenes=len(scene_plan.scenes),
        usable=usable,
        cost_usd=ledger.total_cost_usd(),
    )
    if usable < len(scene_plan.scenes):
        missing = [s.id for s in scene_plan.scenes if s.id not in ledger.usable_scene_ids()]
        raise PipelineValidationError(f"scenes without a usable asset: {missing}")
    return ledger
