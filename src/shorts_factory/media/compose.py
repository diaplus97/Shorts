"""Final FFmpeg composition (spec section 41).

normalize scenes -> concat -> voiceover -> bgm ducking -> sfx -> subtitle -> encode
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..config import AudioSettings, OutputSettings, SubtitleSettings
from ..errors import MediaError
from ..utils import atomic_write_text, ensure_dir, get_logger
from .ffmpeg import escape_filter_path, has_filter, run_async
from .subtitles import force_style

log = get_logger(__name__)


def write_concat_list(clips: list[Path], path: str | Path) -> Path:
    if not clips:
        raise MediaError("cannot build a concat list from zero clips")
    lines = []
    for clip in clips:
        resolved = str(Path(clip).resolve()).replace("'", "'\\''")
        lines.append(f"file '{resolved}'")
    return atomic_write_text(path, "\n".join(lines) + "\n")


class SfxPlacement(BaseModel):
    """One sound effect, dropped in at a scene boundary."""

    model_config = ConfigDict(extra="forbid")

    path: str
    start_sec: float = 0.0
    gain_db: float = -16.0
    cue: str | None = None


def build_audio_filter(
    *,
    voice_index: int,
    bgm_index: int | None,
    sfx_indexes: list[tuple[int, SfxPlacement]] | None = None,
    audio: AudioSettings,
    sample_rate: int,
) -> str:
    """Voice, optionally ducked music, and any scene sound effects.

    ``amix`` is told ``normalize=0`` so adding a quiet effect does not pull the
    narration down with it; the limiter afterwards catches any peak.
    """
    common = f"aresample={sample_rate},aformat=channel_layouts=stereo"
    chains: list[str] = []
    mix_labels: list[str] = []

    voice_chain = f"[{voice_index}:a]{common},volume={audio.voice_gain_db}dB"
    if bgm_index is None:
        chains.append(f"{voice_chain}[voice]")
        mix_labels.append("[voice]")
    else:
        # Duck the music against the voice, then mix the ducked music back in.
        chains.append(f"{voice_chain},asplit=2[voice][vo_key]")
        chains.append(f"[{bgm_index}:a]{common},volume={audio.bgm_gain_db}dB[bgm]")
        chains.append(
            f"[bgm][vo_key]sidechaincompress=threshold={audio.duck_threshold}:"
            f"ratio={audio.duck_ratio}:attack=20:release=300[bgm_ducked]"
        )
        mix_labels.extend(["[voice]", "[bgm_ducked]"])

    for index, placement in sfx_indexes or []:
        label = f"sfx{index}"
        delay_ms = max(round(placement.start_sec * 1000), 0)
        chain = f"[{index}:a]{common},volume={placement.gain_db}dB"
        if delay_ms:
            chain += f",adelay={delay_ms}:all=1"
        chains.append(f"{chain}[{label}]")
        mix_labels.append(f"[{label}]")

    tail = "alimiter=limit=0.95,apad[a]"
    if len(mix_labels) == 1:
        return f"{';'.join(chains)};{mix_labels[0]}{tail}"
    mix = (
        f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest"
        ":dropout_transition=0:normalize=0,"
    )
    return f"{';'.join(chains)};{mix}{tail}"


def build_watermark_filter(text: str, font_name: str, *, can_draw_text: bool | None = None) -> str:
    """Burned-in mark saying this render is not production.

    ``drawtext`` needs ffmpeg built with libfreetype, and common static builds
    ship without it -- the johnvansickle 7.0.2 binary fails with "No such
    filter: 'drawtext'". Losing the mark entirely is the wrong answer: the
    whole reason it exists is that a preview must never pass for a real Short.
    So without drawtext it degrades to a bar of colour, which needs no font,
    rather than to nothing.
    """
    if can_draw_text is None:
        can_draw_text = has_filter("drawtext")
    if can_draw_text:
        escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
        return (
            f"drawtext=text='{escaped}':font='{font_name}':fontsize=44:fontcolor=white@0.92"
            ":x=48:y=48:box=1:boxcolor=black@0.55:boxborderw=18"
        )
    log.warning(
        "watermark_text_unavailable",
        detail="this ffmpeg has no 'drawtext' filter (needs libfreetype); "
        "marking the preview with a magenta border instead",
    )
    # Unmissable, and impossible to confuse with a finished Short.
    return "drawbox=x=0:y=0:w=iw:h=ih:color=magenta@0.9:t=24"


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
    sfx: list[SfxPlacement] | None = None,
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
    next_index = 2
    if bgm_path is not None:
        args += ["-i", str(bgm_path)]
        bgm_index = next_index
        next_index += 1

    sfx_indexes: list[tuple[int, SfxPlacement]] = []
    for placement in sfx or []:
        args += ["-i", placement.path]
        sfx_indexes.append((next_index, placement))
        next_index += 1

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
                sfx_indexes=sfx_indexes,
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
