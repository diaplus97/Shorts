"""Speech plan schema and the deterministic segmenter (spec v0.3 sections 6-12)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factories import make_speech_plan, make_unit
from shorts_factory.domain import BeatPurpose, DeliveryMode, ScriptBeat, gap_ms_before
from shorts_factory.stages.speech import build_plan, split_sentence, units_from_beat
from shorts_factory.utils import visible_length

LONG_COMPOUND = "지폐가 내부로 들어오면 롤러를 지나 센서가 특징을 확인하고 문제가 있는 경우 별도의 통로로 보내게 됩니다."


# -- schema -----------------------------------------------------------------


def test_unit_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        make_unit(text="   ")


def test_unit_rejects_an_unknown_delivery_mode() -> None:
    with pytest.raises(ValidationError):
        make_unit(delivery="shouting")


def test_unit_rejects_an_absurd_pause() -> None:
    with pytest.raises(ValidationError):
        make_unit(pause_after_ms=9000)
    with pytest.raises(ValidationError):
        make_unit(pause_before_ms=-1)


def test_plan_rejects_duplicate_unit_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate speech unit ids"):
        make_speech_plan([make_unit("U01"), make_unit("U01", text="다른 문장입니다.")])


def test_adjacent_pauses_do_not_stack() -> None:
    """A gap is one silence, not the sum of two opinions about it."""
    units = [make_unit("U01", pause_after_ms=300), make_unit("U02", pause_before_ms=500)]
    assert gap_ms_before(units, 1) == 500
    assert gap_ms_before(units, 0) == 0


def test_plan_totals_its_pauses() -> None:
    plan = make_speech_plan(
        [
            make_unit("U01", pause_after_ms=300),
            make_unit("U02", pause_after_ms=500),
            make_unit("U03", pause_after_ms=0),
        ]
    )
    assert plan.total_pause_sec == pytest.approx(0.8)


# -- segmentation -----------------------------------------------------------


def test_a_short_sentence_is_left_alone(settings, config) -> None:
    contract = config.voice.speech
    text = "고무 롤러가 맨 앞 지폐만 살짝 끌어당깁니다."
    assert split_sentence(text, contract) == [text]


def test_a_long_compound_sentence_is_split(config) -> None:
    contract = config.voice.speech
    units = split_sentence(LONG_COMPOUND, contract)
    assert len(units) > 1
    assert all(visible_length(unit) <= contract.hard_split_review_chars for unit in units)
    # Nothing is lost or reordered.
    assert "".join(units).replace(" ", "") == LONG_COMPOUND.replace(" ", "")


def test_splitting_never_leaves_a_runt(config) -> None:
    contract = config.voice.speech
    for unit in split_sentence(LONG_COMPOUND, contract):
        assert visible_length(unit) >= contract.min_unit_chars


def test_a_beat_becomes_units_with_delivery_and_pauses(config, context) -> None:
    beat = ScriptBeat(
        id="B02",
        purpose=BeatPurpose.REVEAL,
        text="지폐를 넣으면 안에서는 바로 확인이 시작됩니다. 그런데 뭉치 그대로는 셀 수 없죠.",
        claim_ids=["C01"],
        visualizable=True,
        visual_payoff="외장이 열린다",
    )
    units = units_from_beat(beat, config.voice.speech, start_index=1)

    assert len(units) == 2
    assert [unit.id for unit in units] == ["U01", "U02"]
    assert all(unit.delivery is DeliveryMode.REVEAL for unit in units)
    assert all(unit.beat_id == "B02" for unit in units)
    assert all(unit.referenced_claim_ids == ["C01"] for unit in units)
    # A sentence break inside the beat is shorter than the break that ends it.
    assert units[0].pause_after_ms < units[-1].pause_after_ms


def test_a_question_gets_its_own_pause(config) -> None:
    beat = ScriptBeat(
        id="B05",
        purpose=BeatPurpose.PROCESS,
        text="그럼 문제가 있는 지폐는 어떻게 될까요? 갈림길에서 따로 빠져나갑니다.",
        visualizable=True,
        visual_payoff="갈림길",
    )
    units = units_from_beat(beat, config.voice.speech, start_index=1)
    assert units[0].text.endswith("?")
    assert units[0].pause_after_ms == config.voice.speech.pauses_ms.question


def test_build_plan_covers_the_whole_script(context) -> None:
    from factories import make_script

    script = make_script()
    plan = build_plan(script, context)
    assert plan.units
    assert plan.tone_profile.persona
    # The last unit has nothing to pause for.
    assert plan.units[-1].pause_after_ms == 0
    joined = " ".join(unit.text for unit in plan.units).replace(" ", "")
    assert joined == script.narration.replace(" ", "")


def test_estimated_duration_includes_the_pauses(context) -> None:
    from factories import make_script

    plan = build_plan(make_script(), context)
    spoken_only = sum(len(unit.text.replace(" ", "")) for unit in plan.units) / 6.2
    assert plan.estimated_duration_sec > spoken_only
