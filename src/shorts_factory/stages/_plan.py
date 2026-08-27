"""Dry-run planning types (spec section 46)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlannedCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    provider: str
    operation: str
    count: int = 1
    estimated_cost_usd: float = 0.0
    detail: str | None = None


class StagePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    skipped: bool = False
    reason: str | None = None
    calls: list[PlannedCall] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def estimated_cost_usd(self) -> float:
        return round(sum(call.estimated_cost_usd for call in self.calls), 6)

    @property
    def call_count(self) -> int:
        return sum(call.count for call in self.calls)
