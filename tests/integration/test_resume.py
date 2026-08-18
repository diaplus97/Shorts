"""Resume after an abrupt termination (spec sections 25, 63).

The point of these tests is that nothing already paid for is paid for twice.
"""

from __future__ import annotations

import pytest

from shorts_factory.domain import PipelineState, Stage, StageStatus
from shorts_factory.errors import PipelineValidationError
from shorts_factory.media import is_available
from shorts_factory.pipeline import (
    build_context,
    load_existing,
    run_pipeline,
    run_stage,
)
from shorts_factory.providers import build_providers

requires_media = pytest.mark.skipif(not is_available(), reason="ffmpeg/ffprobe not installed")


def reopen(config, slug):
    """Reload a project from disk exactly as a fresh process would."""
    project, workspace = load_existing(slug, config)
    return build_context(
        config=config,
        project=project,
        workspace=workspace,
        providers=build_providers(config),
    )


@requires_media
async def test_a_killed_run_resumes_without_repeating_paid_work(config, context) -> None:
    slug = context.project.slug
    await run_pipeline(context, until=Stage.GENERATE)
    first_video_calls = context.tracker.call_count("video")
    first_llm_calls = context.tracker.call_count("llm")
    assert first_video_calls > 0
    assert first_llm_calls == 3  # research, writer, director

    # Simulate `kill -9`: throw away every in-memory object and start over.
    del context
    resumed = reopen(config, slug)
    assert resumed.project.is_stage_completed(Stage.GENERATE)
    assert resumed.tracker.call_count("video") == first_video_calls

    result = await run_pipeline(resumed)
    assert result.state is PipelineState.DONE
    assert set(result.skipped) >= {"research", "write", "direct", "generate"}
    assert resumed.tracker.call_count("video") == first_video_calls
    assert resumed.tracker.call_count("llm") == first_llm_calls
    assert resumed.workspace.final_video.exists()


@requires_media
async def test_a_failed_stage_keeps_earlier_artifacts(config, context) -> None:
    slug = context.project.slug
    await run_pipeline(context, until=Stage.DIRECT)

    # Corrupt the scene plan so the next stage cannot run.
    context.workspace.scenes_json.write_text("{ not json", encoding="utf-8")
    resumed = reopen(config, slug)
    with pytest.raises(PipelineValidationError, match="not a valid ScenePlan"):
        await run_stage(resumed, Stage.GENERATE)

    after_failure = reopen(config, slug)
    assert after_failure.project.is_stage_completed(Stage.DIRECT)
    assert after_failure.project.stage(Stage.GENERATE).status is StageStatus.FAILED
    assert after_failure.workspace.research_json.exists()
    assert after_failure.workspace.script_json.exists()


async def test_rerunning_the_writer_invalidates_the_scene_plan(config, context) -> None:
    slug = context.project.slug
    await run_pipeline(context, until=Stage.DIRECT)
    assert context.project.is_stage_completed(Stage.DIRECT)

    forced = reopen(config, slug)
    forced.force = True
    await run_stage(forced, Stage.WRITE)

    assert forced.project.stage(Stage.DIRECT).status is StageStatus.PENDING
    assert forced.project.stage(Stage.FACT_LOCK).status is StageStatus.PENDING

    reloaded = reopen(config, slug)
    assert reloaded.project.stage(Stage.DIRECT).status is StageStatus.PENDING
