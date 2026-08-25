"""Content Quality Contract enforcement (spec v0.2 section 36.0).

Every other check in this package asks whether the pipeline ran correctly.
These ask whether the result is worth watching:

* does the hook leave the viewer with a question?
* is the script concrete, or does it hide behind "장치", "과정", "시스템"?
* can every factual sentence actually be shown?
* does each scene change something visible on screen?
* do the scenes share one world, or are they twelve unrelated clips?

The clauses live in ``config/content_contract.yaml`` so they can be tuned
without touching code, but they are enforced here rather than merely requested
in a prompt.
"""

from __future__ import annotations

import re

from ..config import ContentContract, ScriptSettings
from ..domain import (
    NON_FACTUAL_PURPOSES,
    BeatPurpose,
    ResearchResult,
    ScenePlan,
    ScriptResult,
)
from ..utils import estimate_duration_sec, visible_length
from .report import QAIssue, error, warning

#: Interrogatives that make a Korean sentence a real question.
_QUESTION_MARKERS = ("?", "까", "왜", "무엇", "뭘", "어떻게", "어디", "언제", "누가", "얼마")

#: A scene that only restates narration tends to describe a state, not an event.
_STATIC_VERB_HINTS = ("있다", "이다", "입니다", "존재", "구성되")


def check_hook(
    script: ScriptResult, contract: ContentContract, script_settings: ScriptSettings
) -> list[QAIssue]:
    issues: list[QAIssue] = []
    clause = contract.hook
    hook = script.hook.strip()

    if clause.must_create_question and not any(marker in hook for marker in _QUESTION_MARKERS):
        issues.append(
            error(
                "hook_no_question",
                "the hook does not pose a question; the first three seconds must "
                f"leave the viewer wanting an answer (hook: {hook!r})",
            )
        )

    spoken = estimate_duration_sec(hook, script_settings.chars_per_sec)
    if spoken > clause.max_seconds:
        issues.append(
            error(
                "hook_too_long",
                f"the hook reads as {spoken:.1f}s, over the {clause.max_seconds:.0f}s budget",
            )
        )
    return issues


def check_generic_nouns(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Abstraction used where a concrete noun was available (spec v0.2 section 13.1)."""
    clause = contract.script
    if not clause.ban_generic_nouns or not clause.generic_nouns:
        return []

    counts = {
        noun: len(re.findall(re.escape(noun), script.narration)) for noun in clause.generic_nouns
    }
    used = {noun: count for noun, count in counts.items() if count}
    total = sum(used.values())
    if total <= clause.max_generic_nouns:
        return []

    detail = ", ".join(f"{noun}x{count}" for noun, count in sorted(used.items()))
    return [
        error(
            "script_generic_nouns",
            f"narration uses {total} generic nouns ({detail}), over the limit of "
            f"{clause.max_generic_nouns}. Name the actual part and what it does.",
        )
    ]


def check_concrete_mechanism(
    script: ScriptResult, research: ResearchResult, contract: ContentContract
) -> list[QAIssue]:
    """Every factual beat must be showable and say what is on screen."""
    if not contract.script.concrete_mechanism_required:
        return []

    issues: list[QAIssue] = []
    visualizable_claims = {claim.id for claim in research.claims if claim.visualizable}

    factual = [beat for beat in script.beats if beat.purpose not in NON_FACTUAL_PURPOSES]
    unshowable = [beat for beat in factual if not beat.visualizable]

    # A sentence carrying context, scale or consequence often has no single shot
    # for it, and those are the sentences that make an explanation an
    # explanation. The benchmark narration is roughly two-thirds unshowable by
    # this measure. What is worth failing is a script that is *mostly* talk with
    # nothing to cut to, not the presence of any such sentence.
    limit = contract.script.max_unshowable_ratio
    if factual and len(unshowable) / len(factual) > limit:
        listed = ", ".join(beat.id for beat in unshowable)
        issues.append(
            error(
                "script_mostly_unshowable",
                f"{len(unshowable)} of {len(factual)} factual beats have no shot "
                f"({listed}), over the limit of {limit:.0%}. This is a video; most of "
                "it has to be something the viewer can watch happen.",
            )
        )

    for beat in factual:
        if beat.visualizable and not (beat.visual_payoff or "").strip():
            issues.append(
                error(
                    "beat_no_visual_payoff",
                    f"beat {beat.id} ({beat.purpose}) is marked showable but does not "
                    "say what the viewer sees while it is spoken",
                )
            )
        if beat.claim_ids and not (set(beat.claim_ids) & visualizable_claims):
            issues.append(
                warning(
                    "beat_claims_not_visualizable",
                    f"beat {beat.id} rests only on claims research marked unshowable "
                    f"({', '.join(beat.claim_ids)})",
                )
            )
    return issues


def check_scenes(plan: ScenePlan, contract: ContentContract) -> list[QAIssue]:
    clause = contract.scene
    issues: list[QAIssue] = []

    for scene in plan.scenes:
        if clause.visible_change_required and not scene.visible_change.strip():
            issues.append(
                error("scene_no_visible_change", "nothing visibly changes in this shot", scene.id)
            )
        if clause.question_answered_required and not scene.question_answered.strip():
            issues.append(
                error(
                    "scene_no_question",
                    "the scene does not say which question it answers",
                    scene.id,
                )
            )
        if clause.static_exposition_forbidden and _is_static_exposition(scene):
            issues.append(
                warning(
                    "scene_static_exposition",
                    "the visible change reads as a state rather than an event; "
                    f"'{scene.visible_change}' has no before and after",
                    scene.id,
                )
            )

    if clause.shared_world_required and plan.scenes:
        if not plan.world.machine_id.strip():
            issues.append(
                error(
                    "plan_no_world",
                    "the plan declares no shared world; twelve scenes would become "
                    "twelve unrelated clips",
                )
            )
        anchored = sum(1 for scene in plan.scenes if scene.continuity_ids)
        if anchored < max(2, len(plan.scenes) // 3):
            issues.append(
                warning(
                    "plan_weak_continuity",
                    f"only {anchored} of {len(plan.scenes)} scenes reference a continuity "
                    "id; recurring objects will drift between shots",
                )
            )
    return issues


def check_video_contract(plan: ScenePlan, contract: ContentContract) -> list[QAIssue]:
    if not contract.video.visual_subject_required:
        return []
    return [
        error("scene_no_visual_subject", "the scene has no visual subject", scene.id)
        for scene in plan.scenes
        if not scene.visual_subject.strip()
    ]


def _is_static_exposition(scene) -> bool:
    change = scene.visible_change.strip()
    if visible_length(change) < 6:
        return True
    has_transition = "→" in change or "->" in change or " to " in change.lower()
    return not has_transition and any(hint in change for hint in _STATIC_VERB_HINTS)


def check_script_contract(
    script: ScriptResult,
    research: ResearchResult,
    contract: ContentContract,
    script_settings: ScriptSettings,
) -> list[QAIssue]:
    """Everything the contract asks of the writer, in one call."""
    return [
        *check_hook(script, contract, script_settings),
        *check_generic_nouns(script, contract),
        *check_concrete_mechanism(script, research, contract),
    ]


def check_scene_contract(plan: ScenePlan, contract: ContentContract) -> list[QAIssue]:
    """Everything the contract asks of the director, in one call."""
    return [*check_scenes(plan, contract), *check_video_contract(plan, contract)]


def hook_purposes_present(script: ScriptResult) -> bool:
    return any(beat.purpose is BeatPurpose.HOOK for beat in script.beats)
