"""Video providers and prompt adapters."""

from .mock import MockVideoProvider
from .prompt_adapter import GenericPromptAdapter, VideoPromptAdapter

__all__ = ["GenericPromptAdapter", "MockVideoProvider", "VideoPromptAdapter"]
