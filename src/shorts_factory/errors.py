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


class BudgetExceededError(ShortsFactoryError):
    """A paid call was refused because it would exceed the configured budget."""


class PipelineValidationError(ShortsFactoryError):
    """Structural validation of pipeline data failed."""


class FactCheckError(ShortsFactoryError):
    """The script references facts that research does not support."""


class MediaError(ShortsFactoryError):
    """FFmpeg/ffprobe failed, or produced an unusable file."""
