"""Production readiness gate (spec v0.2 section 36.4).

The pipeline running to completion is not the same as the result being
publishable. This module answers one question: may this run write ``final.mp4``?

A mock provider anywhere in the chain, a missing scene, a broken picture or a
silent voice track all say no.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..config import AppConfig
from ..domain import AssetLedger, ScenePlan
from ..errors import MediaError
from ..media import MediaInfo, analyze_audio, audio_problems, probe
from ..providers import ProviderSet


class ProductionReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_valid: bool = False
    audio_valid: bool = False
    contains_mock_assets: bool = True
    missing_scenes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: Why this run is not production ready, in words a human can act on.
    blocking_reasons: list[str] = Field(default_factory=list)
    mock_providers: list[str] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.video_valid
            and self.audio_valid
            and not self.contains_mock_assets
            and not self.missing_scenes
        )

    def render(self) -> str:
        lines = [
            f"production ready : {'yes' if self.ready else 'no'}",
            f"video valid      : {self.video_valid}",
            f"audio valid      : {self.audio_valid}",
            f"mock assets      : {self.contains_mock_assets}"
            + (f" ({', '.join(self.mock_providers)})" if self.mock_providers else ""),
            f"missing scenes   : {self.missing_scenes or '—'}",
        ]
        lines.extend(f"blocked by       : {reason}" for reason in self.blocking_reasons)
        lines.extend(f"warning          : {warning}" for warning in self.warnings)
        return "\n".join(lines)


def mock_provider_kinds(providers: ProviderSet) -> list[str]:
    """Which provider slots are still filled by a mock."""
    return sorted(kind for kind, provider in providers.as_dict().items() if provider.is_mock)


def missing_scene_ids(plan: ScenePlan, ledger: AssetLedger) -> list[str]:
    usable = ledger.usable_scene_ids()
    return [scene.id for scene in plan.scenes if scene.id not in usable]


def assess_video(info: MediaInfo, config: AppConfig) -> tuple[bool, list[str]]:
    output = config.settings.output
    reasons: list[str] = []
    if not info.has_video:
        reasons.append("no video stream")
    if info.duration_sec <= 0:
        reasons.append("video duration is zero")
    if (info.width, info.height) != output.resolution:
        reasons.append(
            f"resolution {info.width}x{info.height}, expected {output.width}x{output.height}"
        )
    return not reasons, reasons


def assess(
    *,
    config: AppConfig,
    providers: ProviderSet,
    plan: ScenePlan,
    ledger: AssetLedger,
    video_path: Path | None = None,
    voice_path: Path | None = None,
) -> ProductionReadinessResult:
    """Judge one run. Paths that do not exist yet are simply not asserted on."""
    mocks = mock_provider_kinds(providers)
    missing = missing_scene_ids(plan, ledger)

    result = ProductionReadinessResult(
        contains_mock_assets=bool(mocks),
        mock_providers=mocks,
        missing_scenes=missing,
    )
    if mocks:
        result.blocking_reasons.append(f"mock providers in use: {', '.join(mocks)}")
    if missing:
        result.blocking_reasons.append(f"scenes without a usable asset: {', '.join(missing)}")

    fallback_scenes = [
        scene_id
        for scene_id, record in ledger.records.items()
        if record.fallback_used and record.is_usable
    ]
    if fallback_scenes:
        result.warnings.append(
            f"{len(fallback_scenes)} scene(s) rendered from a still fallback: "
            f"{', '.join(sorted(fallback_scenes))}"
        )

    if video_path is not None and video_path.exists():
        try:
            result.video_valid, reasons = assess_video(probe(video_path), config)
        except MediaError as exc:
            result.video_valid, reasons = False, [str(exc)]
        result.blocking_reasons.extend(reasons)
    elif video_path is not None:
        result.blocking_reasons.append(f"{video_path} does not exist")

    audio_target = video_path if (video_path and video_path.exists()) else voice_path
    if audio_target is not None and audio_target.exists():
        settings = config.settings.quality.audio
        try:
            analysis = analyze_audio(audio_target, settings)
            problems = audio_problems(analysis, settings)
        except MediaError as exc:
            problems = [str(exc)]
        result.audio_valid = not problems
        result.blocking_reasons.extend(problems)
    elif audio_target is not None:
        result.blocking_reasons.append(f"{audio_target} does not exist")

    return result
