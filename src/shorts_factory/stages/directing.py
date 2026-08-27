"""Director stage: narration -> scenes (spec sections 15-16).

The most important LLM step. It produces meaning, not prompt strings; the
prompt adapter turns each scene into provider text afterwards.
"""

from __future__ import annotations

from ..domain import ResearchResult, ScenePlan, ScriptResult, SpeechPlan
from ..pipeline.checkpoint import (
    require_research,
    require_script,
    require_speech_plan,
    save_project,
    save_scenes,
)
from ..pipeline.context import RunContext
from ..quality import (
    QAIssue,
    check_scene_contract,
    check_scene_plan,
    check_scene_speech_alignment,
    check_scene_traceability,
)
from ..utils import atomic_write_text, relative_to
from ._llm import structured_call
from ._plan import PlannedCall, StagePlan
from .writing import claims_payload

STAGE_NAME = "direct"


def script_payload(script: ScriptResult) -> dict[str, object]:
    return {
        "title": script.title,
        "hook": script.hook,
        "narration": script.narration,
        "beats": [
            {
                "id": beat.id,
                "purpose": beat.purpose,
                "text": beat.text,
                "claim_ids": beat.claim_ids,
            }
            for beat in script.beats
        ],
        "target_duration_sec": script.target_duration_sec,
    }


def normalize_plan(plan: ScenePlan, speech: SpeechPlan | None = None) -> ScenePlan:
    """Renumber scenes, and rebuild narration from the speech units they cover.

    Deriving narration from units rather than trusting the model's copy is what
    makes a mid-sentence cut impossible: a scene owns whole units or none.
    """
    scenes = []
    for index, scene in enumerate(sorted(plan.scenes, key=lambda s: s.order), start=1):
        update: dict[str, object] = {"id": f"S{index:02d}", "order": index}
        if speech is not None and scene.speech_unit_ids:
            units = speech.units_for(scene.speech_unit_ids)
            if units:
                update["narration"] = " ".join(unit.text for unit in units)
                update["claim_ids"] = _merge_claims(scene.claim_ids, units)
        scenes.append(scene.model_copy(update=update))
    return plan.model_copy(update={"scenes": scenes})


def _merge_claims(existing: list[str], units) -> list[str]:
    merged = list(existing)
    for unit in units:
        merged.extend(cid for cid in unit.referenced_claim_ids if cid not in merged)
    return merged


def write_scene_prompts(context: RunContext, plan: ScenePlan) -> None:
    """Persist the provider-facing prompt for every scene, for human review."""
    adapter = context.providers.prompt_adapter
    for scene in plan.scenes:
        body = "\n".join(
            [
                f"# {scene.id} ({scene.priority} / {scene.reality_type} / {scene.asset_type})",
                f"duration: {scene.duration_sec:.2f}s",
                f"claims: {', '.join(scene.claim_ids) or '—'}",
                f"answers: {scene.question_answered}",
                f"visible change: {scene.visible_change}",
                "",
                "## narration",
                scene.narration,
                "",
                "## caption",
                scene.subtitle_text,
                "",
                "## prompt",
                adapter.build_prompt(scene, plan),
                "",
                "## negative",
                adapter.build_negative_prompt(scene),
                "",
            ]
        )
        atomic_write_text(context.workspace.scene_prompt_file(scene.id), body)


def plan_stage(context: RunContext) -> StagePlan:
    return StagePlan(
        stage=STAGE_NAME,
        calls=[
            PlannedCall(
                kind="llm",
                provider=context.providers.llm.name,
                operation="director",
                estimated_cost_usd=context.guard.estimate_llm_usd(
                    context.providers.llm.name,
                    5000,
                    context.settings.llm.max_output_tokens,
                ),
                detail=(
                    f"{context.settings.scenes.min_scenes}-"
                    f"{context.settings.scenes.max_scenes} scenes"
                ),
            )
        ],
    )


plan = plan_stage


async def run(context: RunContext) -> ScenePlan:
    research: ResearchResult = require_research(context.workspace)
    script = require_script(context.workspace)
    settings = context.settings
    content_type = context.config.content_type(context.project.content_type)

    contract = context.config.content_contract
    speech = require_speech_plan(context.workspace)

    def _validate(result: ScenePlan) -> list[QAIssue]:
        normalized = normalize_plan(result, speech)
        return [
            *check_scene_plan(normalized, script, settings, context.config.budgets),
            *check_scene_traceability(normalized, research),
            *check_scene_contract(normalized, contract),
            *check_scene_speech_alignment(normalized, speech),
        ]

    result, prompt = await structured_call(
        context,
        prompt_name="director",
        variables={
            "topic": context.project.topic,
            "resolved_question": research.question.resolved_question,
            "scope": research.question.scope,
            "content_type": context.project.content_type,
            "default_reality_type": content_type.default_reality_type,
            "min_scenes": settings.scenes.min_scenes,
            "max_scenes": settings.scenes.max_scenes,
            "target_duration_sec": script.target_duration_sec,
            "min_scene_duration_sec": settings.scenes.min_scene_duration_sec,
            "max_scene_duration_sec": settings.scenes.max_scene_duration_sec,
            "max_high_priority_scenes": context.config.budgets.video.max_high_priority_scenes,
            "chars_per_sec": settings.script.chars_per_sec,
            "reveal_pattern_json": content_type.reveal_pattern,
            "preferred_camera_json": content_type.preferred_camera,
            "preferred_visuals_json": content_type.preferred_visuals,
            "transitions_json": context.config.visual_styles.style.transitions,
            "sfx_vocabulary_json": context.config.sfx.vocabulary,
            "max_caption_chars": (
                settings.subtitles.max_chars_per_line * settings.subtitles.max_lines
            ),
            "script_json": script_payload(script),
            "speech_units_json": [
                {
                    "id": unit.id,
                    "text": unit.text,
                    "delivery": unit.delivery.value,
                    "pause_after_ms": unit.pause_after_ms,
                    "beat_id": unit.beat_id,
                    "claim_ids": unit.referenced_claim_ids,
                }
                for unit in speech.units
            ],
            "claims_json": claims_payload(research),
        },
        schema=ScenePlan,
        validate=_validate,
    )

    scene_plan = normalize_plan(result, speech).model_copy(
        update={"prompt_version": prompt.version, "prompt_hash": prompt.hash}
    )
    save_scenes(context.workspace, scene_plan)
    write_scene_prompts(context, scene_plan)

    context.project.scenes_path = relative_to(context.workspace.scenes_json, context.workspace.root)
    context.project.prompt_versions["director"] = prompt.version
    save_project(context.workspace, context.project)

    context.log.info(
        "scene_generation_completed",
        scenes=len(scene_plan.scenes),
        duration=scene_plan.total_duration_sec,
    )
    return scene_plan
