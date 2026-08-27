"""Render manifest consumed by the FFmpeg compositor (spec section 43)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManifestScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    asset: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"

    resolution: tuple[int, int]
    fps: int = Field(gt=0)
    scenes: list[ManifestScene] = Field(default_factory=list)
    voice: str | None = None
    subtitle: str | None = None
    #: Styled ASS rendering of the same cues, used for burn-in.
    subtitle_burn: str | None = None
    bgm: str | None = None

    @field_validator("scenes")
    @classmethod
    def _contiguous(cls, scenes: list[ManifestScene]) -> list[ManifestScene]:
        cursor = 0.0
        for scene in scenes:
            if abs(scene.start - cursor) > 0.01:
                raise ValueError(
                    f"manifest scene {scene.scene_id} starts at {scene.start}, expected {cursor}"
                )
            cursor += scene.duration
        return scenes

    @property
    def total_duration_sec(self) -> float:
        return round(sum(scene.duration for scene in self.scenes), 3)
