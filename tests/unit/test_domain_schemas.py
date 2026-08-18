"""Schema validation and JSON round trips (spec Phase 1)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shorts_factory.domain import (
    AssetLedger,
    AssetRecord,
    AssetStatus,
    AssetType,
    Claim,
    ClaimConfidence,
    Manifest,
    ManifestScene,
    PipelineState,
    Project,
    RealityType,
    ResearchResult,
    Scene,
    ScenePlan,
    ScenePriority,
    ScriptBeat,
    ScriptResult,
    SourceRef,
    Stage,
    utcnow,
)


def make_scene(**overrides) -> Scene:
    base = {
        "id": "S01",
        "order": 1,
        "narration": "안에서는 여러 단계가 순서대로 움직입니다.",
        "duration_sec": 4.0,
        "purpose": "reveal",
        "visual_subject": "ATM cash counter",
        "environment": "bank lobby",
        "action": "cutaway revealing the note path",
        "camera": "macro dolly in",
        "reality_type": RealityType.RECONSTRUCTED,
        "priority": ScenePriority.MEDIUM,
        "asset_type": AssetType.VIDEO,
    }
    base.update(overrides)
    return Scene(**base)


def test_project_round_trip() -> None:
    now = utcnow()
    project = Project(
        project_id="abc",
        slug="atm",
        topic="ATM은 돈을 어떻게 세는 걸까?",
        content_type="inside_object",
        created_at=now,
        updated_at=now,
    )
    project.mark_stage_completed(Stage.RESEARCH, PipelineState.RESEARCHED)

    restored = Project.model_validate(json.loads(project.model_dump_json()))
    assert restored.slug == project.slug
    assert restored.state is PipelineState.RESEARCHED
    assert restored.is_stage_completed(Stage.RESEARCH)
    assert not restored.is_stage_completed(Stage.WRITE)


def test_invalid_enum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scene(reality_type="imaginary")


def test_invalid_scene_duration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scene(duration_sec=0)
    with pytest.raises(ValidationError):
        make_scene(duration_sec=45.0)


def test_scene_requires_non_empty_visual_fields() -> None:
    with pytest.raises(ValidationError):
        make_scene(action="   ")


def test_scene_plan_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        ScenePlan(scenes=[make_scene(), make_scene(order=2)])


def test_scene_plan_rejects_unsorted_order() -> None:
    with pytest.raises(ValidationError):
        ScenePlan(scenes=[make_scene(id="S02", order=2), make_scene(id="S01", order=1)])


def test_research_rejects_duplicate_claim_ids() -> None:
    claim = Claim(id="C01", statement="a", confidence=ClaimConfidence.HIGH, source_ids=["S01"])
    with pytest.raises(ValidationError):
        ResearchResult(topic="t", summary="s", claims=[claim, claim])


def test_research_detects_dangling_sources() -> None:
    research = ResearchResult(
        topic="t",
        summary="s",
        claims=[
            Claim(id="C01", statement="a", confidence=ClaimConfidence.HIGH, source_ids=["S09"])
        ],
        sources=[SourceRef(id="S01", title="t", url="https://example.invalid/1")],
    )
    assert research.dangling_source_ids() == ["S09"]
    assert research.supported_claims()  # has a source id, even if dangling


def test_claim_without_source_is_unsupported() -> None:
    claim = Claim(id="C01", statement="a", confidence=ClaimConfidence.LOW)
    assert not claim.is_supported


def test_script_narration_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        ScriptResult(title="t", hook="h", narration="  ", target_duration_sec=58)


def test_script_collects_all_claim_ids() -> None:
    script = ScriptResult(
        title="t",
        hook="h",
        narration="n",
        target_duration_sec=58,
        referenced_claim_ids=["C01"],
        beats=[ScriptBeat(id="B01", purpose="hook", text="h", claim_ids=["C02"])],
    )
    assert script.all_claim_ids() == {"C01", "C02"}


def test_manifest_requires_contiguous_scenes() -> None:
    with pytest.raises(ValidationError):
        Manifest(
            resolution=(1080, 1920),
            fps=30,
            scenes=[
                ManifestScene(scene_id="S01", asset="a.mp4", start=0.0, duration=2.0),
                ManifestScene(scene_id="S02", asset="b.mp4", start=5.0, duration=2.0),
            ],
        )


def test_manifest_round_trip_and_total() -> None:
    manifest = Manifest(
        resolution=(1080, 1920),
        fps=30,
        scenes=[
            ManifestScene(scene_id="S01", asset="a.mp4", start=0.0, duration=2.0),
            ManifestScene(scene_id="S02", asset="b.mp4", start=2.0, duration=3.5),
        ],
        voice="audio/narration.wav",
    )
    restored = Manifest.model_validate(json.loads(manifest.model_dump_json()))
    assert restored.total_duration_sec == 5.5
    assert restored.resolution == (1080, 1920)


def test_asset_ledger_tracks_usable_scenes() -> None:
    ledger = AssetLedger()
    ledger.put(
        AssetRecord(
            scene_id="S01",
            provider="mock",
            asset_type=AssetType.VIDEO,
            status=AssetStatus.COMPLETED,
            prompt_hash="h",
            local_path="assets/S01/source.mp4",
            cost_usd=0.5,
        )
    )
    ledger.put(
        AssetRecord(
            scene_id="S02",
            provider="mock",
            asset_type=AssetType.VIDEO,
            status=AssetStatus.FAILED,
            prompt_hash="h2",
        )
    )
    assert ledger.usable_scene_ids() == {"S01"}
    assert ledger.total_cost_usd() == 0.5
