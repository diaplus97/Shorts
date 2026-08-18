"""Deterministic video stand-in with a realistic async job lifecycle.

Real video APIs are submit -> poll -> download (spec section 23), so the mock
is too: it forces the pipeline to exercise the same code path it will use
against a paid provider, including deliberate failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...errors import ProviderError
from ...media.ffmpeg import run_async
from ...utils import ensure_dir, sha256_text
from ..base import VideoJobState, VideoResult
from ..image.mock import color_for


@dataclass
class _Job:
    job_id: str
    prompt: str
    duration_sec: float
    polls: int = 0
    failed: bool = False
    error: str | None = None


@dataclass
class MockVideoProvider:
    """A fake async video generator.

    ``fail_prompt_substrings`` makes specific scenes fail on demand, which is
    how the retry and image-fallback tests drive the failure path.
    """

    name: str = "mock"
    model: str = "mock-video-1"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    #: Number of `status()` calls that report "processing" before completion.
    processing_polls: int = 1
    fail_prompt_substrings: tuple[str, ...] = ()
    _jobs: dict[str, _Job] = field(default_factory=dict, repr=False)

    async def submit(
        self,
        *,
        prompt: str,
        duration_sec: float,
        aspect_ratio: str,
        negative_prompt: str | None = None,
    ) -> str:
        job_id = "mockjob_" + sha256_text(f"{prompt}|{duration_sec}|{aspect_ratio}")[:16]
        should_fail = any(token in prompt for token in self.fail_prompt_substrings)
        # A resubmitted job id must be able to fail again, so overwrite.
        self._jobs[job_id] = _Job(
            job_id=job_id,
            prompt=prompt,
            duration_sec=duration_sec,
            failed=should_fail,
            error="mock provider was told to fail this prompt" if should_fail else None,
        )
        return job_id

    async def status(self, job_id: str) -> VideoJobState:
        job = self._jobs.get(job_id)
        if job is None:
            raise ProviderError(f"unknown mock job {job_id}", provider=self.name)
        job.polls += 1
        if job.failed:
            return VideoJobState(job_id=job_id, state="failed", error=job.error)
        if job.polls <= self.processing_polls:
            return VideoJobState(
                job_id=job_id,
                state="processing",
                progress=round(job.polls / (self.processing_polls + 1), 2),
            )
        return VideoJobState(job_id=job_id, state="completed", progress=1.0)

    async def download(self, job_id: str, destination: str | Path) -> VideoResult:
        job = self._jobs.get(job_id)
        if job is None:
            raise ProviderError(f"unknown mock job {job_id}", provider=self.name)
        if job.failed:
            raise ProviderError(f"mock job {job_id} failed: {job.error}", provider=self.name)
        target = Path(destination)
        ensure_dir(target.parent)
        await run_async(
            [
                "-f",
                "lavfi",
                "-i",
                (
                    f"color=c={color_for(job.prompt)}:s={self.width}x{self.height}"
                    f":r={self.fps}:d={job.duration_sec:.3f}"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(target),
            ],
            label=f"mock_video:{target.name}",
        )
        return VideoResult(path=str(target), model=self.model, duration_sec=job.duration_sec)
