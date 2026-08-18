"""Audio signal analysis (spec v0.2 section 36.3).

An MP4 with a valid AAC stream can still be 55 seconds of nothing. ffprobe
cannot tell the difference, so the render gate measures the signal itself.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..config import AudioQualitySettings
from ..errors import MediaError
from ..utils import ensure_dir
from .ffmpeg import run, run_async
from .ffprobe import probe

_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB")
_MAX_VOLUME = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB")
_SILENCE_DURATION = re.compile(r"silence_duration:\s*(\d+(?:\.\d+)?)")

#: ffmpeg reports a completely silent track as -91 dB.
DIGITAL_SILENCE_DB = -90.0


class AudioAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    duration_sec: float
    has_audio: bool
    mean_volume_db: float | None = None
    max_volume_db: float | None = None
    silent_sec: float = 0.0

    @property
    def silence_ratio(self) -> float:
        if self.duration_sec <= 0:
            return 1.0
        return round(min(self.silent_sec / self.duration_sec, 1.0), 4)

    @property
    def is_digital_silence(self) -> bool:
        return self.mean_volume_db is None or self.mean_volume_db <= DIGITAL_SILENCE_DB


def analyze_audio(
    path: str | Path,
    settings: AudioQualitySettings,
    *,
    timeout: float = 300.0,
) -> AudioAnalysis:
    """Measure loudness and silence in a media file's audio track."""
    target = Path(path)
    if not target.exists():
        raise MediaError(f"cannot analyse missing audio: {target}")

    info = probe(target)
    if not info.has_audio:
        return AudioAnalysis(path=str(target), duration_sec=info.duration_sec, has_audio=False)

    stderr = run(
        [
            "-i",
            str(target),
            "-map",
            "0:a:0",
            "-af",
            (
                f"volumedetect,silencedetect=noise={settings.silence_threshold_db}dB"
                f":d={settings.min_silence_sec}"
            ),
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
        label=f"analyze_audio:{target.name}",
        loglevel="info",
    )

    mean = _MEAN_VOLUME.search(stderr)
    peak = _MAX_VOLUME.search(stderr)
    silent = sum(float(match) for match in _SILENCE_DURATION.findall(stderr))

    return AudioAnalysis(
        path=str(target),
        duration_sec=info.duration_sec,
        has_audio=True,
        mean_volume_db=float(mean.group(1)) if mean else None,
        max_volume_db=float(peak.group(1)) if peak else None,
        silent_sec=round(silent, 3),
    )


def audio_problems(analysis: AudioAnalysis, settings: AudioQualitySettings) -> list[str]:
    """Reasons this audio track must not ship. Empty means it is fine."""
    problems: list[str] = []
    if not analysis.has_audio:
        problems.append("no audio stream")
        return problems
    if analysis.duration_sec <= 0:
        problems.append("audio duration is zero")
    if analysis.is_digital_silence:
        problems.append("the audio track is silent")
        return problems
    if (
        analysis.mean_volume_db is not None
        and analysis.mean_volume_db < settings.min_mean_volume_db
    ):
        problems.append(
            f"mean volume {analysis.mean_volume_db:.1f} dB is below the "
            f"{settings.min_mean_volume_db:.1f} dB floor"
        )
    if analysis.silence_ratio > settings.max_silence_ratio:
        problems.append(
            f"{analysis.silence_ratio:.0%} of the track is silence, over the "
            f"{settings.max_silence_ratio:.0%} limit"
        )
    return problems


async def render_silence(
    destination: str | Path, duration_sec: float, *, sample_rate: int, channels: int = 1
) -> Path:
    target = Path(destination)
    ensure_dir(target.parent)
    layout = "mono" if channels == 1 else "stereo"
    await run_async(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl={layout}",
            "-t",
            f"{max(duration_sec, 0.01):.3f}",
            str(target),
        ],
        label=f"silence:{target.name}",
    )
    return target


async def concat_with_gaps(
    parts: Sequence[tuple[str | Path, float]],
    destination: str | Path,
    *,
    sample_rate: int,
    lead_silence_sec: float = 0.0,
    channels: int = 1,
) -> Path:
    """Join audio files, inserting a measured silence after each one.

    ``parts`` is ``(path, gap_after_seconds)``. This is how a SpeechPlan's
    pauses become real silence: the provider never has to support prosody
    control for the timing to come out right.
    """
    if not parts:
        raise MediaError("cannot concatenate zero audio parts")

    target = Path(destination)
    ensure_dir(target.parent)
    layout = "mono" if channels == 1 else "stereo"

    args: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    index = 0

    if lead_silence_sec > 0:
        args += [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl={layout}",
            "-t",
            f"{lead_silence_sec:.3f}",
        ]
        chains.append(f"[{index}:a]aresample={sample_rate}[a{index}]")
        labels.append(f"[a{index}]")
        index += 1

    for path, gap in parts:
        args += ["-i", str(path)]
        chain = f"[{index}:a]aresample={sample_rate},aformat=channel_layouts={layout}"
        if gap > 0:
            chain += f",apad=pad_dur={gap:.3f}"
        chains.append(f"{chain}[a{index}]")
        labels.append(f"[a{index}]")
        index += 1

    filter_complex = ";".join(chains) + ";" + "".join(labels) + f"concat=n={index}:v=0:a=1[out]"
    await run_async(
        [*args, "-filter_complex", filter_complex, "-map", "[out]", str(target)],
        label=f"concat_audio:{target.name}",
    )
    return target
