"""Writer stage schemas (spec section 13)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import BeatPurpose


class ScriptBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    purpose: BeatPurpose
    text: str
    claim_ids: list[str] = Field(default_factory=list)

    #: Can this sentence be shown in a single shot? A sentence that cannot be
    #: shown does not belong in a video script (spec v0.2 section 13.1).
    visualizable: bool = False
    #: What the viewer sees while this sentence is spoken.
    visual_payoff: str | None = None


class ScriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    title: str
    hook: str
    narration: str
    beats: list[ScriptBeat] = Field(default_factory=list)
    target_duration_sec: float = Field(gt=0)
    resolved_question: str = ""
    referenced_claim_ids: list[str] = Field(default_factory=list)
    estimated_word_count: int = Field(ge=0, default=0)

    prompt_version: str | None = None
    prompt_hash: str | None = None

    @field_validator("beats")
    @classmethod
    def _unique_beat_ids(cls, beats: list[ScriptBeat]) -> list[ScriptBeat]:
        ids = [beat.id for beat in beats]
        duplicates = {bid for bid in ids if ids.count(bid) > 1}
        if duplicates:
            raise ValueError(f"duplicate beat ids: {sorted(duplicates)}")
        return beats

    @field_validator("narration")
    @classmethod
    def _narration_not_blank(cls, narration: str) -> str:
        if not narration.strip():
            raise ValueError("narration must not be empty")
        return narration

    def all_claim_ids(self) -> set[str]:
        ids = set(self.referenced_claim_ids)
        for beat in self.beats:
            ids.update(beat.claim_ids)
        return ids
