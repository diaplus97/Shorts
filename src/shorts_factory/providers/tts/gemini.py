"""Text to speech over the Gemini API.

    POST models/{model}:generateContent  with responseModalities: ["AUDIO"]
    ->  inlineData.data, base64 raw PCM

The one detail that matters more than the endpoint: **Gemini returns headerless
PCM, not a container.** Writing those bytes to a .wav produces a file ffprobe
reports as having no streams, which the audio QA would then flag as silence --
a confusing way to find out. This wraps them in a RIFF header, so what lands on
disk is a real WAV.

The sample rate is not in the response either. It comes from config and has to
match what the model actually returns, or the voice plays at the wrong pitch
while every duration check still passes. Gemini's TTS models document 24 kHz,
16-bit, mono.

**Verified against the live API**, with one caveat that is not a bug here: the
read was judged too slow and the voice wrong, which is what ``tts.speed`` and
``scripts/audition_voices.py`` exist for. Model ids move; run
``scripts/list_gemini_models.py --kind tts`` to see what this key can reach.
"""

from __future__ import annotations

import base64
import binascii
import struct
from pathlib import Path
from typing import Any

import httpx

from ...errors import ProviderError
from ...utils import ensure_dir, get_logger
from ..base import (
    TTSResult,
    assert_live_calls_allowed,
    is_retryable_429,
    require_secret,
)

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiTTSProvider:
    name = "gemini"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        voice: str = "Kore",
        base_url: str = DEFAULT_BASE_URL,
        sample_rate: int = 24000,
        style_instruction: str = "",
        timeout_sec: float = 300.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.voice = voice
        self.base_url = base_url.rstrip("/")
        self.sample_rate = sample_rate
        self.style_instruction = style_instruction
        self.timeout_sec = timeout_sec
        self._client = client

    async def synthesize(self, text: str, destination: str | Path) -> TTSResult:
        assert_live_calls_allowed(self.name)
        target = Path(destination)
        ensure_dir(target.parent)

        # Gemini TTS takes delivery direction as part of the prompt rather than
        # as a parameter, which is how the tone profile reaches it.
        spoken = f"{self.style_instruction.strip()}\n\n{text}" if self.style_instruction else text

        body = await self._request(
            f"{self.base_url}/models/{self.model}:generateContent",
            {
                "contents": [{"parts": [{"text": spoken}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}
                    },
                },
            },
        )

        payload = find_audio_payload(body)
        if payload is None:
            raise ProviderError(
                f"Gemini TTS returned no audio: {str(body)[:300]}", provider=self.name
            )
        try:
            pcm = base64.b64decode(payload)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError(
                f"Gemini TTS returned audio that is not valid base64: {exc}", provider=self.name
            ) from exc
        if not pcm:
            raise ProviderError("Gemini TTS returned an empty audio payload", provider=self.name)

        target.write_bytes(wav_from_pcm(pcm, sample_rate=self.sample_rate))
        return TTSResult(path=str(target), model=self.model, characters=len(text))

    async def _request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = require_secret("TTS_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Gemini TTS timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Gemini TTS transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini TTS HTTP {response.status_code}: {response.text[:400]}",
                provider=self.name,
                retryable=(response.status_code == 429 and is_retryable_429(response.text))
                or response.status_code >= 500,
            )
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"Gemini TTS returned non-JSON: {response.text[:300]}", provider=self.name
            ) from exc


def wav_from_pcm(
    pcm: bytes, *, sample_rate: int, channels: int = 1, bits_per_sample: int = 16
) -> bytes:
    """A RIFF/WAVE header in front of raw samples.

    Gemini hands back headerless PCM. Saved straight to a .wav that is a file
    with no readable stream -- ffprobe reports no audio, and the silence check
    downstream then blames the voice rather than the container.
    """
    block_align = channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    header = b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVEfmt ",
            struct.pack(
                "<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample
            ),
            b"data",
            struct.pack("<I", len(pcm)),
        )
    )
    return header + pcm


def find_audio_payload(node: Any) -> str | None:
    """The base64 audio, wherever ``inlineData`` sits in the response."""
    if isinstance(node, dict):
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict):
            data = inline.get("data")
            if isinstance(data, str) and data:
                return data
        for value in node.values():
            if (found := find_audio_payload(value)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := find_audio_payload(item)) is not None:
                return found
    return None
