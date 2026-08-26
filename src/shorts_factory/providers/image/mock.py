"""Deterministic still-image stand-in.

Renders a solid colour PNG through ffmpeg so the fallback path produces a real
file that ffprobe and the Ken Burns filter can work with.
"""

from __future__ import annotations

from pathlib import Path

from ...media.ffmpeg import run_async
from ...utils import ensure_dir, sha256_text
from ..base import ImageResult


def color_for(seed: str) -> str:
    """Stable, reasonably dark colour so white subtitles stay readable."""
    digest = sha256_text(seed)
    red = int(digest[0:2], 16) // 3 + 20
    green = int(digest[2:4], 16) // 3 + 20
    blue = int(digest[4:6], 16) // 3 + 30
    return f"0x{red:02X}{green:02X}{blue:02X}"


class MockImageProvider:
    name = "mock"
    is_mock = True

    def __init__(self, model: str = "mock-image-1") -> None:
        self.model = model

    async def generate(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        destination: str | Path,
        negative_prompt: str | None = None,
        reference_image: str | Path | None = None,
    ) -> ImageResult:
        target = Path(destination)
        ensure_dir(target.parent)
        await run_async(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color_for(prompt)}:s={width}x{height}",
                "-frames:v",
                "1",
                str(target),
            ],
            label=f"mock_image:{target.name}",
        )
        return ImageResult(path=str(target), model=self.model)
