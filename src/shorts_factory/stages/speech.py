"""Speech planning: script -> breaths (spec v0.3 sections 6-12).

A deterministic transformation, not an agent and not an extra LLM call. The
writer already decides *what* is said; splitting Korean prose into breaths and
choosing pause lengths is rule-work, and paying a model to do it would add
latency, cost and non-determinism for no gain.

The writer prompt is where rhythm actually comes from: this stage cannot merge
two flat sentences into one good one, it can only cut a long one into breaths
and flag what the writer should have done better.
"""

from __future__ import annotations

import re

from ..config import SpeechContract
from ..domain import (
    BeatPurpose,
    DeliveryMode,
    ScriptBeat,
    ScriptResult,
    SpeechPlan,
    SpeechUnit,
    ToneProfile,
)
from ..pipeline.checkpoint import require_script, save_project, save_speech_plan
from ..pipeline.context import RunContext
from ..quality import QAReport, check_speech_plan
from ..utils import estimate_duration_sec, normalize_whitespace, relative_to, visible_length
from ._plan import StagePlan

STAGE_NAME = "speak"

# Korean text mixes ASCII and full-width sentence punctuation.
_SENTENCE_END = re.compile(r"(?<=[.!?。？！])\s+")  # noqa: RUF001

#: Delivery follows the beat's job in the arc.
_DELIVERY_BY_PURPOSE = {
    BeatPurpose.HOOK: DeliveryMode.CURIOUS,
    BeatPurpose.REVEAL: DeliveryMode.REVEAL,
    BeatPurpose.PROCESS: DeliveryMode.NEUTRAL,
    BeatPurpose.SURPRISE: DeliveryMode.EMPHASIS,
    BeatPurpose.CLOSING: DeliveryMode.CLOSING,
    BeatPurpose.TRANSITION: DeliveryMode.NEUTRAL,
}


def split_sentence(text: str, contract: SpeechContract) -> list[str]:
    """Break one sentence into breaths, preferring clause endings.

    Never cuts below ``min_unit_chars``: a fragment shorter than that is a
    particle or a number, and reading it alone sounds broken.
    """
    text = normalize_whitespace(text)
    if visible_length(text) <= contract.hard_split_review_chars:
        return [text]

    pieces = _split_on_commas(text)
    if all(visible_length(piece) <= contract.hard_split_review_chars for piece in pieces):
        return _merge_runts(pieces, contract)

    expanded: list[str] = []
    for piece in pieces:
        if visible_length(piece) <= contract.hard_split_review_chars:
            expanded.append(piece)
        else:
            expanded.extend(_split_on_clause_endings(piece, contract))
    return _merge_runts(expanded, contract)


def _split_on_commas(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[,，、])\s*", text)]  # noqa: RUF001
    return [part for part in parts if part]


def _split_on_clause_endings(text: str, contract: SpeechContract) -> list[str]:
    """Cut after a connective ending, closest to the middle of the clause."""
    if not contract.clause_endings:
        return [text]
    target = len(text) // 2
    best: tuple[int, int] | None = None
    for ending in contract.clause_endings:
        for match in re.finditer(re.escape(ending), text):
            cut = match.end()
            head, tail = text[:cut].strip(), text[cut:].strip()
            if (
                visible_length(head) < contract.min_unit_chars
                or visible_length(tail) < contract.min_unit_chars
            ):
                continue
            distance = abs(cut - target)
            if best is None or distance < best[0]:
                best = (distance, cut)
    if best is None:
        return [text]
    cut = best[1]
    head, tail = text[:cut].strip(), text[cut:].strip()
    return (
        [head, *_split_on_clause_endings(tail, contract)]
        if (visible_length(tail) > contract.hard_split_review_chars)
        else [head, tail]
    )


def _merge_runts(pieces: list[str], contract: SpeechContract) -> list[str]:
    """Fold anything too short to stand alone back into its neighbour."""
    merged: list[str] = []
    for piece in pieces:
        if merged and visible_length(piece) < contract.min_unit_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    if len(merged) > 1 and visible_length(merged[0]) < contract.min_unit_chars:
        merged[1] = f"{merged[0]} {merged[1]}"
        merged.pop(0)
    return merged


