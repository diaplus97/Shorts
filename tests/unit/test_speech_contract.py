"""Spoken-delivery contract checks (spec v0.3 sections 18-21, 31)."""

from __future__ import annotations

from factories import make_plan, make_scene, make_speech_plan, make_unit
from shorts_factory.quality import (
    check_ending_repetition,
    check_rhythm,
    check_scene_speech_alignment,
    check_speech_plan,
    check_unit_lengths,
)


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_unit_length_bands(config) -> None:
    """31-40 characters is worth a look; over 40 should have been split."""
    contract = config.voice.speech
    borderline = "지폐가 내부로 들어오면 롤러를 지나 센서가 특징을 확인하고 별도의 통로로 갑니다."
    too_long = borderline + " 그리고 나머지는 카세트에 차곡차곡 쌓이게 됩니다."

    assert "speech_unit_long" in codes(
        check_unit_lengths(make_speech_plan([make_unit(text=borderline)]), contract)
    )
    assert "speech_unit_too_long" in codes(
        check_unit_lengths(make_speech_plan([make_unit(text=too_long)]), contract)
    )


def test_a_comfortable_unit_is_not_flagged(config) -> None:
    plan = make_speech_plan([make_unit(text="고무 롤러가 한 장씩 떼어냅니다.")])
    assert check_unit_lengths(plan, config.voice.speech) == []


def test_chained_events_in_one_breath_are_flagged(config) -> None:
    plan = make_speech_plan(
        [make_unit(text="지폐가 들어오고 그다음 센서를 지나고 그리고 카세트에 쌓입니다.")]
    )
    assert "speech_unit_multiple_events" in codes(check_speech_plan(plan, config.voice.speech))


def test_repeated_endings_are_flagged(config) -> None:
    plan = make_speech_plan(
        [make_unit(f"U{i:02d}", text=f"지폐가 {'매우 ' * (i % 3)}이동합니다.") for i in range(1, 7)]
    )
    assert "speech_monotone_endings" in codes(check_ending_repetition(plan, config.voice.speech))


def test_varied_endings_pass(config) -> None:
    texts = [
        "지폐를 넣으면 확인이 시작됩니다.",
        "뭉치 그대로는 셀 수 없죠.",
        "그래서 한 장씩 나눕니다.",
        "왜 굳이 나눌까요?",
        "다음 센서가 읽어야 하기 때문인데요.",
        "확인을 마치면 안쪽으로 갑니다.",
    ]
    plan = make_speech_plan(
        [make_unit(f"U{i:02d}", text=text) for i, text in enumerate(texts, start=1)]
    )
    assert check_ending_repetition(plan, config.voice.speech) == []


def test_flat_rhythm_is_flagged(config) -> None:
    plan = make_speech_plan(
        [make_unit(f"U{i:02d}", text="지폐가 이동합니다.") for i in range(1, 7)]
    )
    assert "speech_flat_rhythm" in codes(check_rhythm(plan, config.voice.speech))


def test_varied_lengths_pass(config) -> None:
    texts = [
        "지폐를 넣습니다.",
        "안에서는 바로 확인이 시작되는데요.",
        "먼저 한 장씩 나눕니다.",
        "왜일까요?",
        "여러 장이 겹치면 다음 센서가 제대로 읽지 못하기 때문입니다.",
    ]
    plan = make_speech_plan(
        [make_unit(f"U{i:02d}", text=text) for i, text in enumerate(texts, start=1)]
    )
    assert check_rhythm(plan, config.voice.speech) == []


def test_an_empty_plan_is_an_error(config) -> None:
    assert "speech_empty" in codes(check_speech_plan(make_speech_plan([]), config.voice.speech))


# -- scene alignment --------------------------------------------------------


def two_unit_plan():
    return make_speech_plan(
        [
            make_unit("U01", text="지폐를 넣으면 확인이 시작됩니다."),
            make_unit("U02", text="먼저 한 장씩 나눕니다."),
        ]
    )


def test_aligned_scenes_pass() -> None:
    speech = two_unit_plan()
    plan = make_plan(
        [
            make_scene(id="S01", order=1, speech_unit_ids=["U01"], narration=speech.units[0].text),
            make_scene(id="S02", order=2, speech_unit_ids=["U02"], narration=speech.units[1].text),
        ]
    )
    assert check_scene_speech_alignment(plan, speech) == []


def test_a_cut_through_a_unit_is_rejected() -> None:
    """Half a sentence in one scene and half in the next is the defect we exist to stop."""
    speech = two_unit_plan()
    plan = make_plan(
        [
            make_scene(id="S01", order=1, speech_unit_ids=["U01"], narration="지폐를 넣으면"),
            make_scene(id="S02", order=2, speech_unit_ids=["U02"], narration="확인이 시작됩니다."),
        ]
    )
    assert "scene_narration_mismatch" in codes(check_scene_speech_alignment(plan, speech))


def test_an_unassigned_unit_is_rejected() -> None:
    speech = two_unit_plan()
    plan = make_plan(
        [make_scene(id="S01", order=1, speech_unit_ids=["U01"], narration=speech.units[0].text)]
    )
    assert "speech_unit_unassigned" in codes(check_scene_speech_alignment(plan, speech))


def test_a_reused_unit_is_rejected() -> None:
    speech = two_unit_plan()
    text = " ".join(unit.text for unit in speech.units)
    plan = make_plan(
        [
            make_scene(id="S01", order=1, speech_unit_ids=["U01", "U02"], narration=text),
            make_scene(id="S02", order=2, speech_unit_ids=["U02"], narration=speech.units[1].text),
        ]
    )
    assert "speech_unit_reused" in codes(check_scene_speech_alignment(plan, speech))


def test_an_unknown_unit_reference_is_rejected() -> None:
    speech = two_unit_plan()
    plan = make_plan(
        [
            make_scene(
                id="S01",
                order=1,
                speech_unit_ids=["U01", "U02", "U99"],
                narration=" ".join(u.text for u in speech.units),
            )
        ]
    )
    assert "scene_unknown_speech_unit" in codes(check_scene_speech_alignment(plan, speech))


def test_out_of_order_scenes_are_rejected() -> None:
    speech = two_unit_plan()
    plan = make_plan(
        [
            make_scene(id="S01", order=1, speech_unit_ids=["U02"], narration=speech.units[1].text),
            make_scene(id="S02", order=2, speech_unit_ids=["U01"], narration=speech.units[0].text),
        ]
    )
    assert "speech_unit_out_of_order" in codes(check_scene_speech_alignment(plan, speech))
