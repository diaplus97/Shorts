"""Audio signal QA (spec v0.3 section 24).

The bug this exists to stop: an MP4 with a perfectly valid AAC stream and no
sound in it, reported as a successful render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts_factory.media import is_available
from shorts_factory.media.audio import DIGITAL_SILENCE_DB, analyze_audio, audio_problems
from shorts_factory.media.ffmpeg import run_async

pytestmark = pytest.mark.media


async def make_tone(path: Path, *, db: float, duration: float = 4.0) -> Path:
    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=180:duration={duration}:sample_rate=24000",
            "-af",
            f"volume={db}dB",
            "-ac",
            "1",
            str(path),
        ],
        label="test_tone",
    )
    return path


async def make_silence(path: Path, duration: float = 4.0) -> Path:
    await run_async(
        ["-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={duration}", str(path)],
        label="test_silence",
    )
    return path


async def test_normal_audio_passes(tmp_path: Path, settings) -> None:
    path = await make_tone(tmp_path / "voice.wav", db=-12)
    analysis = analyze_audio(path, settings.quality.audio)
    assert analysis.has_audio
    assert analysis.duration_sec == pytest.approx(4.0, abs=0.2)
    assert analysis.silence_ratio == 0.0
    assert audio_problems(analysis, settings.quality.audio) == []


async def test_silent_audio_is_rejected(tmp_path: Path, settings) -> None:
    path = await make_silence(tmp_path / "silent.wav")
    analysis = analyze_audio(path, settings.quality.audio)
    assert analysis.is_digital_silence
    assert analysis.mean_volume_db <= DIGITAL_SILENCE_DB
    assert "the audio track is silent" in audio_problems(analysis, settings.quality.audio)


async def test_near_silent_audio_is_rejected(tmp_path: Path, settings) -> None:
    path = await make_tone(tmp_path / "faint.wav", db=-40)
    analysis = analyze_audio(path, settings.quality.audio)
    problems = audio_problems(analysis, settings.quality.audio)
    assert problems
    assert "below the" in problems[0]


async def test_mostly_silent_audio_is_rejected(tmp_path: Path, settings) -> None:
    """Loud enough where it plays, but silent for most of its length."""
    from shorts_factory.media import concat_with_gaps

    tone = await make_tone(tmp_path / "short.wav", db=-12, duration=1.0)
    path = await concat_with_gaps([(tone, 5.0)], tmp_path / "gappy.wav", sample_rate=24000)
    analysis = analyze_audio(path, settings.quality.audio)
    assert analysis.silence_ratio > settings.quality.audio.max_silence_ratio
    assert any("silence" in problem for problem in audio_problems(analysis, settings.quality.audio))


async def test_a_file_with_no_audio_stream_is_rejected(tmp_path: Path, settings) -> None:
    video = tmp_path / "mute.mp4"
    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        label="test_mute",
    )
    analysis = analyze_audio(video, settings.quality.audio)
    assert not analysis.has_audio
    assert audio_problems(analysis, settings.quality.audio) == ["no audio stream"]


def test_module_requires_ffmpeg() -> None:
    assert is_available()
