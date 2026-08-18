"""OpenAI text-to-speech provider.

One real TTS provider, per spec section 22. Never called by the default test
suite -- see ``assert_live_calls_allowed``.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ...errors import ProviderError
from ...utils import ensure_dir
from ..base import TTSResult, assert_live_calls_allowed, require_secret

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAITTSProvider:
    name = "openai"
    is_mock = False

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        audio_format: str = "wav",
        timeout_sec: float = 300.0,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.voice = voice
        self.audio_format = audio_format
        self.timeout_sec = timeout_sec
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def synthesize(self, text: str, destination: str | Path) -> TTSResult:
        assert_live_calls_allowed(self.name)
        api_key = require_secret("TTS_API_KEY", self.name)
        target = Path(destination)
        ensure_dir(target.parent)

        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": self.audio_format,
        }
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"OpenAI TTS timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenAI TTS transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"OpenAI TTS HTTP {response.status_code}: {response.text[:500]}",
                provider=self.name,
                retryable=retryable,
            )
        if not response.content:
            raise ProviderError("OpenAI TTS returned an empty body", provider=self.name)

        target.write_bytes(response.content)
        return TTSResult(path=str(target), model=self.model, characters=len(text))
