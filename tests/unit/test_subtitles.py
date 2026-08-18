"""SRT/ASS rendering and cues built from speech units (spec v0.3 sections 26-27)."""

from __future__ import annotations

import itertools

from factories import make_plan, make_scene, make_speech_plan, make_timeline, make_unit
from shorts_factory.media.subtitles import (
    format_ass_timestamp,
    format_timestamp,
    render_ass,
    render_srt,
)
from shorts_factory.stages.subtitles import build


def test_srt_timestamp_format() -> None:
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(61.5) == "00:01:01,500"
    assert format_timestamp(3661.25) == "01:01:01,250"
    assert format_timestamp(-3) == "00:00:00,000"


def test_ass_timestamp_format() -> None:
    assert format_ass_timestamp(0) == "0:00:00.00"
    assert format_ass_timestamp(61.5) == "0:01:01.50"
    assert format_ass_timestamp(3661.25) == "1:01:01.25"


def three_unit_setup():
    speech = make_speech_plan(
        [
            make_unit("U01", text="지폐를 넣으면 확인이 시작됩니다."),
            make_unit("U02", text="먼저 한 장씩 나눕니다."),
            make_unit("U03", text="그다음 센서를 지나가는데요.", pause_after_ms=0),
        ]
    )
    plan = make_plan(
        [
            make_scene(
                id="S01",
                order=1,
                speech_unit_ids=["U01", "U02"],
                narration="지폐를 넣으면 확인이 시작됩니다. 먼저 한 장씩 나눕니다.",
            ),
            make_scene(
                id="S02",
                order=2,
                speech_unit_ids=["U03"],
                narration="그다음 센서를 지나가는데요.",
                subtitle_position="top",
            ),
        ]
    )
    return speech, plan, make_timeline(speech)


def test_one_cue_per_speech_unit(context) -> None:
    speech, plan, timeline = three_unit_setup()
    cues = build(context, plan, speech, timeline)
    assert len(cues) == len(speech.units)
    assert [cue.index for cue in cues] == [1, 2, 3]


def test_cues_follow_the_measured_timeline(context) -> None:
    speech, plan, timeline = three_unit_setup()
    cues = build(context, plan, speech, timeline)
    for cue, unit in zip(cues, speech.units, strict=True):
        entry = timeline.entry_for(unit.id)
        assert cue.start == entry.start
        # The cue is held through the pause that follows it.
        assert cue.end == round(entry.end + entry.gap_after, 3)
    for previous, current in itertools.pairwise(cues):
        assert current.start >= previous.start
        assert current.start <= current.end


def test_cue_text_is_never_empty_and_fits_two_lines(context, settings) -> None:
    speech, plan, timeline = three_unit_setup()
    for cue in build(context, plan, speech, timeline):
        assert cue.text.strip()
        lines = cue.text.split("\n")
        assert len(lines) <= settings.subtitles.max_lines


def test_scene_position_carries_to_its_cues(context) -> None:
    speech, plan, timeline = three_unit_setup()
    cues = build(context, plan, speech, timeline)
    assert [cue.position for cue in cues] == ["bottom", "bottom", "top"]


def test_srt_rendering_is_well_formed(context) -> None:
    speech, plan, timeline = three_unit_setup()
    text = render_srt(build(context, plan, speech, timeline))
    assert text.startswith("1\n00:00:00,000 --> ")
    assert text.endswith("\n")


def test_ass_declares_the_output_resolution(context, settings) -> None:
    """MarginV is in output pixels only because PlayRes is declared."""
    speech, plan, timeline = three_unit_setup()
    text = render_ass(build(context, plan, speech, timeline), settings.subtitles, 1080, 1920)
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert f",{settings.subtitles.margin_v},1" in text
    assert settings.subtitles.font_name in text
    # A top-positioned cue uses the alternate style.
    assert "Style: Top," in text
    assert any(line.startswith("Dialogue:") and ",Top," in line for line in text.splitlines())
