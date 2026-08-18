"""FFmpeg-backed media processing. Nothing here knows about the pipeline."""

from .audio import (
    AudioAnalysis,
    analyze_audio,
    audio_problems,
    concat_with_gaps,
    render_silence,
)
from .compose import compose, write_concat_list
from .ffmpeg import ffmpeg_path, ffprobe_path, has_filter, is_available, run, run_async, version
from .ffprobe import MediaInfo, probe
from .normalize import normalize_image, normalize_video
from .subtitles import (
    SubtitleCue,
    SubtitleSegment,
    build_cues,
    format_ass_timestamp,
    format_timestamp,
    render_ass,
    render_srt,
    write_ass,
    write_srt,
)

__all__ = [
    "AudioAnalysis",
    "MediaInfo",
    "SubtitleCue",
    "SubtitleSegment",
    "analyze_audio",
    "audio_problems",
    "build_cues",
    "compose",
    "concat_with_gaps",
    "ffmpeg_path",
    "ffprobe_path",
    "format_ass_timestamp",
    "format_timestamp",
    "has_filter",
    "is_available",
    "normalize_image",
    "normalize_video",
    "probe",
    "render_ass",
    "render_silence",
    "render_srt",
    "run",
    "run_async",
    "version",
    "write_ass",
    "write_concat_list",
    "write_srt",
]
