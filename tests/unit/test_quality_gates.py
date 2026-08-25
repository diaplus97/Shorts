"""Structural QA, fact traceability and the content quality contract."""

from __future__ import annotations

from factories import (
    make_claim,
    make_research,
    make_scenes,
    make_script,
    make_source,
)
from shorts_factory.domain import (
    AssetLedger,
    AssetRecord,
    AssetStatus,
    AssetType,
    BeatPurpose,
    ScenePriority,
    ScriptBeat,
)
from shorts_factory.quality import (
    affected_scenes,
    check_assets,
    check_generic_nouns,
    check_hook,
    check_research,
    check_scene_contract,
    check_scene_plan,
    check_script,
    check_script_contract,
    check_script_traceability,
    fact_lock_issues,
)

NARRATION = "가" * 300


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def script_with(text: str, **overrides) -> object:
    """A single-beat script whose narration is exactly `text`."""
    beat = ScriptBeat(
        id="B01",
        purpose=BeatPurpose.HOOK,
        text=text,
        visualizable=True,
        visual_payoff="카메라가 다가간다",
    )
    return make_script(hook=text, narration=text, beats=[beat], **overrides)


# -- script structure -------------------------------------------------------


def test_script_duration_window(settings) -> None:
    assert "script_duration" in codes(check_script(make_script(narration_chars=100), settings))
    assert "script_duration" not in codes(check_script(make_script(narration_chars=320), settings))


def test_banned_intro_and_hype_are_errors(settings) -> None:
    intro = "안녕하세요 " + "가" * 295
    assert "script_intro" in codes(check_script(script_with(intro), settings))

    hype = "여러분은 평생 속고 있었습니다 " + "가" * 285
    assert "script_hype" in codes(check_script(script_with(hype), settings))


def test_narration_must_equal_the_joined_beats(settings) -> None:
    script = make_script(
        beats=[ScriptBeat(id="B01", purpose=BeatPurpose.HOOK, text="다른 문장입니다.")]
    )
    assert "script_narration_mismatch" in codes(check_script(script, settings))


# -- fact traceability ------------------------------------------------------


def test_unsourced_claim_may_not_reach_the_script() -> None:
    research = make_research(claims=[make_claim(source_ids=[])])
    assert "script_unsourced_claim" in codes(check_script_traceability(make_script(), research))


def test_unknown_claim_reference_is_an_error() -> None:
    research = make_research(claims=[make_claim("C02")])
    assert "script_unknown_claim" in codes(check_script_traceability(make_script(), research))


def test_fact_lock_passes_for_a_sourced_script() -> None:
    issues = fact_lock_issues(make_script(), make_research())
    assert [issue for issue in issues if issue.level == "error"] == []


def test_research_without_sources_fails() -> None:
    research = make_research(claims=[], sources=[])
    assert {"research_empty", "research_no_supported_claims"} <= codes(check_research(research))


def test_dangling_source_reference_is_an_error() -> None:
    research = make_research(claims=[make_claim(source_ids=["S99"])], sources=[make_source()])
    assert "research_dangling_sources" in codes(check_research(research))


# -- scene plan -------------------------------------------------------------


def test_scene_count_window(settings, budgets) -> None:
    script = make_script(narration=NARRATION, hook=NARRATION[:20])
    too_few = make_scenes(3, NARRATION, total=12.0)
    assert "scene_count" in codes(check_scene_plan(too_few, script, settings, budgets))

    ok = make_scenes(10, NARRATION)
    assert "scene_count" not in codes(check_scene_plan(ok, script, settings, budgets))


def test_scene_narration_must_cover_the_script(settings, budgets) -> None:
    script = make_script(narration=NARRATION, hook=NARRATION[:20])
    plan = make_scenes(10, "다" * 300)
    assert "scene_narration_coverage" in codes(check_scene_plan(plan, script, settings, budgets))


def test_high_priority_budget_is_enforced(settings, budgets) -> None:
    script = make_script(narration=NARRATION, hook=NARRATION[:20])
    plan = make_scenes(10, NARRATION)
    plan = plan.model_copy(
        update={
            "scenes": [s.model_copy(update={"priority": ScenePriority.HIGH}) for s in plan.scenes]
        }
    )
    assert "scene_priority_budget" in codes(check_scene_plan(plan, script, settings, budgets))


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
    assert {"asset_fallback", "asset_missing"} <= codes(check_assets(plan, ledger))


def test_affected_scenes_traces_a_claim() -> None:
    plan = make_scenes(3, "가" * 30, total=9.0)
    assert affected_scenes(plan, "C01") == ["S01", "S02", "S03"]
    assert affected_scenes(plan, "C99") == []


# -- content quality contract ----------------------------------------------


def test_hook_must_pose_a_question(config, settings) -> None:
    contract = config.content_contract
    flat = make_script(hook="ATM 안에는 롤러가 있습니다.")
    assert "hook_no_question" in codes(check_hook(flat, contract, settings.script))

    asked = make_script(hook="ATM은 지폐를 어떻게 셀까요?")
    assert "hook_no_question" not in codes(check_hook(asked, contract, settings.script))


