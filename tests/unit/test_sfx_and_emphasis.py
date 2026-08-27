"""Scene sound effects and the one-word caption highlight (spec v0.4 appendix E)."""

from __future__ import annotations

from pathlib import Path

import pytest

from factories import make_plan, make_scene, make_speech_plan, make_timeline, make_unit
from shorts_factory.config import SfxConfig
from shorts_factory.domain import Manifest, ManifestScene
from shorts_factory.media.compose import SfxPlacement, build_audio_filter
from shorts_factory.media.subtitles import SubtitleCue, render_ass, render_srt
from shorts_factory.stages.composition import resolve_sfx
from shorts_factory.stages.subtitles import build

# -- mixing -----------------------------------------------------------------


def test_voice_only_needs_no_mixer(settings) -> None:
    chain = build_audio_filter(
        voice_index=1, bgm_index=None, audio=settings.audio, sample_rate=48000
    )
    assert "amix" not in chain
    assert chain.endswith("[a]")


def test_sfx_is_delayed_to_its_scene_and_mixed_under_the_voice(settings) -> None:
    chain = build_audio_filter(
        voice_index=1,
        bgm_index=None,
        sfx_indexes=[(2, SfxPlacement(path="a.wav", start_sec=3.5, gain_db=-14))],
        audio=settings.audio,
        sample_rate=48000,
    )
    assert "adelay=3500:all=1" in chain
    assert "volume=-14.0dB" in chain
    # normalize=0 keeps a quiet effect from pulling the narration down with it.
    assert "amix=inputs=2" in chain
    assert "normalize=0" in chain


def test_an_effect_at_zero_is_not_delayed(settings) -> None:
    chain = build_audio_filter(
        voice_index=1,
        bgm_index=None,
        sfx_indexes=[(2, SfxPlacement(path="a.wav", start_sec=0.0))],
        audio=settings.audio,
        sample_rate=48000,
    )
    assert "adelay" not in chain


def test_bgm_and_sfx_coexist(settings) -> None:
    chain = build_audio_filter(
        voice_index=1,
        bgm_index=2,
        sfx_indexes=[(3, SfxPlacement(path="a.wav", start_sec=1.0))],
        audio=settings.audio,
        sample_rate=48000,
    )
    assert "sidechaincompress" in chain  # music still ducks against the voice
    assert "amix=inputs=3" in chain


# -- cue resolution ---------------------------------------------------------


def manifest_for(plan) -> Manifest:
    cursor = 0.0
    entries = []
    for scene in plan.scenes:
        entries.append(
            ManifestScene(scene_id=scene.id, asset="a.mp4", start=round(cursor, 3), duration=4.0)
        )
        cursor += 4.0
    return Manifest(resolution=(1080, 1920), fps=30, scenes=entries)


def two_cue_plan():
    return make_plan(
        [
            make_scene(id="S01", order=1, sfx_cue="sensor_scan"),
            make_scene(id="S02", order=2, sfx_cue="none"),
        ]
    )


def test_sfx_is_off_by_default(context) -> None:
    plan = two_cue_plan()
    assert not context.config.sfx.enabled
    assert resolve_sfx(context, plan, manifest_for(plan)) == []


def test_a_cue_resolves_to_a_placed_sound(context, tmp_path: Path) -> None:
    sound = tmp_path / "scan.wav"
    sound.write_bytes(b"")
    context.config.sfx = SfxConfig.model_validate(
        {
            "enabled": True,
            "default_gain_db": -16.0,
            "library": {"sensor_scan": {"file": str(sound), "gain_db": -12.0}},
        }
    )
    plan = two_cue_plan()
    placements = resolve_sfx(context, plan, manifest_for(plan))

    assert len(placements) == 1
    assert placements[0].cue == "sensor_scan"
    assert placements[0].start_sec == 0.0
    assert placements[0].gain_db == -12.0


def test_a_cue_with_no_file_is_skipped_not_fatal(context) -> None:
    """No audio ships with this repo, so a missing sound must never fail a render."""
    context.config.sfx = SfxConfig.model_validate(
        {"enabled": True, "library": {"sensor_scan": {"file": "does/not/exist.wav"}}}
    )
    plan = two_cue_plan()
    assert resolve_sfx(context, plan, manifest_for(plan)) == []


