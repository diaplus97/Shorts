"""Spoken narration model (spec v0.3 sections 6-7).

``ScriptResult`` says *what* is said and in what order. ``SpeechPlan`` says
*how it is read out*: where the breaths fall, how long the pauses are, and which
delivery each unit takes.

Splitting the two is what makes scene changes line up with speech. Scenes
reference speech unit ids, so a cut can never land in the middle of a sentence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Nothing should ever wait longer than this between breaths.
MAX_PAUSE_MS = 2000


class DeliveryMode(StrEnum):
    NEUTRAL = "neutral"
    CURIOUS = "curious"
    REVEAL = "reveal"
    EMPHASIS = "emphasis"
    CLOSING = "closing"


class SpeechUnit(BaseModel):
    """One breath. One idea."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str

    pause_before_ms: int = Field(default=0, ge=0, le=MAX_PAUSE_MS)
    pause_after_ms: int = Field(default=0, ge=0, le=MAX_PAUSE_MS)

    delivery: DeliveryMode = DeliveryMode.NEUTRAL
    emphasis_words: list[str] = Field(default_factory=list)

    referenced_claim_ids: list[str] = Field(default_factory=list)
    #: The script beat this unit was split out of.
    beat_id: str | None = None

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("a speech unit must have text")
        return text.strip()


class ToneProfile(BaseModel):
    """The channel's narrator, stated once instead of implied by prompts."""

    model_config = ConfigDict(extra="forbid")

    persona: str
    language: str = "ko"
    formality: str
    energy: str
    sentence_style: str
    prohibited_patterns: list[str] = Field(default_factory=list)


class SpeechPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    tone_profile: ToneProfile
    units: list[SpeechUnit] = Field(default_factory=list)
    target_duration_sec: float = Field(gt=0)
    estimated_duration_sec: float | None = None

    @field_validator("units")
    @classmethod
    def _unique_ids(cls, units: list[SpeechUnit]) -> list[SpeechUnit]:
        ids = [unit.id for unit in units]
        duplicates = {uid for uid in ids if ids.count(uid) > 1}
        if duplicates:
            raise ValueError(f"duplicate speech unit ids: {sorted(duplicates)}")
        return units

    @property
    def text(self) -> str:
        return " ".join(unit.text for unit in self.units)

    @property
    def total_pause_sec(self) -> float:
        gaps = sum(gap_ms_before(self.units, index) for index in range(len(self.units)))
        trailing = self.units[-1].pause_after_ms if self.units else 0
        return round((gaps + trailing) / 1000, 3)

    def unit_by_id(self, unit_id: str) -> SpeechUnit | None:
        return next((unit for unit in self.units if unit.id == unit_id), None)

    def units_for(self, unit_ids: list[str]) -> list[SpeechUnit]:
        resolved = [self.unit_by_id(uid) for uid in unit_ids]
        return [unit for unit in resolved if unit is not None]


def gap_ms_before(units: list[SpeechUnit], index: int) -> int:
    """Silence inserted in front of ``units[index]``.

    A unit's own `pause_before_ms` and its predecessor's `pause_after_ms`
    describe the same gap, so the wider of the two wins rather than both being
    added.
    """
    if index == 0:
        return units[0].pause_before_ms if units else 0
    return max(units[index - 1].pause_after_ms, units[index].pause_before_ms)


class SpeechTimingEntry(BaseModel):
    """Measured, not estimated: filled in after the audio actually exists."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0)
    #: Silence that follows this unit before the next one begins.
    gap_after: float = Field(default=0.0, ge=0)

    @property
    def end(self) -> float:
        return round(self.start + self.duration, 3)


class SpeechTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    entries: list[SpeechTimingEntry] = Field(default_factory=list)
    total_duration_sec: float = Field(default=0.0, ge=0)

    def entry_for(self, unit_id: str) -> SpeechTimingEntry | None:
        return next((entry for entry in self.entries if entry.unit_id == unit_id), None)

    def span_for(self, unit_ids: list[str]) -> tuple[float, float] | None:
        """Start and duration covering a group of units, gaps included."""
        entries = [entry for entry in self.entries if entry.unit_id in set(unit_ids)]
        if not entries:
            return None
        start = min(entry.start for entry in entries)
        end = max(entry.end + entry.gap_after for entry in entries)
        return round(start, 3), round(end - start, 3)
