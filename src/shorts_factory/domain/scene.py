"""Director stage schemas (spec sections 15-16).

A Scene describes the *meaning* of a shot. It never stores a provider-specific
prompt string; that is the job of the prompt adapters (spec section 20).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import AssetType, RealityType, ScenePriority


class ContinuitySpec(BaseModel):
    """Identity of a recurring object or location (spec sections 31-32)."""

    model_config = ConfigDict(extra="forbid")

    continuity_id: str
    fixed_description: str


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int = Field(ge=1)

    narration: str = ""
    duration_sec: float = Field(gt=0)
    purpose: str

    visual_subject: str
    environment: str
    action: str

    camera: str
    framing: str | None = None
    lighting: str | None = None

    reality_type: RealityType
    priority: ScenePriority
    asset_type: AssetType

    continuity: list[ContinuitySpec] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)

    transition_in: str | None = None
    transition_out: str | None = None

    negative_constraints: list[str] = Field(default_factory=list)

    @field_validator("duration_sec")
    @classmethod
    def _sane_duration(cls, value: float) -> float:
        if not 0.5 <= value <= 15.0:
            raise ValueError("scene duration_sec must be between 0.5 and 15.0 seconds")
        return value

    @model_validator(mode="after")
    def _visual_fields_present(self) -> Scene:
        for field in ("visual_subject", "environment", "action", "camera", "purpose"):
            if not getattr(self, field).strip():
                raise ValueError(f"scene {self.id}: '{field}' must not be empty")
        return self


class ScenePlan(BaseModel):
    """The full ordered set of scenes for one Short."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    scenes: list[Scene] = Field(default_factory=list)
    continuity: list[ContinuitySpec] = Field(default_factory=list)
    visual_notes: str | None = None

    prompt_version: str | None = None
    prompt_hash: str | None = None

    @field_validator("scenes")
    @classmethod
    def _ordered_and_unique(cls, scenes: list[Scene]) -> list[Scene]:
        ids = [scene.id for scene in scenes]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"duplicate scene ids: {sorted(duplicates)}")
        orders = [scene.order for scene in scenes]
        if orders != sorted(orders):
            raise ValueError("scenes must be sorted by ascending order")
        if len(set(orders)) != len(orders):
            raise ValueError("scene order values must be unique")
        return scenes

    @property
    def total_duration_sec(self) -> float:
        return round(sum(scene.duration_sec for scene in self.scenes), 3)

    def scene_by_id(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)
