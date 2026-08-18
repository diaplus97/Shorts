"""Canonical persistent project state (spec section 10).

``project.json`` is the single source of truth for what has been done and what
still needs doing. Every stage reads it, updates it, and writes it atomically.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import PipelineState, Stage, StageStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_done(self) -> bool:
        return self.status is StageStatus.COMPLETED


class CostSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_usd: float = 0.0
    search_usd: float = 0.0
    image_usd: float = 0.0
    video_usd: float = 0.0
    tts_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return round(
            self.llm_usd + self.search_usd + self.image_usd + self.video_usd + self.tts_usd, 6
        )


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    project_id: str
    slug: str
    topic: str
    content_type: str

    created_at: datetime
    updated_at: datetime

    state: PipelineState = PipelineState.CREATED
    stages: dict[str, StageRecord] = Field(default_factory=dict)

    research_path: str | None = None
    script_path: str | None = None
    scenes_path: str | None = None
    assets_path: str | None = None
    audio_path: str | None = None
    subtitle_path: str | None = None
    manifest_path: str | None = None
    final_video_path: str | None = None

    providers: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)

    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    cost_breakdown: CostSummary = Field(default_factory=CostSummary)

    contains_ai_generated_visuals: bool = True
    notes: list[str] = Field(default_factory=list)

    def stage(self, stage: Stage) -> StageRecord:
        record = self.stages.get(stage.value)
        if record is None:
            record = StageRecord()
            self.stages[stage.value] = record
        return record

    def is_stage_completed(self, stage: Stage) -> bool:
        return self.stage(stage).is_done

    def mark_stage_running(self, stage: Stage) -> None:
        record = self.stage(stage)
        record.status = StageStatus.RUNNING
        record.attempts += 1
        record.started_at = utcnow()
        record.error = None
        self.updated_at = utcnow()

    def mark_stage_completed(self, stage: Stage, new_state: PipelineState | None = None) -> None:
        record = self.stage(stage)
        record.status = StageStatus.COMPLETED
        record.completed_at = utcnow()
        record.error = None
        if new_state is not None:
            self.state = new_state
        self.updated_at = utcnow()

    def mark_stage_failed(self, stage: Stage, error: str) -> None:
        record = self.stage(stage)
        record.status = StageStatus.FAILED
        # Keep the error short; full tracebacks live in the log file.
        record.error = error[:2000]
        self.state = PipelineState.FAILED
        self.updated_at = utcnow()

    def mark_stage_skipped(self, stage: Stage) -> None:
        record = self.stage(stage)
        if record.status is not StageStatus.COMPLETED:
            record.status = StageStatus.SKIPPED
        self.updated_at = utcnow()
