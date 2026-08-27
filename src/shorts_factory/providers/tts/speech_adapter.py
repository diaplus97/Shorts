"""SpeechPlan -> what a TTS provider is actually asked to say (spec v0.3 sections 22-23).

Provider syntax never enters the domain model. A SpeechUnit has no `ssml`
field; this adapter is where a plan becomes provider input.

Two representations are offered because providers differ:

* :func:`segments_for` — one call per unit. Pauses become real silence inserted
  during concatenation, which also yields measured per-unit timings. This is
  what the pipeline uses, because scene and subtitle sync depend on knowing
  where each unit actually starts.
* :func:`as_single_text` — the whole plan as one string, pauses expressed as
  punctuation and paragraph breaks. For a provider that reads better with full
  context, or that bills per request rather than per character.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ...domain import SpeechPlan, gap_ms_before


class SpeechSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    text: str
    #: Silence to insert after this segment, in seconds.
    gap_after_sec: float = 0.0


def segments_for(plan: SpeechPlan) -> list[SpeechSegment]:
    """One segment per unit, with the gap that follows it already resolved."""
    segments: list[SpeechSegment] = []
    for index, unit in enumerate(plan.units):
        next_gap = (
            gap_ms_before(plan.units, index + 1)
            if index + 1 < len(plan.units)
            else unit.pause_after_ms
        )
        segments.append(
            SpeechSegment(
                unit_id=unit.id,
                text=unit.text,
                gap_after_sec=round(next_gap / 1000, 3),
            )
        )
    return segments


def lead_silence_sec(plan: SpeechPlan) -> float:
    return round(gap_ms_before(plan.units, 0) / 1000, 3) if plan.units else 0.0


def as_single_text(plan: SpeechPlan, *, paragraph_pause_ms: int = 400) -> str:
    """The whole plan as one string, pauses approximated with punctuation.

    A long pause becomes a paragraph break and a short one a line break, which
    is the most portable way to ask for a breath from a provider with no
    prosody controls.
    """
    lines: list[str] = []
    for index, unit in enumerate(plan.units):
        lines.append(unit.text)
        gap = gap_ms_before(plan.units, index + 1) if index + 1 < len(plan.units) else 0
        if gap >= paragraph_pause_ms:
            lines.append("")
    return "\n".join(lines).strip()
