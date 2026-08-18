"""Structural QA, fact traceability and technical checks."""

from __future__ import annotations

from shorts_factory.domain import (
    AssetLedger,
    AssetRecord,
    AssetStatus,
    AssetType,
    Claim,
    ClaimConfidence,
    RealityType,
    ResearchResult,
    Scene,
    ScenePlan,
    ScenePriority,
    ScriptBeat,
    ScriptResult,
    SourceRef,
)
from shorts_factory.quality import (
    affected_scenes,
    check_assets,
    check_research,
    check_scene_plan,
    check_script,
    check_script_traceability,
    fact_lock_issues,
)


def research_with(*claims: Claim) -> ResearchResult:
    return ResearchResult(
        topic="t",
        summary="s",
        claims=list(claims),
        sources=[SourceRef(id="S01", title="t", url="https://example.invalid/1")],
    )


def build_script(narration_chars: int = 360, **overrides) -> ScriptResult:
    body = "가" * narration_chars
    beats = [ScriptBeat(id="B01", purpose="hook", text=body, claim_ids=["C01"])]
    base = {
        "title": "t",
        "hook": body,
        "narration": body,
        "beats": beats,
        "target_duration_sec": 58,
        "referenced_claim_ids": ["C01"],
    }
    base.update(overrides)
    return ScriptResult(**base)


def make_scenes(count: int, narration: str, total: float = 58.0) -> ScenePlan:
    per = total / count
    chunk = len(narration) // count
    scenes = []
    for index in range(count):
        start = index * chunk
        end = len(narration) if index == count - 1 else (index + 1) * chunk
        scenes.append(
            Scene(
                id=f"S{index + 1:02d}",
                order=index + 1,
                narration=narration[start:end],
                duration_sec=round(per, 3),
                purpose="process",
                visual_subject="subject",
                environment="environment",
                action="action",
                camera="camera",
                reality_type=RealityType.RECONSTRUCTED,
                priority=ScenePriority.MEDIUM,
                asset_type=AssetType.VIDEO,
                claim_ids=["C01"],
            )
        )
    return ScenePlan(scenes=scenes)


def test_script_duration_window(settings) -> None:
    too_short = build_script(narration_chars=100)
    codes = {issue.code for issue in check_script(too_short, settings)}
    assert "script_duration" in codes

    ok = build_script(narration_chars=360)
    assert "script_duration" not in {issue.code for issue in check_script(ok, settings)}


def test_banned_intro_and_hype_are_errors(settings) -> None:
    body = "안녕하세요 " + "가" * 355
    script = build_script(
        narration_chars=1,
        hook=body,
        narration=body,
        beats=[ScriptBeat(id="B01", purpose="hook", text=body)],
    )
    codes = {issue.code for issue in check_script(script, settings)}
    assert "script_intro" in codes

    hype = "여러분은 평생 속고 있었습니다 " + "가" * 340
    script2 = build_script(
        narration_chars=1,
        hook=hype,
        narration=hype,
        beats=[ScriptBeat(id="B01", purpose="hook", text=hype)],
    )
    assert "script_hype" in {issue.code for issue in check_script(script2, settings)}


def test_narration_must_equal_the_joined_beats(settings) -> None:
    script = build_script(
        beats=[ScriptBeat(id="B01", purpose="hook", text="다른 문장입니다.")],
    )
    codes = {issue.code for issue in check_script(script, settings)}
    assert "script_narration_mismatch" in codes


def test_unsourced_claim_may_not_reach_the_script() -> None:
    research = research_with(Claim(id="C01", statement="a", confidence=ClaimConfidence.HIGH))
    script = build_script()
    codes = {issue.code for issue in check_script_traceability(script, research)}
    assert "script_unsourced_claim" in codes


def test_unknown_claim_reference_is_an_error() -> None:
    research = research_with(
        Claim(id="C02", statement="a", confidence=ClaimConfidence.HIGH, source_ids=["S01"])
    )
    codes = {issue.code for issue in check_script_traceability(build_script(), research)}
    assert "script_unknown_claim" in codes


def test_fact_lock_passes_for_a_sourced_script() -> None:
    research = research_with(
        Claim(id="C01", statement="a", confidence=ClaimConfidence.HIGH, source_ids=["S01"])
    )
    issues = fact_lock_issues(build_script(), research)
    assert [issue for issue in issues if issue.level == "error"] == []


def test_research_without_sources_fails() -> None:
    research = ResearchResult(topic="t", summary="s", claims=[], sources=[])
    codes = {issue.code for issue in check_research(research)}
    assert "research_empty" in codes
    assert "research_no_supported_claims" in codes


def test_scene_count_window(settings, budgets) -> None:
    narration = "가" * 360
    script = build_script()
    too_few = make_scenes(3, narration, total=12.0)
    codes = {issue.code for issue in check_scene_plan(too_few, script, settings, budgets)}
    assert "scene_count" in codes

    ok = make_scenes(10, narration)
    codes = {issue.code for issue in check_scene_plan(ok, script, settings, budgets)}
    assert "scene_count" not in codes


def test_scene_narration_must_cover_the_script(settings, budgets) -> None:
    script = build_script()
    plan = make_scenes(10, "다" * 360)
    codes = {issue.code for issue in check_scene_plan(plan, script, settings, budgets)}
    assert "scene_narration_coverage" in codes


def test_high_priority_budget_is_enforced(settings, budgets) -> None:
    narration = "가" * 360
    plan = make_scenes(10, narration)
    plan = plan.model_copy(
        update={
            "scenes": [
                scene.model_copy(update={"priority": ScenePriority.HIGH}) for scene in plan.scenes
            ]
        }
    )
    codes = {issue.code for issue in check_scene_plan(plan, build_script(), settings, budgets)}
    assert "scene_priority_budget" in codes


def test_asset_checks_flag_missing_and_fallback() -> None:
    plan = make_scenes(2, "가" * 40, total=8.0)
    ledger = AssetLedger()
    ledger.put(
        AssetRecord(
            scene_id="S01",
            provider="mock",
            asset_type=AssetType.IMAGE_MOTION,
            status=AssetStatus.COMPLETED,
            prompt_hash="h",
            local_path="assets/S01/source.png",
            fallback_used=True,
        )
    )
    codes = {issue.code for issue in check_assets(plan, ledger)}
    assert "asset_fallback" in codes
    assert "asset_missing" in codes


def test_affected_scenes_traces_a_claim() -> None:
    plan = make_scenes(3, "가" * 30, total=9.0)
    assert affected_scenes(plan, "C01") == ["S01", "S02", "S03"]
    assert affected_scenes(plan, "C99") == []
