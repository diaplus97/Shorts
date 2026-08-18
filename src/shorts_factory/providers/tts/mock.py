"""Deterministic TTS stand-in.

Produces a real WAV whose length matches what the narration would actually take
to speak, so scene timing, subtitle timing and the final mux are all exercised.
"""

from __future__ import annotations

from pathlib import Path

from ...media.ffmpeg import run_async
from ...utils import ensure_dir, visible_length
from ..base import TTSResult


class MockTTSProvider:
    name = "mock"
    is_mock = True

    def __init__(
        self,
        *,
        model: str = "mock-tts-1",
        chars_per_sec: float = 6.2,
        sample_rate: int = 24000,
    ) -> None:
        self.model = model
        self.chars_per_sec = chars_per_sec
        self.sample_rate = sample_rate

    def estimate_duration_sec(self, text: str) -> float:
        return max(round(visible_length(text) / self.chars_per_sec, 3), 1.0)

    async def synthesize(self, text: str, destination: str | Path) -> TTSResult:
        target = Path(destination)
        ensure_dir(target.parent)
        duration = self.estimate_duration_sec(text)
        # A quiet low tone rather than silence: audible in review, and it proves
        # the mix, the limiter and the ducking chain actually ran.
        await run_async(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=180:sample_rate={self.sample_rate}:duration={duration:.3f}",
                "-af",
                "volume=-18dB",
                "-ac",
                "1",
                str(target),
            ],
            label=f"mock_tts:{target.name}",
        )
        return TTSResult(path=str(target), model=self.model, characters=len(text))
