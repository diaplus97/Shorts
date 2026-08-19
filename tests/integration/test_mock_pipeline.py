"""Mock pipeline integration (spec Phase 3).

No paid API is reachable here; the mock providers exercise the real code paths,
including the async submit/poll/download lifecycle, retry and fallback.
"""

from __future__ import annotations

import dataclasses

import pytest

from shorts_factory.domain import AssetStatus, AssetType, PipelineState, Stage, StageStatus
from shorts_factory.errors import FactCheckError, PipelineValidationError
from shorts_factory.media import probe
from shorts_factory.pipeline import (
    load_assets,
    load_research,
    load_scenes,
    load_script,
    plan_pipeline,
    run_pipeline,
    run_stage,
    save_script,
    total_estimated_cost,
)
from shorts_factory.providers.video.mock import MockVideoProvider

requires_media = pytest.mark.media


async def run_through_direct(context) -> None:
    for stage in (Stage.RESEARCH, Stage.WRITE, Stage.FACT_LOCK, Stage.SPEAK, Stage.DIRECT):
        await run_stage(context, stage)


async def test_research_to_scenes_with_mocks(context) -> None:
    await run_through_direct(context)
    workspace = context.workspace

    research = load_research(workspace)
    assert research is not None
    assert research.claims
    assert all(claim.source_ids for claim in research.claims)
    assert research.dangling_source_ids() == []
    assert workspace.research_md.exists()

    script = load_script(workspace)
    assert script is not None
    # The hook is a rewritten spoken question, not the raw topic echoed back.
    assert script.narration.startswith(script.hook)
    assert script.hook.rstrip().endswith("?")
    assert script.resolved_question
    assert set(script.all_claim_ids()) <= {claim.id for claim in research.claims}
    assert workspace.script_txt.exists()

    plan = load_scenes(workspace)
    assert plan is not None
    settings = context.settings.scenes
    assert settings.min_scenes <= len(plan.scenes) <= settings.max_scenes
    assert all(scene.reality_type for scene in plan.scenes)
    assert workspace.scene_prompt_file(plan.scenes[0].id).exists()

    # Every scene prompt must be provider-ready, not a scene dump.
    prompt_text = workspace.scene_prompt_file(plan.scenes[0].id).read_text()
    assert "## prompt" in prompt_text
    assert "## negative" in prompt_text


async def test_scene_narration_reproduces_the_script(context) -> None:
    await run_through_direct(context)
    script = load_script(context.workspace)
    plan = load_scenes(context.workspace)
    joined = " ".join(scene.narration for scene in plan.scenes)
    assert joined == script.narration


async def test_every_scene_holds_whole_speech_units(context) -> None:
    """A scene owns complete units, so a cut can never land mid-sentence."""
    from shorts_factory.pipeline import load_speech_plan
    from shorts_factory.quality import check_scene_speech_alignment

    await run_through_direct(context)
    speech = load_speech_plan(context.workspace)
    plan = load_scenes(context.workspace)

    assert speech is not None and speech.units
    assert check_scene_speech_alignment(plan, speech) == []
    for scene in plan.scenes:
        assert scene.speech_unit_ids
        units = speech.units_for(scene.speech_unit_ids)
        assert scene.narration == " ".join(unit.text for unit in units)


async def test_speech_units_are_short_and_paused(context) -> None:
    from shorts_factory.pipeline import load_speech_plan
    from shorts_factory.utils import visible_length

    await run_through_direct(context)
    speech = load_speech_plan(context.workspace)
    contract = context.config.voice.speech

    assert all(
        visible_length(unit.text) <= contract.hard_split_review_chars for unit in speech.units
    )
    assert any(unit.pause_after_ms > 0 for unit in speech.units)
    assert speech.units[-1].pause_after_ms == 0


async def test_fact_lock_blocks_an_unsourced_script(context) -> None:
    await run_stage(context, Stage.RESEARCH)
    await run_stage(context, Stage.WRITE)

    script = load_script(context.workspace)
    tampered = script.model_copy(update={"referenced_claim_ids": ["C99"]})
    save_script(context.workspace, tampered)

    context.project.stage(Stage.FACT_LOCK).status = StageStatus.PENDING
    with pytest.raises(FactCheckError, match="fact lock failed"):
        await run_stage(context, Stage.FACT_LOCK)
    assert context.project.stage(Stage.FACT_LOCK).status is StageStatus.FAILED
    # The earlier stages keep their results.
    assert context.project.is_stage_completed(Stage.WRITE)


async def test_direct_requires_prior_stages(context) -> None:
    with pytest.raises(PipelineValidationError, match="run `shorts research` first"):
        await run_stage(context, Stage.DIRECT)


@requires_media
async def test_video_submit_poll_download(context) -> None:
    await run_through_direct(context)
    await run_stage(context, Stage.GENERATE)

    ledger = load_assets(context.workspace)
    plan = load_scenes(context.workspace)
    assert ledger.usable_scene_ids() == {scene.id for scene in plan.scenes}

    video_records = [r for r in ledger.records.values() if r.asset_type is AssetType.VIDEO]
    assert video_records
    for record in video_records:
        assert record.provider_job_id
        assert record.status is AssetStatus.COMPLETED
        assert (context.workspace.root / record.local_path).exists()


