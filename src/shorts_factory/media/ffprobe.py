"""ffprobe-based technical inspection (spec section 36.3)."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..errors import MediaError
from .ffmpeg import ffprobe_path


class MediaInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    duration_sec: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    has_video: bool = False
    has_audio: bool = False

    @property
    def aspect_ratio(self) -> float | None:
        if not self.width or not self.height:
            return None
        return round(self.width / self.height, 4)


def _parse_fps(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        return round(float(Fraction(value)), 3)
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | Path, *, timeout: float = 60.0) -> MediaInfo:
    target = Path(path)
    if not target.exists():
        raise MediaError(f"cannot probe missing file: {target}")
    command = [
        ffprobe_path(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(target),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out on {target}") from exc
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed on {target}: {result.stderr[-1000:]}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {target}") from exc

    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration_raw = payload.get("format", {}).get("duration")
    duration = float(duration_raw) if duration_raw not in (None, "N/A") else 0.0
    if duration == 0.0 and video is not None and video.get("duration") not in (None, "N/A"):
        duration = float(video["duration"])

    return MediaInfo(
        path=str(target),
        duration_sec=round(duration, 3),
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        has_video=video is not None,
        has_audio=audio is not None,
    )
