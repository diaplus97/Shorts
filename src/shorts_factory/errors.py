"""Normalised error hierarchy (spec section 50)."""

from __future__ import annotations


class ShortsFactoryError(Exception):
    """Base class for every error this package raises deliberately."""


class ConfigError(ShortsFactoryError):
    """Malformed or missing configuration."""


class ProviderError(ShortsFactoryError):
    """An external provider failed. Wraps transport and API-level failures."""

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ContentBlockedError(ProviderError):
    """The provider refused the prompt on content-policy grounds.

    Distinct from a transient failure because retrying costs money and will
    fail again. The scene falls back to a still image instead.
    """

    def __init__(self, message: str, *, provider: str = "", reason: str | None = None) -> None:
        super().__init__(message, provider=provider, retryable=False)
        self.reason = reason


class BudgetExceededError(ShortsFactoryError):
    """A paid call was refused because it would exceed the configured budget."""


class PipelineValidationError(ShortsFactoryError):
    """Structural validation of pipeline data failed."""


class FactCheckError(ShortsFactoryError):
    """The script references facts that research does not support."""


class MediaError(ShortsFactoryError):
    """FFmpeg/ffprobe failed, or produced an unusable file."""
