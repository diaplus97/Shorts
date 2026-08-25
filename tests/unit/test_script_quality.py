"""The script-quality gates, driven by a corpus of scripts that should fail.

Every gate in this repository used to be exercised only against material
engineered to pass -- the one hand-written ATM scenario, and ``"가" * 300`` as
the stand-in for Korean prose. So each gate could be decorative without any
test noticing, and several were: a script whose beats ran ``hook, closing,
surprise, process, reveal`` returned zero issues, and so did a narration
written entirely in the register the owner complained about.

`tests/fixtures/scripts/` holds one script per defect. The rule here is that a
defect fixture must trip its own gate and the good script must trip none, which
makes every gate a red-to-green change rather than an opinion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shorts_factory.config import AppConfig
from shorts_factory.domain import ScriptResult
from shorts_factory.quality import (
    check_beat_arc,
    check_causal_linkage,
    check_korean_register,
)
from shorts_factory.quality.korean_register import (
    _NAMING_CLOSE,
    DEICTIC,
    LIGHT_VERB,
    hangul_ratio,
)
from shorts_factory.quality.script_arc import CAUSAL_CONNECTIVES, CAUSAL_ENDINGS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scripts"
BENCHMARK = Path(__file__).resolve().parents[1] / "fixtures" / "benchmark"


def load(name: str) -> ScriptResult:
    return ScriptResult.model_validate(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


def codes(script: ScriptResult, config: AppConfig) -> set[str]:
    contract = config.content_contract
    return {
        issue.code
        for issue in [
            *check_beat_arc(script, contract),
            *check_causal_linkage(script, contract),
            *check_korean_register(script, contract),
        ]
    }


#: Each defect and the gate that must catch it.
DEFECTS = [
    ("arc_scrambled", "script_arc_order"),
    ("arc_flat", "script_arc_missing"),
    ("translationese", "script_light_verb"),
    ("translationese", "script_nominalisation"),
    ("deictic_visual_dependent", "script_deictic_density"),
    ("deictic_visual_dependent", "script_no_causal_linkage"),
]


@pytest.mark.parametrize(("fixture", "expected"), DEFECTS)
def test_each_defect_trips_its_gate(fixture: str, expected: str, config: AppConfig) -> None:
    assert expected in codes(load(fixture), config)


def test_the_good_script_trips_nothing(config: AppConfig) -> None:
    """The gates have to be passable, or they only teach the writer to give up."""
    assert codes(load("good_atm"), config) == set()


def test_every_fixture_is_a_valid_script() -> None:
    """A corpus that does not parse tests nothing."""
    found = sorted(path.stem for path in FIXTURES.glob("*.json"))
    assert "good_atm" in found
    for name in found:
        load(name)


# -- the benchmark ---------------------------------------------------------
#
# The thresholds are measured from this script, so it is the one piece of
# material that must pass everything. If a future tightening fails it, the
# threshold is wrong, not the benchmark.


def benchmark_narration() -> str:
    return (BENCHMARK / "water_reclamation.txt").read_text("utf-8").replace("\n", " ").strip()


def test_the_benchmark_passes_the_language_gates(config: AppConfig) -> None:
    text = benchmark_narration()
    chars = len(text.replace(" ", ""))
    clause = config.content_contract.script

    assert hangul_ratio(text) >= clause.min_hangul_ratio

    deictic = len(DEICTIC.findall(_NAMING_CLOSE.sub("", text))) / chars * 100
    assert deictic <= clause.max_deictic_per_100_chars, (
        f"the benchmark scores {deictic:.2f} deictic per 100 chars, over its own limit"
    )

    causal = sum(text.count(word) for word in CAUSAL_CONNECTIVES)
    causal += len(CAUSAL_ENDINGS.findall(text))
    assert causal / chars * 100 >= clause.min_causal_per_100_chars

    assert sum(character.isdigit() for character in text) >= clause.min_numerals


def test_the_benchmark_is_far_clear_of_the_deictic_limit(config: AppConfig) -> None:
    """A limit the reference only just clears would fail good scripts too.

    The output that prompted this scored 1.92 per 100 characters against a
    benchmark of roughly 0.4, so there is an order of magnitude between them;
    the limit belongs in that gap, not next to the benchmark.
    """
    text = benchmark_narration()
    chars = len(text.replace(" ", ""))
    measured = len(DEICTIC.findall(_NAMING_CLOSE.sub("", text))) / chars * 100
    limit = config.content_contract.script.max_deictic_per_100_chars
    assert measured < limit * 0.8


# -- individual gate behaviour --------------------------------------------


def test_transition_beats_do_not_break_the_arc(config: AppConfig) -> None:
    """A transition is connective tissue and may sit anywhere."""
    script = load("good_atm")
    beats = list(script.beats)
    beats.insert(
        3,
        beats[0].model_copy(
            update={
                "id": "BT1",
                "purpose": "transition",
                "text": "그런데 여기서 문제가 하나 생깁니다.",
            }
        ),
    )
    script = script.model_copy(update={"beats": beats})
    assert not check_beat_arc(script, config.content_contract)


def test_the_arc_error_names_the_offending_beat(config: AppConfig) -> None:
    """A message the writer can act on, not 'arc out of order'."""
    issues = check_beat_arc(load("arc_scrambled"), config.content_contract)
    messages = " ".join(issue.message for issue in issues)
    assert "B02" in messages


def test_a_short_narration_is_not_measured_for_density(config: AppConfig) -> None:
    """Below 100 characters the ratios are noise, so they are not applied."""
    script = load("good_atm").model_copy(
        update={"narration": "지폐가 들어옵니다. 그것이 전부입니다.", "beats": []}
    )
    assert not check_causal_linkage(script, config.content_contract)


def test_the_closing_formula_is_not_counted_as_deictic(config: AppConfig) -> None:
    """ "이것이 물재생센터입니다" names the subject; it does not dodge naming it.

    The benchmark ends on exactly this, so counting it would fail the reference.
    """
    for closing in (
        "이것이 현금 입금기입니다.",
        "이것이 물재생센터입니다.",
        "이게 바로 서울의 물 재생 센터입니다.",
    ):
        assert not DEICTIC.findall(_NAMING_CLOSE.sub("", closing))


def test_light_verb_catches_the_reported_sentence(config: AppConfig) -> None:
    """The owner's own example, frozen so it cannot regress."""
    assert LIGHT_VERB.findall("나머지는 중력이 합니다.")
    assert LIGHT_VERB.findall("제어부가 목적지 분류를 수행합니다.")
    # A real verb must not be flagged just for having a subject.
    assert not LIGHT_VERB.findall("중력이 지폐를 아래로 끌어내립니다.")
