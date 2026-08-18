"""Spoken-delivery checks (spec v0.3 sections 18-21, 31).

These catch the things that make Korean short-form narration tiring to listen
to: breaths that carry three facts at once, six sentences ending the same way,
and a flat rhythm where every line is the same length.

The aim is not to force every ending to differ. It is to catch mechanical
repetition a listener would notice.
"""

from __future__ import annotations

import re
import statistics

from ..config import SpeechContract
from ..domain import ScenePlan, SpeechPlan, SpeechUnit
from ..utils import visible_length
from .report import QAIssue, error, warning

#: Markers that a second information event was packed into one breath.
_EVENT_MARKERS = ("그리고", "그다음", "그런 다음", "이후", "하고 나서", "면서")


def _ending_of(text: str, endings: list[str]) -> str | None:
    stripped = text.rstrip(" .!?。")
    for ending in sorted(endings, key=len, reverse=True):
        if stripped.endswith(ending):
            return ending
    return None


def check_unit_lengths(plan: SpeechPlan, contract: SpeechContract) -> list[QAIssue]:
    issues: list[QAIssue] = []
    for unit in plan.units:
        length = visible_length(unit.text)
        if length > contract.hard_split_review_chars:
            issues.append(
                warning(
                    "speech_unit_too_long",
                    f"{unit.id} is {length} characters, over the "
                    f"{contract.hard_split_review_chars} split threshold: "
                    f"'{unit.text}'",
                )
            )
        elif length > contract.max_preferred_unit_chars:
            issues.append(
                warning(
                    "speech_unit_long",
                    f"{unit.id} is {length} characters, over the preferred "
                    f"{contract.max_preferred_unit_chars}",
                )
            )
    return issues


def check_information_density(plan: SpeechPlan, contract: SpeechContract) -> list[QAIssue]:
    """One breath, one idea (spec v0.3 section 9)."""
    issues: list[QAIssue] = []
    for unit in plan.units:
        events = sum(1 for marker in _EVENT_MARKERS if marker in unit.text)
        if events > contract.max_information_events:
            issues.append(
                warning(
                    "speech_unit_multiple_events",
                    f"{unit.id} chains {events + 1} events in one breath: '{unit.text}'",
                )
            )
    return issues


def check_ending_repetition(plan: SpeechPlan, contract: SpeechContract) -> list[QAIssue]:
    if not contract.tracked_endings:
        return []
    issues: list[QAIssue] = []
    run_ending: str | None = None
    run_start = 0
    for index, unit in enumerate([*plan.units, None]):
        ending = _ending_of(unit.text, contract.tracked_endings) if unit else None
        if ending == run_ending and ending is not None:
            continue
        run_length = index - run_start
        if run_ending is not None and run_length > contract.max_consecutive_same_ending:
            issues.append(
                warning(
                    "speech_monotone_endings",
                    f"{run_length} units in a row end in '{run_ending}' "
                    f"({plan.units[run_start].id}..{plan.units[index - 1].id})",
                )
            )
        run_ending, run_start = ending, index
    return issues


def check_rhythm(plan: SpeechPlan, contract: SpeechContract) -> list[QAIssue]:
    """Flat rhythm: every breath the same length is as tiring as one long one."""
    lengths = [visible_length(unit.text) for unit in plan.units]
    if len(lengths) < 4:
        return []
    mean = statistics.fmean(lengths)
    if mean <= 0:
        return []
    variation = statistics.pstdev(lengths) / mean
    if variation < contract.min_length_variation_ratio:
        return [
            warning(
                "speech_flat_rhythm",
                f"unit lengths barely vary (ratio {variation:.2f} < "
                f"{contract.min_length_variation_ratio}); the narration will sound mechanical",
            )
        ]
    return []


def check_pauses(plan: SpeechPlan) -> list[QAIssue]:
    if plan.units and all(unit.pause_after_ms == 0 for unit in plan.units[:-1]):
        return [warning("speech_no_pauses", "no pauses were planned between units")]
    return []


def check_speech_plan(plan: SpeechPlan, contract: SpeechContract) -> list[QAIssue]:
    if not plan.units:
        return [error("speech_empty", "the speech plan has no units")]
    return [
        *check_unit_lengths(plan, contract),
        *check_information_density(plan, contract),
        *check_ending_repetition(plan, contract),
        *check_rhythm(plan, contract),
        *check_pauses(plan),
    ]


def check_scene_speech_alignment(scene_plan: ScenePlan, speech: SpeechPlan) -> list[QAIssue]:
    """Scene boundaries must fall between whole units (spec v0.3 section 15)."""
    issues: list[QAIssue] = []
    known = {unit.id for unit in speech.units}
    assigned: list[str] = []

    for scene in scene_plan.scenes:
        unknown = [uid for uid in scene.speech_unit_ids if uid not in known]
        if unknown:
            issues.append(
                error("scene_unknown_speech_unit", f"references unknown units {unknown}", scene.id)
            )
        assigned.extend(scene.speech_unit_ids)

    duplicates = sorted({uid for uid in assigned if assigned.count(uid) > 1})
    if duplicates:
        issues.append(
            error("speech_unit_reused", f"units appear in more than one scene: {duplicates}")
        )

    missing = [unit.id for unit in speech.units if unit.id not in set(assigned)]
    if missing:
        issues.append(error("speech_unit_unassigned", f"units no scene covers: {missing}"))

    order = [unit.id for unit in speech.units]
    covered = [uid for uid in assigned if uid in known]
    if covered != [uid for uid in order if uid in set(covered)]:
        issues.append(error("speech_unit_out_of_order", "scenes do not follow the speech order"))

    for scene in scene_plan.scenes:
        expected = " ".join(unit.text for unit in speech.units_for(scene.speech_unit_ids))
        if expected and _squash(scene.narration) != _squash(expected):
            issues.append(
                error(
                    "scene_narration_mismatch",
                    "scene narration is not exactly its speech units joined in order",
                    scene.id,
                )
            )
    return issues


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def units_in_scene_order(scene_plan: ScenePlan, speech: SpeechPlan) -> list[SpeechUnit]:
    ordered: list[SpeechUnit] = []
    for scene in scene_plan.scenes:
        ordered.extend(speech.units_for(scene.speech_unit_ids))
    return ordered
