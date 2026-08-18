"""SRT and ASS generation (spec section 40)."""

from __future__ import annotations

import itertools

from shorts_factory.media.subtitles import (
    build_cues,
    format_ass_timestamp,
    format_timestamp,
    render_ass,
    render_srt,
)


def test_srt_timestamp_format() -> None:
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(61.5) == "00:01:01,500"
    assert format_timestamp(3661.25) == "01:01:01,250"
    assert format_timestamp(-3) == "00:00:00,000"


def test_ass_timestamp_format() -> None:
    assert format_ass_timestamp(0) == "0:00:00.00"
    assert format_ass_timestamp(61.5) == "0:01:01.50"
    assert format_ass_timestamp(3661.25) == "1:01:01.25"


def test_cues_cover_each_segment_without_gaps(settings) -> None:
    segments = [
        ("첫 번째 장면의 내레이션입니다. 두 번째 문장도 있습니다.", 0.0, 6.0),
        ("세 번째 장면입니다.", 6.0, 3.0),
    ]
    cues = build_cues(segments, settings.subtitles)
    assert cues
    assert cues[0].start == 0.0
    assert abs(cues[-1].end - 9.0) < 0.01
    for previous, current in itertools.pairwise(cues):
        assert abs(current.start - previous.end) < 0.01


def test_cues_respect_the_line_budget(settings) -> None:
    long_text = "센서가 대상의 존재와 위치를 감지하고 제어부가 신호를 밀리초 단위로 대조한다."
    cues = build_cues([(long_text, 0.0, 8.0)], settings.subtitles)
    for cue in cues:
        lines = cue.text.split("\n")
        assert len(lines) <= settings.subtitles.max_lines
        assert all(len(line) <= settings.subtitles.max_chars_per_line + 2 for line in lines)


def test_empty_and_zero_length_segments_are_dropped(settings) -> None:
    assert (
        build_cues([("", 0.0, 3.0), ("   ", 3.0, 2.0), ("x", 5.0, 0.0)], settings.subtitles) == []
    )


def test_srt_rendering_is_well_formed(settings) -> None:
    cues = build_cues([("짧은 문장입니다.", 0.0, 2.0)], settings.subtitles)
    text = render_srt(cues)
    assert text.startswith("1\n00:00:00,000 --> ")
    assert text.endswith("\n")


def test_ass_declares_the_output_resolution(settings) -> None:
    """MarginV is in output pixels only because PlayRes is declared."""
    long_line = "센서가 대상의 존재와 위치를 감지하고 신호를 대조한다."
    cues = build_cues([(long_line, 0.0, 4.0)], settings.subtitles)
    text = render_ass(cues, settings.subtitles, 1080, 1920)
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    # Margins belong to the style line, in output pixels.
    assert f",{settings.subtitles.margin_v},1" in text
    assert settings.subtitles.font_name in text
    assert text.count("Dialogue:") == len(cues)
    dialogue_lines = [line for line in text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == len(cues)
    # A wrapped cue stays on one physical line and uses the ASS break escape.
    assert any("\\N" in line for line in dialogue_lines)
