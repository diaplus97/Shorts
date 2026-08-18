"""Per-call cost ledger (spec section 30).

Costs are appended to ``logs/costs.jsonl`` inside the project directory, so the
totals survive a crash and a resume never double-counts a call that already
happened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain import CostSummary
from ..utils import append_jsonl, read_jsonl

COST_KINDS = ("llm", "search", "image", "video", "tts")


class CostEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    provider: str
    operation: str
    scene_id: str | None = None
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def billed_usd(self) -> float:
        return self.actual_cost_usd if self.actual_cost_usd is not None else self.estimated_cost_usd


class CostTracker:
    """Append-only cost ledger for one project."""

    def __init__(self, ledger_path: str | Path) -> None:
        self.ledger_path = Path(ledger_path)
        self._events: list[CostEvent] = [
            CostEvent.model_validate(row) for row in read_jsonl(self.ledger_path)
        ]

    @property
    def events(self) -> list[CostEvent]:
        return list(self._events)

    def record(self, event: CostEvent) -> CostEvent:
        if event.kind not in COST_KINDS:
            raise ValueError(f"unknown cost kind '{event.kind}'")
        self._events.append(event)
        append_jsonl(self.ledger_path, event.model_dump(mode="json"))
        return event

    def total_usd(self) -> float:
        return round(sum(event.billed_usd for event in self._events), 6)

    def total_for(self, kind: str) -> float:
        return round(
            sum(event.billed_usd for event in self._events if event.kind == kind),
            6,
        )

    def call_count(self, kind: str) -> int:
        return sum(1 for event in self._events if event.kind == kind)

    def scene_attempts(self, kind: str, scene_id: str) -> int:
        return sum(1 for event in self._events if event.kind == kind and event.scene_id == scene_id)

    def summary(self) -> CostSummary:
        return CostSummary(
            llm_usd=self.total_for("llm"),
            search_usd=self.total_for("search"),
            image_usd=self.total_for("image"),
            video_usd=self.total_for("video"),
            tts_usd=self.total_for("tts"),
        )

    def render_table(self) -> str:
        summary = self.summary()
        rows = [
            ("LLM", summary.llm_usd),
            ("SEARCH", summary.search_usd),
            ("IMAGE", summary.image_usd),
            ("VIDEO", summary.video_usd),
            ("TTS", summary.tts_usd),
        ]
        lines = ["PROJECT COST"]
        lines.extend(f"{label:<10} ${value:>7.4f}" for label, value in rows)
        lines.append("-" * 18)
        lines.append(f"{'TOTAL':<10} ${summary.total_usd:>7.4f}")
        return "\n".join(lines)