def _pause_after(
    text: str,
    delivery: DeliveryMode,
    *,
    ends_beat: bool,
    ends_sentence: bool,
    contract: SpeechContract,
) -> int:
    pauses = contract.pauses_ms
    if ends_beat and delivery in {DeliveryMode.REVEAL, DeliveryMode.EMPHASIS}:
        return pauses.reveal
    if ends_beat:
        return pauses.section
    if text.rstrip().endswith("?"):
        return pauses.question
    if ends_sentence:
        return pauses.sentence
    if text.rstrip().endswith((",", "，", "、")):  # noqa: RUF001
        return pauses.clause
    return pauses.shift


def units_from_beat(
    beat: ScriptBeat, contract: SpeechContract, start_index: int
) -> list[SpeechUnit]:
    delivery = _DELIVERY_BY_PURPOSE.get(beat.purpose, DeliveryMode.NEUTRAL)
    sentences = [s for s in _SENTENCE_END.split(normalize_whitespace(beat.text)) if s.strip()]

    texts: list[tuple[str, bool]] = []
    for sentence in sentences:
        breaths = split_sentence(sentence, contract)
        for offset, breath in enumerate(breaths):
            texts.append((breath, offset == len(breaths) - 1))

    emphasis = (beat.emphasis or "").strip()
    units: list[SpeechUnit] = []
    for offset, (text, ends_sentence) in enumerate(texts):
        ends_beat = offset == len(texts) - 1
        units.append(
            SpeechUnit(
                id=f"U{start_index + offset:02d}",
                text=text,
                # The stressed word belongs to whichever breath actually says it.
                emphasis_words=[emphasis] if emphasis and emphasis in text else [],
                pause_after_ms=_pause_after(
                    text,
                    delivery,
                    ends_beat=ends_beat,
                    ends_sentence=ends_sentence,
                    contract=contract,
                ),
                delivery=delivery,
                # Only the beat's own claims travel with its units.
                referenced_claim_ids=list(beat.claim_ids),
                beat_id=beat.id,
            )
        )
    return units


def build_plan(script: ScriptResult, context: RunContext) -> SpeechPlan:
    contract = context.config.voice.speech
    tone = ToneProfile.model_validate(context.config.voice.tone_profile)

    units: list[SpeechUnit] = []
    for beat in script.beats:
        units.extend(units_from_beat(beat, contract, start_index=len(units) + 1))
    if units:
        # Nothing follows the last unit, so its pause would only pad the tail.
        units[-1] = units[-1].model_copy(update={"pause_after_ms": 0})

    spoken = estimate_duration_sec(script.narration, context.settings.script.chars_per_sec)
    plan = SpeechPlan(
        tone_profile=tone,
        units=units,
        target_duration_sec=script.target_duration_sec,
    )
    return plan.model_copy(
        update={"estimated_duration_sec": round(spoken + plan.total_pause_sec, 3)}
    )


def plan(context: RunContext) -> StagePlan:
    return StagePlan(
        stage=STAGE_NAME,
        notes=["deterministic segmentation, no LLM call and no cost"],
    )


async def run(context: RunContext) -> SpeechPlan:
    script = require_script(context.workspace)
    speech_plan = build_plan(script, context)

    report = QAReport(issues=check_speech_plan(speech_plan, context.config.voice.speech))
    for issue in report.warnings:
        context.log.warning("speech_warning", issue=issue.render())
    if not report.ok:
        from ..errors import PipelineValidationError

        raise PipelineValidationError(
            "speech planning failed:\n" + "\n".join(issue.render() for issue in report.errors)
        )

    save_speech_plan(context.workspace, speech_plan)
    context.project.speech_path = relative_to(context.workspace.speech_json, context.workspace.root)
    save_project(context.workspace, context.project)

    context.log.info(
        "speech_plan_completed",
        units=len(speech_plan.units),
        estimated=speech_plan.estimated_duration_sec,
        pause_sec=speech_plan.total_pause_sec,
    )
    return speech_plan