def test_hook_must_fit_three_seconds(config, settings) -> None:
    long_hook = "ATM에 지폐를 여러 장 넣었을 때 이 기계가 각각을 어떻게 구분하는지 생각해 보신 적 있으신가요?"
    issues = check_hook(make_script(hook=long_hook), config.content_contract, settings.script)
    assert "hook_too_long" in codes(issues)


def test_generic_nouns_are_capped(config) -> None:
    vague = "센서가 대상의 위치를 확인합니다. 이 장치의 과정은 구간마다 다릅니다. 시스템이 기준값을 비교합니다."
    assert "script_generic_nouns" in codes(
        check_generic_nouns(script_with(vague), config.content_contract)
    )
    concrete = "고무 롤러가 지폐를 한 장씩 끌어당깁니다. 센서가 무늬와 크기를 읽습니다."
    assert check_generic_nouns(script_with(concrete), config.content_contract) == []


def test_a_script_with_nothing_to_show_is_rejected(config, settings) -> None:
    """A video that is entirely talk fails -- but one unshowable beat does not.

    This gate used to error on *any* beat marked unshowable. Applied to the
    benchmark script in tests/fixtures/benchmark/ it deletes six of nine core
    sentences: the scale, the reason the obvious answer fails, the numbers, the
    date, the closing reframe. What survived was a middle section with no
    beginning and no stakes, which is what the pipeline was producing. The rule
    is now a share, not a per-beat veto.
    """
    script = make_script(
        beats=[
            ScriptBeat(id="B01", purpose=BeatPurpose.HOOK, text="ATM은 어떻게 셀까요?"),
            ScriptBeat(
                id="B02",
                purpose=BeatPurpose.PROCESS,
                text="여러 단계가 순서대로 움직입니다.",
                claim_ids=["C01"],
                visualizable=False,
            ),
        ],
        narration="ATM은 어떻게 셀까요? 여러 단계가 순서대로 움직입니다.",
        hook="ATM은 어떻게 셀까요?",
    )
    issues = check_script_contract(
        script, make_research(), config.content_contract, settings.script
    )
    assert "script_mostly_unshowable" in codes(issues)


def test_one_unshowable_beat_among_several_is_allowed(config, settings) -> None:
    """Context and consequence rarely have a single shot, and belong anyway."""
    beats = [
        ScriptBeat(id="B01", purpose=BeatPurpose.HOOK, text="ATM은 어떻게 셀까요?"),
        ScriptBeat(
            id="B02",
            purpose=BeatPurpose.PROCESS,
            text="1976년부터 쓰인 방식입니다.",
            claim_ids=["C01"],
            visualizable=False,
        ),
        ScriptBeat(
            id="B03",
            purpose=BeatPurpose.PROCESS,
            text="고무 롤러가 지폐를 한 장씩 끌어당깁니다.",
            claim_ids=["C02"],
            visualizable=True,
            visual_payoff="롤러가 맨 앞 지폐를 분리한다",
        ),
        ScriptBeat(
            id="B04",
            purpose=BeatPurpose.PROCESS,
            text="센서가 무늬와 크기를 읽습니다.",
            claim_ids=["C03"],
            visualizable=True,
            visual_payoff="지폐가 센서 창을 지난다",
        ),
    ]
    script = make_script(
        beats=beats,
        narration=" ".join(beat.text for beat in beats),
        hook=beats[0].text,
    )
    issues = check_script_contract(
        script, make_research(), config.content_contract, settings.script
    )
    assert "script_mostly_unshowable" not in codes(issues)


def test_a_beat_claiming_a_shot_must_say_what_it_is(config, settings) -> None:
    """Marked showable with an empty visual_payoff is the field being skipped."""
    script = make_script(
        beats=[
            ScriptBeat(id="B01", purpose=BeatPurpose.HOOK, text="ATM은 어떻게 셀까요?"),
            ScriptBeat(
                id="B02",
                purpose=BeatPurpose.PROCESS,
                text="고무 롤러가 지폐를 끌어당깁니다.",
                claim_ids=["C01"],
                visualizable=True,
            ),
        ],
        narration="ATM은 어떻게 셀까요? 고무 롤러가 지폐를 끌어당깁니다.",
        hook="ATM은 어떻게 셀까요?",
    )
    issues = check_script_contract(
        script, make_research(), config.content_contract, settings.script
    )
    assert "beat_no_visual_payoff" in codes(issues)


def test_a_scene_with_no_visible_change_is_rejected(config) -> None:
    plan = make_scenes(2, "가" * 40, total=8.0)
    plan = plan.model_copy(
        update={
            "scenes": [
                plan.scenes[0].model_copy(update={"visible_change": "ATM 내부입니다"}),
                plan.scenes[1],
            ]
        }
    )
    assert "scene_static_exposition" in codes(check_scene_contract(plan, config.content_contract))


def test_a_scene_plan_with_no_world_is_rejected(config) -> None:
    plan = make_scenes(2, "가" * 40, total=8.0)
    plan = plan.model_copy(update={"world": plan.world.model_copy(update={"machine_id": " "})})
    assert "plan_no_world" in codes(check_scene_contract(plan, config.content_contract))
