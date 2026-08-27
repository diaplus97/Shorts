"""TTS providers."""

from .mock import MockTTSProvider
from .openai import OpenAITTSProvider
from .speech_adapter import SpeechSegment, as_single_text, lead_silence_sec, segments_for

__all__ = [
    "MockTTSProvider",
    "OpenAITTSProvider",
    "SpeechSegment",
    "as_single_text",
    "lead_silence_sec",
    "segments_for",
]