@requires_media
async def test_repeated_video_failure_falls_back_to_a_still(context) -> None:
    await run_through_direct(context)
    # Every generated prompt contains "camera:", so every video call fails.
    context.providers = dataclasses.replace(
        context.providers,
        video=MockVideoProvider(fail_prompt_substrings=("camera:",)),
    )

    await run_stage(context, Stage.GENERATE)

    ledger = load_assets(context.workspace)
    plan = load_scenes(context.workspace)
    assert ledger.usable_scene_ids() == {scene.id for scene in plan.scenes}

    video_scenes = [scene for scene in plan.scenes if scene.asset_type is AssetType.VIDEO]
    assert video_scenes
    for scene in video_scenes:
        record = ledger.get(scene.id)
        assert record.fallback_used
        assert record.asset_type is AssetType.IMAGE_MOTION
        assert record.local_path.endswith(".png")

    attempts = context.tracker.scene_attempts("video", video_scenes[0].id)
    assert attempts == context.config.budgets.video.max_scene_attempts


@requires_media
async def test_a_refused_prompt_falls_back_without_burning_retries(context) -> None:
    """A content-policy refusal is final. Retrying it costs money and fails again."""
    from shorts_factory.errors import ContentBlockedError
    from shorts_factory.providers.base import VideoJobState

    class RefusingVideoProvider:
        name = "refusing"
        is_mock = True
        model = "refusing-1"

        def snap_duration(self, seconds: float) -> float:
            return seconds

        async def submit(self, **kwargs) -> str:
            return "job-1"

        async def status(self, job_id: str) -> VideoJobState:
            return VideoJobState(
                job_id=job_id, state="failed", error="unsafe content", blocked=True
            )

        async def download(self, job_id: str, destination) -> None:
            raise ContentBlockedError("refused", provider=self.name)

    await run_through_direct(context)
    context.providers = dataclasses.replace(context.providers, video=RefusingVideoProvider())

    await run_stage(context, Stage.GENERATE)

    ledger = load_assets(context.workspace)
    plan = load_scenes(context.workspace)
    assert ledger.usable_scene_ids() == {scene.id for scene in plan.scenes}

    video_scene = next(s for s in plan.scenes if s.asset_type is AssetType.VIDEO)
    assert ledger.get(video_scene.id).fallback_used
    # One attempt, not the three a transient failure would have earned.
    assert context.tracker.scene_attempts("video", video_scene.id) == 1


@requires_media
async def test_assets_are_not_regenerated_on_a_second_run(context) -> None:
    await run_through_direct(context)
    await run_stage(context, Stage.GENERATE)
    calls_after_first = context.tracker.call_count("video") + context.tracker.call_count("image")

    context.project.stage(Stage.GENERATE).status = StageStatus.PENDING
    await run_stage(context, Stage.GENERATE)
    calls_after_second = context.tracker.call_count("video") + context.tracker.call_count("image")

    assert calls_after_second == calls_after_first


async def test_dry_run_plan_costs_nothing_and_calls_nothing(context) -> None:
    plans = plan_pipeline(context)
    assert [plan.stage for plan in plans][:3] == ["research", "write", "fact_lock"]
    assert total_estimated_cost(plans) == 0.0  # mock pricing is zero
    assert context.tracker.total_usd() == 0.0
    assert not context.workspace.research_json.exists()


async def test_plan_reflects_completed_stages(context) -> None:
    await run_stage(context, Stage.RESEARCH)
    plans = {plan.stage: plan for plan in plan_pipeline(context)}
    assert plans["research"].skipped
    assert not plans["write"].skipped


@requires_media
async def test_resume_skips_completed_stages(context) -> None:
    await run_pipeline(context, until=Stage.DIRECT)
    executed_first = set()

    result = await run_pipeline(context, until=Stage.DIRECT)
    assert result.executed == []
    assert set(result.skipped) == {"research", "write", "fact_lock", "speak", "direct"}
    assert executed_first == set()


@requires_media
async def test_full_pipeline_produces_a_valid_short(context) -> None:
    result = await run_pipeline(context)
    assert result.state is PipelineState.DONE

    # Mock providers may never produce final.mp4 (spec v0.2 section 5.3).
    preview = context.workspace.mock_preview
    assert preview.exists()
    assert not context.workspace.final_video.exists()
    assert result.final_video_path is None
    assert result.preview_video_path

    info = probe(preview)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_video and info.has_audio
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert 45.0 <= info.duration_sec <= 70.0

    assert context.workspace.narration_srt.exists()
    assert context.workspace.speech_json.exists()
    assert context.workspace.speech_timeline_json.exists()
    assert (context.workspace.logs_dir / "production_readiness.json").exists()
    assert context.workspace.narration_ass.exists()
    assert context.workspace.manifest_json.exists()
    assert (context.workspace.logs_dir / "validation.json").exists()
    assert (context.workspace.logs_dir / "technical_qa.json").exists()
