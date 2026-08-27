"""Structural QA (spec section 36.1). Pure code, no LLM."""

from __future__ import annotations

from ..config import Budgets, Settings
from ..domain import AssetLedger, ScenePlan, ScenePriority, ScriptResult
from ..utils import normalize_whitespace, visible_length
from .report import QAIssue, error, warning


def check_script(script: ScriptResult, settings: Settings) -> list[QAIssue]:
    issues: list[QAIssue] = []
    script_settings = settings.script

    # Spoken characters plus the pause budget: what the finished video will run.
    estimated = (
        visible_length(script.narration) / script_settings.chars_per_sec
        + script_settings.pause_budget_sec
    )
    if not script_settings.min_duration_sec <= estimated <= script_settings.max_duration_sec:
        issues.append(
            error(
                "script_duration",
                f"narration reads as {estimated:.1f}s, outside the "
                f"{script_settings.min_duration_sec:.0f}-"
                f"{script_settings.max_duration_sec:.0f}s window",
            )
        )

    if not script.beats:
        issues.append(error("script_beats", "script has no beats"))

    joined = normalize_whitespace(" ".join(beat.text for beat in script.beats))
    if joined and normalize_whitespace(script.narration) != joined:
        issues.append(
            error(
                "script_narration_mismatch",
                "narration is not the concatenation of the beat texts; "
                "the director splits on beats, so they must match",
            )
        )

    if script.beats and normalize_whitespace(script.beats[0].text) != normalize_whitespace(
        script.hook
    ):
        issues.append(warning("script_hook", "the first beat is not the declared hook"))

    purposes = {beat.purpose for beat in script.beats}
    for required in ("hook", "closing"):
        if required not in purposes:
            issues.append(warning("script_arc", f"no beat with purpose '{required}'"))

    banned_openings = ("안녕하세요", "오늘은", "구독", "좋아요를")
    head = normalize_whitespace(script.hook)[:20]
    for banned in banned_openings:
        if banned in head:
            issues.append(error("script_intro", f"hook contains a banned opening: '{banned}'"))

    banned_hype = ("평생 속고", "충격적인 진실", "아무도 몰랐", "소름")
    for banned in banned_hype:
        if banned in script.narration:
            issues.append(error("script_hype", f"narration contains unfounded hype: '{banned}'"))

    return issues


def check_scene_plan(
    plan: ScenePlan,
    script: ScriptResult,
    settings: Settings,
    budgets: Budgets,
) -> list[QAIssue]:
    issues: list[QAIssue] = []
    scene_settings = settings.scenes

    count = len(plan.scenes)
    if not scene_settings.min_scenes <= count <= scene_settings.max_scenes:
        issues.append(
            error(
                "scene_count",
                f"{count} scenes, expected {scene_settings.min_scenes}-{scene_settings.max_scenes}",
            )
        )

    total = plan.total_duration_sec
    if not settings.script.min_duration_sec <= total <= settings.script.max_duration_sec:
        issues.append(
            error(
                "scene_total_duration",
                f"scenes total {total:.1f}s, outside the "
                f"{settings.script.min_duration_sec:.0f}-"
                f"{settings.script.max_duration_sec:.0f}s window",
            )
        )

    for scene in plan.scenes:
        if not (
            scene_settings.min_scene_duration_sec
            <= scene.duration_sec
            <= scene_settings.max_scene_duration_sec
        ):
            issues.append(
                warning(
                    "scene_duration",
                    f"{scene.duration_sec:.2f}s is outside the "
                    f"{scene_settings.min_scene_duration_sec}-"
                    f"{scene_settings.max_scene_duration_sec}s guideline",
                    scene.id,
                )
            )

    # Every scene must declare how literally it should be read.
    for scene in plan.scenes:
        if scene.reality_type is None:  # pragma: no cover - schema enforces this
            issues.append(error("scene_reality_type", "missing reality_type", scene.id))

    high = [scene for scene in plan.scenes if scene.priority is ScenePriority.HIGH]
    allowance = budgets.video.max_high_priority_scenes
    if len(high) > allowance:
        issues.append(
            error(
                "scene_priority_budget",
                f"{len(high)} HIGH priority scenes exceed the budget of {allowance} "
                "(config/budgets.yaml: video.max_high_priority_scenes)",
            )
        )

    # A box is emphasis, and emphasis is relative. Boxing most of the shots
    # says nothing about any of them.
    boxed = [scene.id for scene in plan.scenes if scene.highlight is not None]
    limit = scene_settings.max_highlight_ratio
    if plan.scenes and limit > 0 and len(boxed) > len(plan.scenes) * limit:
        issues.append(
            warning(
                "scene_highlight_overuse",
                f"{len(boxed)} of {len(plan.scenes)} scenes carry a highlight box "
                f"(over {limit:.0%}). Keep the box for the shots where the narration "
                "names one part of a busy frame; elsewhere it is just a border.",
            )
        )

    scene_narration = normalize_whitespace(" ".join(scene.narration for scene in plan.scenes))
    if scene_narration != normalize_whitespace(script.narration):
        issues.append(
            error(
                "scene_narration_coverage",
                "scene narration does not reproduce the script narration exactly; "
                "voice and picture would drift apart",
            )
        )

    return issues


def check_assets(plan: ScenePlan, ledger: AssetLedger) -> list[QAIssue]:
    issues: list[QAIssue] = []
    usable = ledger.usable_scene_ids()
    for scene in plan.scenes:
        record = ledger.get(scene.id)
        if record is None:
            issues.append(error("asset_missing", "no asset record", scene.id))
        elif scene.id not in usable:
            issues.append(error("asset_unusable", f"asset status is {record.status}", scene.id))
        elif record.fallback_used:
            issues.append(
                warning("asset_fallback", "rendered from a still image fallback", scene.id)
            )
    return issues
