"""Research stage schemas. The unit of research is a Claim, not a paragraph."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import ClaimConfidence


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: str
    publisher: str | None = None
    published_at: str | None = None
    accessed_at: str | None = None


class QuestionSpec(BaseModel):
    """The topic, restated as one answerable question (spec v0.2 section 12.1).

    "ATM은 돈을 어떻게 세는 걸까?" covers several different machines. Pinning the
    scope down here stops the rest of the pipeline from blending a cash-dispense
    ATM and a deposit ATM into one impossible mechanism.
    """

    model_config = ConfigDict(extra="forbid")

    original_topic: str
    resolved_question: str
    scope: str
    excluded: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str
    confidence: ClaimConfidence
    source_ids: list[str] = Field(default_factory=list)
    visualizable: bool = False
    notes: str | None = None

    @property
    def is_supported(self) -> bool:
        """A claim is usable in the script only when it cites at least one source."""
        return bool(self.source_ids)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    topic: str
    question: QuestionSpec
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    unsafe_or_uncertain_claims: list[str] = Field(default_factory=list)

    prompt_version: str | None = None
    prompt_hash: str | None = None

    @field_validator("claims")
    @classmethod
    def _unique_claim_ids(cls, claims: list[Claim]) -> list[Claim]:
        ids = [claim.id for claim in claims]
        duplicates = {cid for cid in ids if ids.count(cid) > 1}
        if duplicates:
            raise ValueError(f"duplicate claim ids: {sorted(duplicates)}")
        return claims

    @field_validator("sources")
    @classmethod
    def _unique_source_ids(cls, sources: list[SourceRef]) -> list[SourceRef]:
        ids = [source.id for source in sources]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"duplicate source ids: {sorted(duplicates)}")
        return sources

    def source_by_id(self, source_id: str) -> SourceRef | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def claim_by_id(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.id == claim_id), None)

    def supported_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.is_supported]

    def dangling_source_ids(self) -> list[str]:
        """Source ids referenced by a claim that do not exist in ``sources``."""
        known = {s.id for s in self.sources}
        missing: list[str] = []
        for claim in self.claims:
            missing.extend(sid for sid in claim.source_ids if sid not in known)
        return sorted(set(missing))
