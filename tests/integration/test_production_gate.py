"""The gate between "the pipeline ran" and "this is publishable".

Regression cover for the two defects that motivated v0.2: a mock run whose
output was called final.mp4, and a silent voice track reported as success.
"""

from __future__ import annotations

import dataclasses

import pytest

from shorts_factory.domain import Stage
from shorts_factory.errors import MediaError, PipelineValidationError
from shorts_factory.media.ffmpeg import run_async
from shorts_factory.pipeline import load_assets, load_scenes, run_pipeline, run_stage
from shorts_factory.quality import assess, mock_provider_kinds

pytestmark = pytest.mark.media


async def test_a_mock_run_cannot_produce_final_mp4(context) -> None:
    await run_pipeline(context)

    assert context.workspace.mock_preview.exists()
    assert not context.workspace.final_video.exists()
    assert context.project.final_video_path is None
    assert context.project.preview_video_path.endswith("mock_preview.mp4")


async def test_readiness_names_every_mock_provider(context) -> None:
    await run_pipeline(context, until=Stage.GENERATE)
    readiness = assess(
        config=context.config,
        providers=context.providers,
        plan=load_scenes(context.workspace),
        ledger=load_assets(context.workspace),
    )
    assert not readiness.ready
    assert readiness.contains_mock_assets
    assert readiness.mock_providers == mock_provider_kinds(context.providers)
    assert any("mock providers" in reason for reason in readiness.blocking_reasons)


async def test_silent_narration_fails_validation(context) -> None:
    """The original bug: 55 seconds of nothing used to pass as a finished video."""
    await run_pipeline(context, until=Stage.NARRATE)

    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono:d=20",
            str(context.workspace.narration_wav),
        ],
        label="silence_injection",
    )

    context.force = True
    with pytest.raises(PipelineValidationError, match="silent"):
        await run_stage(context, Stage.VALIDATE)


async def test_a_silent_render_publishes_nothing(context) -> None:
    """Even if validation is bypassed, nothing reaches the output directory."""
    await run_pipeline(context, until=Stage.VALIDATE)

    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono:d=20",
            str(context.workspace.narration_wav),
        ],
        label="silence_injection",
    )
    context.force = True
    with pytest.raises(MediaError, match="silent"):
        await run_stage(context, Stage.COMPOSE)

    assert not context.workspace.final_video.exists()
    assert not context.workspace.mock_preview.exists()


async def test_switching_to_a_real_provider_flips_readiness(context) -> None:
    """`production_ready` is derived from the providers, not from a stored flag."""
    assert not context.production_ready

    class RealEnough:
        name = "openai"
        is_mock = False
        model = "x"

    context.providers = dataclasses.replace(context.providers, tts=RealEnough())
    assert "tts" not in mock_provider_kinds(context.providers)
    assert not context.production_ready  # the others are still mocks
