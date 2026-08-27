"""The two edit-level requests: point at the part, and read at a chosen pace.

Both were reported the same way -- "the video is correct and I still cannot
follow it" -- and both are fixed by things that never reach a provider, so they
are testable without spending anything.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.factories import make_scene, make_scenes, make_script

from shorts_factory.config import HighlightStyle, OutputSettings
from shorts_factory.domain import HighlightSpec
from shorts_factory.media import HighlightBox, atempo_chain, highlight_filter
from shorts_factory.quality import check_scene_plan
from shorts_factory.stages.composition import clip_recipe

# -- the box ----------------------------------------------------------------


def test_a_box_is_placed_in_pixels_from_fractions_of_the_frame() -> None:
    chain = highlight_filter(
        HighlightBox(x=0.25, y=0.5, width=0.5, height=0.1),
        output=OutputSettings(),
        duration_sec=4.0,
        style=HighlightStyle(),
    )
    # 1080x1920: a quarter across is 270, half down is 960.
    assert "x=270" in chain
    assert "y=960" in chain
    assert "w=540" in chain


def test_a_box_covering_the_whole_shot_is_not_gated_on_time() -> None:
    """``enable`` costs a per-frame expression evaluation for no gain here."""
    chain = highlight_filter(
        HighlightBox(x=0.1, y=0.1, width=0.2, height=0.2),
        output=OutputSettings(),
        duration_sec=4.0,
        style=HighlightStyle(),
    )
    assert "enable=" not in chain


def test_a_timed_box_is_gated_to_its_own_window() -> None:
    chain = highlight_filter(
        HighlightBox(x=0.1, y=0.1, width=0.2, height=0.2, start_sec=1.5, duration_sec=1.0),
        output=OutputSettings(),
        duration_sec=4.0,
        style=HighlightStyle(),
    )
    assert "enable='between(t,1.500,2.500)'" in chain


def test_an_open_ended_box_runs_to_the_end_of_the_shot() -> None:
    chain = highlight_filter(
        HighlightBox(x=0.1, y=0.1, width=0.2, height=0.2, start_sec=1.5),
        output=OutputSettings(),
        duration_sec=4.0,
        style=HighlightStyle(),
    )
    assert "enable='between(t,1.500,4.000)'" in chain


def test_a_box_may_not_be_scheduled_past_the_end_of_its_shot() -> None:
    with pytest.raises(ValidationError, match="highlight starts at"):
        make_scene(
            duration_sec=3.0,
            highlight=HighlightSpec(x=0.1, y=0.1, width=0.2, height=0.2, start_sec=5.0),
        )


@pytest.mark.parametrize(
    ("x", "width"),
    [(0.8, 0.5), (0.0, 1.5)],
)
def test_a_box_may_not_run_off_the_frame(x: float, width: float) -> None:
    with pytest.raises(ValidationError):
        HighlightSpec(x=x, y=0.1, width=width, height=0.2)


def _boxed(plan, count: int):
    """The same plan with the first ``count`` scenes carrying a highlight."""
    box = HighlightSpec(x=0.1, y=0.1, width=0.2, height=0.2)
    scenes = [
        scene.model_copy(update={"highlight": box if index < count else None})
        for index, scene in enumerate(plan.scenes)
    ]
    return plan.model_copy(update={"scenes": scenes})


def test_boxing_most_of_the_shots_is_flagged(settings, budgets) -> None:
    """A box on every shot is a border, and a border emphasises nothing."""
    narration = "가" * 300
    script = make_script(narration=narration, hook=narration[:20])
    plan = make_scenes(10, narration)

    codes = {i.code for i in check_scene_plan(_boxed(plan, 8), script, settings, budgets)}
    assert "scene_highlight_overuse" in codes

    codes = {i.code for i in check_scene_plan(_boxed(plan, 3), script, settings, budgets)}
    assert "scene_highlight_overuse" not in codes


# -- the pace ---------------------------------------------------------------


def test_a_pace_ffmpeg_can_do_in_one_stage_uses_one() -> None:
    assert atempo_chain(1.15) == "atempo=1.150000"


def test_no_change_still_produces_a_valid_filter() -> None:
    assert atempo_chain(1.0) == "atempo=1.000000"


@pytest.mark.parametrize("speed", [0.25, 3.0, 4.5, 0.5, 2.0])
def test_every_stage_of_a_chain_stays_inside_what_atempo_accepts(speed: float) -> None:
    """``atempo`` rejects a factor outside 0.5-2.0 rather than clamping it."""
    factors = [float(part.split("=")[1]) for part in atempo_chain(speed).split(",")]
    assert all(0.5 <= factor <= 2.0 for factor in factors)
    product = 1.0
    for factor in factors:
        product *= factor
    assert product == pytest.approx(speed, rel=1e-6)


def test_a_pace_of_zero_is_refused() -> None:
    with pytest.raises(Exception, match="positive"):
        atempo_chain(0.0)


# -- clip reuse -------------------------------------------------------------


def test_adding_a_box_invalidates_a_cached_clip() -> None:
    """Duration alone used to decide reuse, and a box does not change duration."""
    from pathlib import Path

    source = Path("assets/S01/raw.mp4")
    style = HighlightStyle()
    plain = clip_recipe(source, 4.0, None, style)
    boxed = clip_recipe(source, 4.0, HighlightBox(x=0.1, y=0.1, width=0.2, height=0.2), style)
    assert plain != boxed


def test_regenerating_the_source_invalidates_a_cached_clip() -> None:
    from pathlib import Path

    style = HighlightStyle()
    first = clip_recipe(Path("assets/S01/veo.mp4"), 4.0, None, style)
    second = clip_recipe(Path("assets/S01/still.png"), 4.0, None, style)
    assert first != second
