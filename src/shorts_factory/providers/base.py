"""Provider interfaces and shared plumbing (spec section 21).

Domain code never touches an SDK or a URL. It talks to these protocols, so
swapping a video or TTS vendor never reaches into the stages.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..config import RetrySettings
from ..errors import ProviderError
from ..utils import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------
# Result payloads
# --------------------------------------------------------------------------


class LLMUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0


class LLMJsonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any]
    model: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    raw_text: str | None = None


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    snippet: str = ""
    publisher: str | None = None
    published_at: str | None = None


class ImageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    model: str


class VideoJobState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    #: One of: submitted, processing, completed, failed
    state: str
    error: str | None = None
    progress: float | None = None


class VideoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    model: str
    duration_sec: float | None = None


class TTSResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    model: str
    characters: int


# --------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> LLMJsonResponse: ...


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]: ...


@runtime_checkable
class ImageProvider(Protocol):
    name: str
    model: str

    async def generate(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        destination: str | Path,
        negative_prompt: str | None = None,
    ) -> ImageResult: ...


@runtime_checkable
class VideoProvider(Protocol):
    name: str
    model: str

    async def submit(
        self,
        *,
        prompt: str,
        duration_sec: float,
        aspect_ratio: str,
        negative_prompt: str | None = None,
    ) -> str: ...

    async def status(self, job_id: str) -> VideoJobState: ...

    async def download(self, job_id: str, destination: str | Path) -> VideoResult: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    model: str

    async def synthesize(self, text: str, destination: str | Path) -> TTSResult: ...


# --------------------------------------------------------------------------
# Shared behaviour
# --------------------------------------------------------------------------


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


async def with_retry(operation: str, func: Any, settings: RetrySettings) -> Any:
    """Run ``func`` with exponential backoff on retryable provider errors."""
    attempt_number = 0
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(settings.provider_max_attempts),
        wait=wait_exponential(
            multiplier=settings.provider_backoff_initial_sec,
            max=settings.provider_backoff_max_sec,
        ),
        retry=retry_if_exception(is_retryable),
        reraise=True,
    ):
        with attempt:
            attempt_number += 1
            if attempt_number > 1:
                log.warning("provider_retry", operation=operation, attempt=attempt_number)
            return await func()
    raise ProviderError(f"{operation} exhausted retries")  # pragma: no cover - defensive


def assert_live_calls_allowed(provider: str) -> None:
    """Refuse real API calls from the normal test suite (spec section 56).

    ``tests/conftest.py`` sets ``SHORTS_BLOCK_LIVE_API=1``; opting back in
    requires ``ALLOW_LIVE_API_TESTS=1`` and the ``live`` pytest marker.
    """
    blocked = os.environ.get("SHORTS_BLOCK_LIVE_API") == "1" or "PYTEST_CURRENT_TEST" in os.environ
    if blocked and os.environ.get("ALLOW_LIVE_API_TESTS") != "1":
        raise ProviderError(
            f"live API call to '{provider}' blocked during tests; "
            "set ALLOW_LIVE_API_TESTS=1 and run `pytest -m live` to allow it",
            provider=provider,
        )


def require_secret(env_name: str, provider: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise ProviderError(
            f"{provider} requires {env_name}; add it to .env (see .env.example)",
            provider=provider,
        )
    return value
