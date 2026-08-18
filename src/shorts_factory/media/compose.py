"""Final FFmpeg composition (spec section 41).

normalize scenes -> concat -> voiceover -> bgm ducking -> subtitle -> encode
"""

from __future__ import annotations

from pathlib import Path

from ..config import AudioSettings, OutputSettings, SubtitleSettings
from ..errors import MediaError
from ..utils import atomic_write_text, ensure_dir
from .ffmpeg import escape_filter_path, has_filter, run_async
from .subtitles import force_style


def write_concat_list(clips: list[Path], path: str | Path) -> Path:
    if not clips:
        raise MediaError("cannot build a concat list from zero clips")
    lines = []
    for clip in clips:
        resolved = str(Path(clip).resolve()).replace("'", "'\\''")
        lines.append(f"file '{resolved}'")
    return atomic_write_text(path, "\n".join(lines) + "\n")


def build_audio_filter(
    *,
    voice_index: int,
    bgm_index: int | None,
    audio: AudioSettings,
    sample_rate: int,
) -> str:
    voice_chain = (
        f"[{voice_index}:a]aresample={sample_rate},aformat=channel_layouts=stereo,"
        f"volume={audio.voice_gain_db}dB"
    )
    if bgm_index is None:
        return f"{voice_chain},alimiter=limit=0.95,apad[a]"

    # Duck the music against the voice, then mix the ducked music back in.
    return (
        f"{voice_chain},asplit=2[vo_mix][vo_key];"
        f"[{bgm_index}:a]aresample={sample_rate},aformat=channel_layouts=stereo,"
        f"volume={audio.bgm_gain_db}dB[bgm];"
        f"[bgm][vo_key]sidechaincompress=threshold={audio.duck_threshold}:"
        f"ratio={audio.duck_ratio}:attack=20:release=300[bgm_ducked];"
        f"[bgm_ducked][vo_mix]amix=inputs=2:duration=longest:dropout_transition=0,"
        f"alimiter=limit=0.95,apad[a]"
    )


def build_watermark_filter(text: str, font_name: str) -> str:
    """Top-left burned-in label. Used to mark a run that is not production."""
    escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
    return (
        f"drawtext=text='{escaped}':font='{font_name}':fontsize=44:fontcolor=white@0.92"
        ":x=48:y=48:box=1:boxcolor=black@0.55:boxborderw=18"
    )


def build_video_filter(
    subtitle_path: Path | None,
    subtitles: SubtitleSettings,
    watermark: str | None = None,
    watermark_font: str = "DejaVu Sans",
) -> str:
    stages: list[str] = []
    if subtitle_path is not None and subtitles.burn_in:
        stages.append(_subtitle_filter(subtitle_path, subtitles))
    if watermark:
        stages.append(build_watermark_filter(watermark, watermark_font))
    if not stages:
        return "[0:v]null[v]"
    return "[0:v]" + ",".join(stages) + "[v]"


def _subtitle_filter(subtitle_path: Path, subtitles: SubtitleSettings) -> str:
    escaped = escape_filter_path(subtitle_path.resolve())
    if subtitle_path.suffix.lower() == ".ass":
        # The ASS file carries its own PlayRes and style; force_style here would
        # reintroduce the script-unit confusion it was written to avoid.
        return f"subtitles='{escaped}'"
    style = force_style(subtitles).replace("'", "")
    return f"subtitles='{escaped}':force_style='{style}'"


async def compose(
    *,
    clips: list[Path],
    destination: str | Path,
    total_duration_sec: float,
    work_dir: str | Path,
    output: OutputSettings,
    audio: AudioSettings,
    subtitles: SubtitleSettings,
    voice_path: str | Path | None = None,
    bgm_path: str | Path | None = None,
    subtitle_path: str | Path | None = None,
    watermark: str | None = None,
) -> Path:
    """Stitch normalised clips, audio and subtitles into the final MP4."""
    target = Path(destination)
    ensure_dir(target.parent)
    work = ensure_dir(work_dir)

    if subtitle_path is not None and subtitles.burn_in and not has_filter("subtitles"):
        raise MediaError(
            "this ffmpeg build has no 'subtitles' filter (libass); "
            "install a full ffmpeg or set subtitles.burn_in: false"
        )

    concat_list = write_concat_list(clips, work / "concat.txt")

    args: list[str] = ["-f", "concat", "-safe", "0", "-i", str(concat_list)]
    if voice_path is not None:
        args += ["-i", str(voice_path)]
    else:
        args += [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={output.audio_sample_rate}",
        ]
    voice_index = 1

    bgm_index: int | None = None
    if bgm_path is not None:
        args += ["-i", str(bgm_path)]
        bgm_index = 2

    filter_complex = ";".join(
        [
            build_video_filter(
                Path(subtitle_path) if subtitle_path else None,
                subtitles,
                watermark=watermark,
                watermark_font=subtitles.font_name,
            ),
            build_audio_filter(
                voice_index=voice_index,
                bgm_index=bgm_index,
                audio=audio,
                sample_rate=output.audio_sample_rate,
            ),
        ]
    )

    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{total_duration_sec:.3f}",
        "-c:v",
        output.video_codec,
        "-preset",
        output.video_preset,
        "-crf",
        str(output.video_crf),
        "-pix_fmt",
        output.pixel_format,
        "-r",
        str(output.fps),
        "-c:a",
        output.audio_codec,
        "-b:a",
        output.audio_bitrate,
        "-ar",
        str(output.audio_sample_rate),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(target),
    ]

    await run_async(args, label="compose")
    return target
