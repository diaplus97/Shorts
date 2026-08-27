"""Asset generation bookkeeping (spec sections 23-24, 53)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import AssetStatus, AssetType


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = "ai_generated"
    source_url: str | None = None
    license: str | None = None
    generated_by_ai: bool = True


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    provider: str
    asset_type: AssetType
    provider_job_id: str | None = None
    status: AssetStatus = AssetStatus.PENDING
    attempt: int = 0
    prompt: str | None = None
    prompt_hash: str
    local_path: str | None = None
    duration_sec: float | None = None
    cost_usd: float | None = None
    error: str | None = None
    fallback_used: bool = False
    provenance: Provenance = Field(default_factory=Provenance)

    @property
    def is_usable(self) -> bool:
        return self.status is AssetStatus.COMPLETED and bool(self.local_path)


class AssetLedger(BaseModel):
    """All asset records for a project, keyed by scene id."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    records: dict[str, AssetRecord] = Field(default_factory=dict)

    def get(self, scene_id: str) -> AssetRecord | None:
        return self.records.get(scene_id)

    def put(self, record: AssetRecord) -> None:
        self.records[record.scene_id] = record

    def usable_scene_ids(self) -> set[str]:
        return {sid for sid, rec in self.records.items() if rec.is_usable}

    def total_cost_usd(self) -> float:
        return round(sum(rec.cost_usd or 0.0 for rec in self.records.values()), 6)
