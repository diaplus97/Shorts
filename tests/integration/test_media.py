"""Media layer against real ffmpeg (spec section 55, media tests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts_factory.errors import MediaError
from shorts_factory.media import (
    compose,
    is_available,
    normalize_image,
    normalize_video,
    probe,
    write_concat_list,
)
from shorts_factory.media.compose import build_audio_filter, build_video_filter
from shorts_factory.media.ffmpeg import run_async

pytestmark = pytest.mark.skipif(not is_available(), reason="ffmpeg/ffprobe not installed")


async def make_clip(path: Path, duration: float, size: str = "640x360") -> Path:
    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x203040:s={size}:r=25:d={duration}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        label="test_clip",
    )
    return path


async def make_still(path: Path, size: str = "800x600") -> Path:
    await run_async(
        ["-f", "lavfi", "-i", f"color=c=0x404020:s={size}", "-frames:v", "1", str(path)],
        label="test_still",
    )
    return path


async def make_tone(path: Path, duration: float) -> Path:
    await run_async(
        ["-f", "lavfi", "-i", f"sine=frequency=200:duration={duration}", "-ac", "1", str(path)],
        label="test_tone",
    )
    return path


async def test_normalize_video_crops_to_vertical_and_exact_duration(tmp_path, settings) -> None:
    source = await make_clip(tmp_path / "src.mp4", 3.0, size="1920x1080")
    out = await normalize_video(
        source, tmp_path / "out.mp4", duration_sec=2.5, output=settings.output
    )
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.fps == pytest.approx(30, abs=0.5)
    assert info.duration_sec == pytest.approx(2.5, abs=0.1)
    assert not info.has_audio


async def test_normalize_video_extends_a_short_source(tmp_path, settings) -> None:
    """A 2s clip must fill a 4s slot rather than cut to black."""
    source = await make_clip(tmp_path / "short.mp4", 2.0)
    out = await normalize_video(
        source, tmp_path / "long.mp4", duration_sec=4.0, output=settings.output
    )
    assert probe(out).duration_sec == pytest.approx(4.0, abs=0.15)


async def test_normalize_image_produces_motion(tmp_path, settings) -> None:
    still = await make_still(tmp_path / "still.png")
    out = await normalize_image(
        still, tmp_path / "ken.mp4", duration_sec=3.0, output=settings.output, motion_index=0
    )
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration_sec == pytest.approx(3.0, abs=0.15)


async def test_normalize_image_static_variant(tmp_path, settings) -> None:
    still = await make_still(tmp_path / "still.png")
    out = await normalize_image(
        still, tmp_path / "static.mp4", duration_sec=2.0, output=settings.output, static=True
    )
    assert probe(out).duration_sec == pytest.approx(2.0, abs=0.15)


async def test_compose_concatenates_and_mixes(tmp_path, settings) -> None:
    clips = []
    for index, duration in enumerate((2.0, 3.0)):
        source = await make_clip(tmp_path / f"s{index}.mp4", duration)
        clips.append(
            await normalize_video(
                source, tmp_path / f"n{index}.mp4", duration_sec=duration, output=settings.output
            )
        )
    voice = await make_tone(tmp_path / "voice.wav", 4.6)
    srt = tmp_path / "subs.ass"
    srt.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, Alignment, MarginV\n"
        "Style: Default,DejaVu Sans,64,2,320\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:04.00,Default,,0,0,0,,HELLO\n",
        encoding="utf-8",
    )

    out = await compose(
        clips=clips,
        destination=tmp_path / "final.mp4",
        total_duration_sec=5.0,
        work_dir=tmp_path / "work",
        output=settings.output,
        audio=settings.audio,
        subtitles=settings.subtitles,
        voice_path=voice,
        subtitle_path=srt,
    )
    info = probe(out)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration_sec == pytest.approx(5.0, abs=0.2)


async def test_compose_without_voice_still_has_an_audio_stream(tmp_path, settings) -> None:
    source = await make_clip(tmp_path / "s.mp4", 2.0)
    clip = await normalize_video(
        source, tmp_path / "n.mp4", duration_sec=2.0, output=settings.output
    )
    out = await compose(
        clips=[clip],
        destination=tmp_path / "silent.mp4",
        total_duration_sec=2.0,
        work_dir=tmp_path / "work",
        output=settings.output,
        audio=settings.audio,
        subtitles=settings.subtitles,
    )
    assert probe(out).has_audio


def test_concat_list_quotes_awkward_paths(tmp_path) -> None:
    weird = tmp_path / "it's a clip.mp4"
    weird.write_bytes(b"")
    listing = write_concat_list([weird], tmp_path / "concat.txt")
    assert "'\\''" in listing.read_text()


def test_concat_list_rejects_an_empty_set(tmp_path) -> None:
    with pytest.raises(MediaError, match="zero clips"):
        write_concat_list([], tmp_path / "concat.txt")


def test_video_filter_skips_force_style_for_ass(tmp_path, settings) -> None:
    ass = tmp_path / "a.ass"
    srt = tmp_path / "a.srt"
    assert "force_style" not in build_video_filter(ass, settings.subtitles)
    assert "force_style" in build_video_filter(srt, settings.subtitles)
    assert build_video_filter(None, settings.subtitles) == "[0:v]null[v]"


def test_audio_filter_ducks_only_when_bgm_is_present(settings) -> None:
    plain = build_audio_filter(
        voice_index=1, bgm_index=None, audio=settings.audio, sample_rate=48000
    )
    assert "sidechaincompress" not in plain
    ducked = build_audio_filter(voice_index=1, bgm_index=2, audio=settings.audio, sample_rate=48000)
    assert "sidechaincompress" in ducked
    assert "amix=inputs=2" in ducked


def test_probe_rejects_a_missing_file(tmp_path) -> None:
    with pytest.raises(MediaError, match="cannot probe"):
        probe(tmp_path / "nope.mp4")