def test_the_default_gain_applies_when_the_entry_omits_one(context, tmp_path: Path) -> None:
    sound = tmp_path / "scan.wav"
    sound.write_bytes(b"")
    context.config.sfx = SfxConfig.model_validate(
        {
            "enabled": True,
            "default_gain_db": -18.0,
            "library": {"sensor_scan": {"file": str(sound)}},
        }
    )
    plan = two_cue_plan()
    assert resolve_sfx(context, plan, manifest_for(plan))[0].gain_db == -18.0


# -- caption emphasis -------------------------------------------------------


def test_emphasis_travels_from_the_unit_to_the_cue(context) -> None:
    speech = make_speech_plan(
        [make_unit("U01", text="고무 롤러가 한 장씩 떼어냅니다.", emphasis_words=["한 장씩"])]
    )
    plan = make_plan(
        [make_scene(id="S01", order=1, speech_unit_ids=["U01"], narration=speech.units[0].text)]
    )
    cues = build(context, plan, speech, make_timeline(speech))
    assert cues[0].emphasis == "한 장씩"


def test_ass_colours_only_the_stressed_word(settings) -> None:
    cue = SubtitleCue(
        index=1, start=0, end=2, text="고무 롤러가 한 장씩 떼어냅니다.", emphasis="한 장씩"
    )
    line = next(
        line
        for line in render_ass([cue], settings.subtitles, 1080, 1920).splitlines()
        if line.startswith("Dialogue:")
    )
    assert f"{{\\c{settings.subtitles.emphasis_colour}}}한 장씩{{\\r}}" in line
    # One highlight per cue: two would be no highlight at all.
    assert line.count("\\c&H") == 1


def test_a_cue_without_emphasis_is_untouched(settings) -> None:
    cue = SubtitleCue(index=1, start=0, end=2, text="센서가 무늬를 읽습니다.")
    text = render_ass([cue], settings.subtitles, 1080, 1920)
    assert "\\c&H" not in text.split("[Events]")[1]


def test_emphasis_never_reaches_the_srt(settings) -> None:
    """SRT has no reliable styling, so the deliverable stays plain text."""
    cue = SubtitleCue(
        index=1, start=0, end=2, text="고무 롤러가 한 장씩 떼어냅니다.", emphasis="한 장씩"
    )
    assert "\\c" not in render_srt([cue])
    assert "한 장씩" in render_srt([cue])


def test_emphasis_that_is_not_in_the_text_is_ignored(settings) -> None:
    cue = SubtitleCue(index=1, start=0, end=2, text="센서가 무늬를 읽습니다.", emphasis="롤러")
    line = next(
        line
        for line in render_ass([cue], settings.subtitles, 1080, 1920).splitlines()
        if line.startswith("Dialogue:")
    )
    assert "\\c&H" not in line


@pytest.mark.media
async def test_a_mixed_render_is_louder_than_the_voice_alone(tmp_path: Path, settings) -> None:
    """End-to-end proof that the effect actually reaches the output."""
    from shorts_factory.media import analyze_audio, compose, normalize_video
    from shorts_factory.media.ffmpeg import run_async

    async def tone(path: Path, freq: int, duration: float, db: float) -> Path:
        await run_async(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={freq}:duration={duration}:sample_rate=48000",
                "-af",
                f"volume={db}dB",
                "-ac",
                "1",
                str(path),
            ],
            label="tone",
        )
        return path

    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x203040:s=320x568:r=30:d=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(tmp_path / "src.mp4"),
        ],
        label="clip",
    )
    clip = await normalize_video(
        tmp_path / "src.mp4", tmp_path / "clip.mp4", duration_sec=3.0, output=settings.output
    )
    voice = await tone(tmp_path / "voice.wav", 180, 3.0, -18)
    effect = await tone(tmp_path / "sfx.wav", 900, 0.3, -6)

    quiet = await compose(
        clips=[clip],
        destination=tmp_path / "quiet.mp4",
        total_duration_sec=3.0,
        work_dir=tmp_path / "w1",
        output=settings.output,
        audio=settings.audio,
        subtitles=settings.subtitles,
        voice_path=voice,
    )
    loud = await compose(
        clips=[clip],
        destination=tmp_path / "loud.mp4",
        total_duration_sec=3.0,
        work_dir=tmp_path / "w2",
        output=settings.output,
        audio=settings.audio,
        subtitles=settings.subtitles,
        voice_path=voice,
        sfx=[SfxPlacement(path=str(effect), start_sec=1.0, gain_db=-6)],
    )

    before = analyze_audio(quiet, settings.quality.audio)
    after = analyze_audio(loud, settings.quality.audio)
    assert after.max_volume_db > before.max_volume_db + 3
