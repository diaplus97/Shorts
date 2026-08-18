"""Technical media QA via ffprobe (spec section 36.3)."""

from __future__ import annotations

from pathlib import Path

from ..config import OutputSettings
from ..errors import MediaError
from ..media import probe
from .report import QAIssue, error, warning


def check_clip(
    path: str | Path, expected_duration: float, output: OutputSettings, scene_id: str | None = None
) -> list[QAIssue]:
    target = Path(path)
    if not target.exists():
        return [error("clip_missing", f"{target} does not exist", scene_id)]
    try:
        info = probe(target)
    except MediaError as exc:
        return [error("clip_unprobeable", str(exc), scene_id)]

    issues: list[QAIssue] = []
    if not info.has_video:
        issues.append(error("clip_no_video", "no video stream", scene_id))
    if info.duration_sec <= 0:
        issues.append(error("clip_zero_duration", "duration is zero", scene_id))
    elif abs(info.duration_sec - expected_duration) > 0.25:
        issues.append(
            warning(
                "clip_duration_drift",
                f"{info.duration_sec:.3f}s vs the planned {expected_duration:.3f}s",
                scene_id,
            )
        )
    if (info.width, info.height) != output.resolution:
        issues.append(
            error(
                "clip_resolution",
                f"{info.width}x{info.height}, expected {output.width}x{output.height}",
                scene_id,
            )
        )
    if info.fps is not None and abs(info.fps - output.fps) > 0.5:
        issues.append(warning("clip_fps", f"{info.fps} fps, expected {output.fps}", scene_id))
    return issues


def check_final_video(
    path: str | Path, expected_duration: float, output: OutputSettings
) -> list[QAIssue]:
    target = Path(path)
    if not target.exists():
        return [error("output_missing", f"{target} does not exist")]
    try:
        info = probe(target)
    except MediaError as exc:
        return [error("output_unprobeable", str(exc))]

    issues: list[QAIssue] = []
    if not info.has_video:
        issues.append(error("output_no_video", "final video has no video stream"))
    if not info.has_audio:
        issues.append(error("output_no_audio", "final video has no audio stream"))
    if info.duration_sec <= 0:
        issues.append(error("output_zero_duration", "final video duration is zero"))
    elif abs(info.duration_sec - expected_duration) > 1.0:
        issues.append(
            warning(
                "output_duration_drift",
                f"{info.duration_sec:.2f}s vs the planned {expected_duration:.2f}s",
            )
        )
    if (info.width, info.height) != output.resolution:
        issues.append(
            error(
                "output_resolution",
                f"{info.width}x{info.height}, expected {output.width}x{output.height}",
            )
        )
    if info.fps is not None and abs(info.fps - output.fps) > 0.5:
        issues.append(warning("output_fps", f"{info.fps} fps, expected {output.fps}"))
    if info.width and info.height:
        ratio = info.width / info.height
        if abs(ratio - 9 / 16) > 0.01:
            issues.append(error("output_aspect", f"aspect ratio {ratio:.4f}, expected 0.5625"))
    return issues
