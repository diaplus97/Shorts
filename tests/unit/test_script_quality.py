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
from shorts_factory.quality.content_contract import has_concrete_anchor, is_question
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


# -- the hook --------------------------------------------------------------


def test_a_causal_clause_is_not_a_question() -> None:
    """The gate matched bare "까", so any sentence with ~니까 counted as asking."""
    assert not is_question("지폐가 들어오니까 롤러가 움직입니다.")
    assert not is_question("문이 닫히니까 안전합니다.")
    assert not is_question("깨끗해진 물만 강으로 나갑니다.")


def test_real_questions_are_recognised() -> None:
    assert is_question("ATM은 돈을 어떻게 세는 걸까요?")
    assert is_question("계단은 끝에서 어디로 갈까요?")
    assert is_question("그럼 맞지 않는 건 어떻게 될까요?")


def test_a_statement_opens_the_video_if_it_is_specific_enough() -> None:
    """The benchmark's own opening is declarative, and it works.

    A rule of "must pose a question" rejects the reference material, which is
    the same mistake as requiring every sentence to be showable in one shot.
    """
    benchmark_opening = "서울에서 하루 동안 사용하고 버린 물은 네 곳의 물재생센터로 모입니다."
    assert not is_question(benchmark_opening)
    assert has_concrete_anchor(benchmark_opening)


def test_a_particle_is_not_a_quantity() -> None:
    """만 is the numeral 10,000 and also the particle "only"."""
    assert not has_concrete_anchor("깨끗해진 물만 강으로 나갑니다.")
    assert has_concrete_anchor("하루 100만 톤의 물이 이곳을 지납니다.")
    assert has_concrete_anchor("여기서는 두 가지 방식이 함께 쓰입니다.")


def test_the_benchmark_opening_fits_the_hook_budget(config: AppConfig) -> None:
    """A budget the reference cannot meet forces a generic stub question."""
    from shorts_factory.utils import estimate_duration_sec

    opening = "서울에서 하루 동안 사용하고 버린 물은 네 곳의 물재생센터로 모입니다."
    spoken = estimate_duration_sec(opening, config.settings.script.chars_per_sec)
    assert spoken <= config.content_contract.hook.max_seconds


def test_a_hook_that_is_not_the_first_beat_is_rejected(config: AppConfig, settings) -> None:
    """Checking one string and speaking another ships the unchecked one."""
    from shorts_factory.quality.content_contract import check_hook

    script = load("good_atm").model_copy(update={"hook": "완전히 다른 훅 문장일까요?"})
    codes_found = {i.code for i in check_hook(script, config.content_contract, settings.script)}
    assert "hook_not_first_beat" in codes_found


# -- visual realism --------------------------------------------------------


def test_realism_follows_the_scene_reality_type(config: AppConfig) -> None:
    """A scene the taxonomy calls a drawing must not be ordered as footage.

    "photorealistic" used to be appended to every prompt unconditionally, so
    the reality_type suffix asking for a cutaway sat in the same string as the
    instruction to make it photoreal.
    """
    styles = config.visual_styles
    observed = styles.reality_type_style["observed"]
    reconstructed = styles.reality_type_style["reconstructed"]

    assert "photorealistic" in styles.style.as_prompt_fragment(observed.realism)
    assert "photorealistic" not in styles.style.as_prompt_fragment(reconstructed.realism)


def test_no_prompt_asks_for_a_drawing_and_a_photograph_at_once(config: AppConfig) -> None:
    """The suffix and the realism flag have to agree, or the model gets both."""
    styles = config.visual_styles
    for name, entry in styles.reality_type_style.items():
        fragment = styles.style.as_prompt_fragment(entry.realism)
        combined = f"{entry.suffix} {fragment}"
        drawn = "visibly a drawing" in combined or "diagrammatic" in combined
        assert not (drawn and "photorealistic" in combined), (
            f"reality_type '{name}' asks for a drawing and a photograph in one prompt"
        )


# -- still images ----------------------------------------------------------


def make_still_scene():
    from tests.factories import make_scene

    return make_scene(
        id="S09",
        asset_type="image_motion",
        visible_change="interior transport path → the closed front panel again",
        camera_path="reverse of the opening move, pulling back out",
        action="the cutaway closes back into the intact machine",
    )


def test_a_still_is_not_ordered_with_camera_moves(config: AppConfig) -> None:
    """A frame has no camera move and no "change during the shot".

    The fallback used to receive the video prompt verbatim, so a still was
    asked for motion it cannot have -- part of why it never matched the clips
    on either side of it.
    """
    from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter

    adapter = GenericPromptAdapter(config.visual_styles)
    still = adapter.build_still_prompt(make_still_scene())

    for motion in (
        "camera:",
        "visible change during the shot",
        "physically possible camera motion",
        "physically plausible materials and motion",
    ):
        assert motion not in still, f"still prompt still asks for {motion!r}"
    assert "a single still frame" in still


def test_a_still_shows_the_state_the_shot_lands_on(config: AppConfig) -> None:
    """A still belongs at the end of the movement, where the next scene starts."""
    from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter

    adapter = GenericPromptAdapter(config.visual_styles)
    still = adapter.build_still_prompt(make_still_scene())

    assert "the moment shown: the closed front panel again" in still
    # Not the state it started from.
    assert "interior transport path →" not in still


def test_a_still_keeps_the_world_it_shares(config: AppConfig) -> None:
    """Dropping motion must not drop what makes it the same place."""
    from tests.factories import make_scenes

    from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter

    plan = make_scenes(3, "고무 롤러가 지폐를 끌어당깁니다.", total=12.0)
    adapter = GenericPromptAdapter(config.visual_styles)
    still = adapter.build_still_prompt(plan.scenes[0], plan)

    assert "same machine and location throughout" in still
    assert plan.scenes[0].environment in still


def test_a_still_is_reused_rather_than_rebought(config: AppConfig) -> None:
    """The reuse hash has to be computed from the prompt actually sent.

    The still prompt differs from the video prompt, so hashing the video one
    made every still miss the reuse check and be re-billed on each resume.
    """
    from tests.factories import make_scenes

    from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter

    plan = make_scenes(3, "고무 롤러가 지폐를 끌어당깁니다.", total=12.0)
    adapter = GenericPromptAdapter(config.visual_styles)
    scene = plan.scenes[0]

    assert adapter.build_still_prompt(scene, plan) != adapter.build_prompt(scene, plan), (
        "if these were identical the regression this guards could not happen"
    )
