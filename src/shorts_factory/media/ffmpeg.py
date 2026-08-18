"""Thin wrapper around the ffmpeg binary.

A wrapper, not a framework: the spec prefers calling ffmpeg directly over
depending on a Python video library (spec section 6).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from ..errors import MediaError
from ..utils import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT_SEC = 900.0


def ffmpeg_path() -> str:
    override = os.environ.get("SHORTS_FFMPEG")
    if override:
        return override
    found = shutil.which("ffmpeg")
    if not found:
        raise MediaError("ffmpeg not found on PATH; install ffmpeg or set SHORTS_FFMPEG")
    return found


def ffprobe_path() -> str:
    override = os.environ.get("SHORTS_FFPROBE")
    if override:
        return override
    found = shutil.which("ffprobe")
    if not found:
        raise MediaError("ffprobe not found on PATH; install ffmpeg or set SHORTS_FFPROBE")
    return found


def is_available() -> bool:
    try:
        ffmpeg_path()
        ffprobe_path()
    except MediaError:
        return False
    return True


def version() -> str:
    result = subprocess.run(
        [ffmpeg_path(), "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def has_filter(name: str) -> bool:
    """Whether this ffmpeg build exposes a given filter (e.g. ``subtitles``)."""
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    return any(line.split()[1:2] == [name] for line in result.stdout.splitlines() if line.strip())


def run(args: list[str], *, timeout: float = DEFAULT_TIMEOUT_SEC, label: str = "ffmpeg") -> str:
    """Run ffmpeg synchronously. Returns stderr (where ffmpeg writes its report)."""
    command = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg_run", label=label, args=args)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{label}: ffmpeg timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise MediaError(f"{label}: ffmpeg failed ({result.returncode})\n{result.stderr[-2000:]}")
    return result.stderr


async def run_async(
    args: list[str], *, timeout: float = DEFAULT_TIMEOUT_SEC, label: str = "ffmpeg"
) -> str:
    command = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg_run_async", label=label, args=args)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise MediaError(f"{label}: ffmpeg timed out after {timeout}s") from exc
    if process.returncode != 0:
        text = stderr.decode("utf-8", "replace")
        raise MediaError(f"{label}: ffmpeg failed ({process.returncode})\n{text[-2000:]}")
    return stderr.decode("utf-8", "replace")


def escape_filter_path(path: str | Path) -> str:
    """Escape a path for use inside an ffmpeg filtergraph argument."""
    text = str(path)
    # Inside a single-quoted filter argument only these three need escaping.
    for char in ("\\", ":", "'"):
        text = text.replace(char, f"\\{char}")
    return text
