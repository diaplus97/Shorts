"""Turn a raw generated asset into a canonical clip.

Every scene clip leaves this module with identical codec parameters, which is
what lets the concat demuxer stitch them without re-encoding twice.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..config import HighlightStyle, OutputSettings
from ..errors import MediaError
from ..utils import ensure_dir
from .ffmpeg import run_async
from .ffprobe import probe

#: Ken Burns variants, cycled by scene order so consecutive stills differ.
_MOTIONS = ("zoom_in", "zoom_out", "pan_right", "pan_left")


class HighlightBox(BaseModel):
    """A rectangle to outline on one clip, in frame fractions.

    The media layer keeps its own shape here for the same reason it keeps
    ``SfxPlacement``: nothing under ``media/`` imports the domain models, so a
    scene schema change cannot reach down and break the renderer. The
    composition stage translates a ``Scene.highlight`` into one of these.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float
    height: float
    start_sec: float = 0.0
    duration_sec: float | None = None


def _encode_args(output: OutputSettings) -> list[str]:
    return [
        "-an",
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
        "-video_track_timescale",
        "90000",
        "-movflags",
        "+faststart",
    ]


def _fit_filter(output: OutputSettings) -> str:
    width, height = output.resolution
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={output.fps},format={output.pixel_format}"
    )


def highlight_filter(
    box: HighlightBox,
    *,
    output: OutputSettings,
    duration_sec: float,
    style: HighlightStyle,
) -> str:
    """A ``drawbox`` outline over the part of the shot being talked about.

    ``drawbox`` is used rather than ``drawtext`` deliberately: it needs no font
    and no libfreetype, so it works on the stripped static ffmpeg builds that
    cannot render text at all. The label on a HighlightSpec is therefore review
    material, not something that reaches the screen.

    The box is drawn on the clip rather than at composition time because the
    coordinates belong to one shot, and by composition every shot has been
    concatenated into one stream where they would mean nothing.
    """
    width, height = output.resolution
    x = round(box.x * width)
    y = round(box.y * height)
    w = max(round(box.width * width), style.thickness * 2)
    h = max(round(box.height * height), style.thickness * 2)

    start = max(box.start_sec, 0.0)
    end = duration_sec if box.duration_sec is None else min(start + box.duration_sec, duration_sec)
    drawn = f"drawbox=x={x}:y={y}:w={w}:h={h}:color={style.colour}:t={style.thickness}"
    if start <= 0 and end >= duration_sec:
        return drawn
    # An always-on box is a frame, not a pointer. Timing it to the sentence that
    # names the part is the whole reason it reads as an explanation.
    return f"{drawn}:enable='between(t,{start:.3f},{end:.3f})'"


async def normalize_video(
    source: str | Path,
    destination: str | Path,
    *,
    duration_sec: float,
    output: OutputSettings,
    highlight: HighlightBox | None = None,
    highlight_style: HighlightStyle | None = None,
) -> Path:
    """Crop/scale a generated clip to the output spec and to an exact duration.

    Clips shorter than ``duration_sec`` are extended by holding the last frame,
    which is far less objectionable than a hard cut to black.
    """
    target = Path(destination)
    ensure_dir(target.parent)
    filters = f"{_fit_filter(output)},tpad=stop_mode=clone:stop_duration={duration_sec:.3f}"
    if highlight is not None:
        filters += "," + highlight_filter(
            highlight,
            output=output,
            duration_sec=duration_sec,
            style=highlight_style or HighlightStyle(),
        )
    await run_async(
        [
            "-i",
            str(source),
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            filters,
            *_encode_args(output),
            str(target),
        ],
        label=f"normalize_video:{Path(source).name}",
    )
    _assert_duration(target, duration_sec)
    return target


async def normalize_image(
    source: str | Path,
    destination: str | Path,
    *,
    duration_sec: float,
    output: OutputSettings,
    motion_index: int = 0,
    static: bool = False,
    highlight: HighlightBox | None = None,
    highlight_style: HighlightStyle | None = None,
) -> Path:
    """Render a still into a moving clip (the video-generation fallback).

    Spec section 27: a failed video scene becomes image + camera motion rather
    than a hole in the edit.
    """
    target = Path(destination)
    ensure_dir(target.parent)
    width, height = output.resolution
    motion = "static" if static else _MOTIONS[motion_index % len(_MOTIONS)]
    frames = max(round(duration_sec * output.fps), 1)

    # Oversample so the zoom crop still has real pixels to show.
    prescale = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2}"
    )
    if motion == "static":
        zoom, x_expr, y_expr = ("1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
    elif motion == "zoom_in":
        zoom, x_expr, y_expr = (
            "min(1+0.00060*on,1.12)",
            "iw/2-(iw/zoom/2)",
            "ih/2-(ih/zoom/2)",
        )
    elif motion == "zoom_out":
        zoom, x_expr, y_expr = (
            "max(1.12-0.00060*on,1.0)",
            "iw/2-(iw/zoom/2)",
            "ih/2-(ih/zoom/2)",
        )
    elif motion == "pan_right":
        zoom, x_expr, y_expr = (
            "1.10",
            f"(iw-iw/zoom)*min(on/{frames},1)",
            "ih/2-(ih/zoom/2)",
        )
    else:  # pan_left
        zoom, x_expr, y_expr = (
            "1.10",
            f"(iw-iw/zoom)*(1-min(on/{frames},1))",
            "ih/2-(ih/zoom/2)",
        )

    filters = (
        f"{prescale},"
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={output.fps},"
        f"setsar=1,format={output.pixel_format}"
    )
    if highlight is not None:
        # After zoompan, not before: the box is placed in output-frame
        # coordinates, and a Ken Burns move would otherwise drag it off target.
        filters += "," + highlight_filter(
            highlight,
            output=output,
            duration_sec=duration_sec,
            style=highlight_style or HighlightStyle(),
        )
    await run_async(
        [
            "-loop",
            "1",
            "-framerate",
            str(output.fps),
            "-i",
            str(source),
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            filters,
            *_encode_args(output),
            str(target),
        ],
        label=f"normalize_image:{Path(source).name}",
    )
    _assert_duration(target, duration_sec)
    return target


def _assert_duration(path: Path, expected: float, tolerance: float = 0.25) -> None:
    info = probe(path)
    if info.duration_sec <= 0:
        raise MediaError(f"{path} has zero duration after normalisation")
    if abs(info.duration_sec - expected) > tolerance:
        raise MediaError(f"{path} is {info.duration_sec:.3f}s but {expected:.3f}s was requested")
