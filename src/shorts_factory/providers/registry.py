"""Build the provider set named in ``config/settings.yaml``.

Interfaces are separated from the first implementation, but only one real
provider per kind is wired up (spec section 22).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..errors import ConfigError
from .base import ImageProvider, LLMProvider, SearchProvider, TTSProvider, VideoProvider
from .image.mock import MockImageProvider
from .llm.mock import MockLLMProvider
from .llm.openai import OpenAILLMProvider
from .search.mock import MockSearchProvider
from .tts.mock import MockTTSProvider
from .tts.openai import OpenAITTSProvider
from .video.mock import MockVideoProvider
from .video.prompt_adapter import GenericPromptAdapter, VideoPromptAdapter


@dataclass(frozen=True)
class ProviderSet:
    """Live provider objects. A dataclass, not a model: these are not data."""

    llm: LLMProvider
    search: SearchProvider
    image: ImageProvider
    video: VideoProvider
    tts: TTSProvider
    prompt_adapter: VideoPromptAdapter

    def names(self) -> dict[str, str]:
        return {
            "llm": self.llm.name,
            "search": self.search.name,
            "image": self.image.name,
            "video": self.video.name,
            "tts": self.tts.name,
            "prompt_adapter": self.prompt_adapter.name,
        }


def build_llm(config: AppConfig) -> LLMProvider:
    name = config.settings.providers.llm
    llm = config.settings.llm
    if name == "mock":
        return MockLLMProvider(model="mock-llm-1")
    if name == "openai":
        return OpenAILLMProvider(
            model=llm.model,
            temperature=llm.temperature,
            max_output_tokens=llm.max_output_tokens,
            timeout_sec=llm.timeout_sec,
        )
    raise ConfigError(f"unknown llm provider '{name}'; available: mock, openai")


def build_search(config: AppConfig) -> SearchProvider:
    name = config.settings.providers.search
    if name == "mock":
        return MockSearchProvider(results_per_query=config.settings.search.max_results_per_query)
    raise ConfigError(
        f"unknown search provider '{name}'; only 'mock' is implemented. "
        "Phase 5 adds the first real search provider (docs/IMPLEMENTATION_SPEC.md section 66)."
    )


def build_image(config: AppConfig) -> ImageProvider:
    name = config.settings.providers.image
    if name == "mock":
        return MockImageProvider(model=config.settings.image.model)
    raise ConfigError(
        f"unknown image provider '{name}'; only 'mock' is implemented. "
        "Check the vendor's current docs before wiring a real one."
    )


def build_video(config: AppConfig) -> VideoProvider:
    name = config.settings.providers.video
    if name == "mock":
        return MockVideoProvider(
            model=config.settings.video.model,
            width=config.settings.output.width,
            height=config.settings.output.height,
            fps=config.settings.output.fps,
        )
    raise ConfigError(
        f"unknown video provider '{name}'; only 'mock' is implemented. "
        "Phase 7 wires exactly one real video provider "
        "(docs/IMPLEMENTATION_SPEC.md section 68); implement it against that "
        "vendor's current official documentation."
    )


def build_tts(config: AppConfig) -> TTSProvider:
    name = config.settings.providers.tts
    tts = config.settings.tts
    if name == "mock":
        return MockTTSProvider(
            model=tts.model,
            chars_per_sec=config.settings.script.chars_per_sec,
            sample_rate=tts.sample_rate,
        )
    if name == "openai":
        return OpenAITTSProvider(
            model=tts.model,
            voice=tts.voice,
            audio_format=tts.format,
        )
    raise ConfigError(f"unknown tts provider '{name}'; available: mock, openai")


def build_providers(config: AppConfig) -> ProviderSet:
    return ProviderSet(
        llm=build_llm(config),
        search=build_search(config),
        image=build_image(config),
        video=build_video(config),
        tts=build_tts(config),
        prompt_adapter=GenericPromptAdapter(config.visual_styles),
    )
