"""Build the provider set named in ``config/settings.yaml``.

Interfaces are separated from the first implementation, but only one real
provider per kind is wired up (spec section 22).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AppConfig
from ..errors import ConfigError
from .base import ImageProvider, LLMProvider, SearchProvider, TTSProvider, VideoProvider
from .image.gemini import GeminiImageProvider
from .image.mock import MockImageProvider
from .llm.gemini import GeminiLLMProvider
from .llm.mock import MockLLMProvider
from .llm.openai import OpenAILLMProvider
from .search.gemini import GeminiSearchProvider
from .search.mock import MockSearchProvider
from .tts.gemini import GeminiTTSProvider
from .tts.mock import MockTTSProvider
from .tts.openai import OpenAITTSProvider
from .video.mock import MockVideoProvider
from .video.prompt_adapter import GenericPromptAdapter, VideoPromptAdapter
from .video.veo import VeoVideoProvider


@dataclass(frozen=True)
class ProviderSet:
    """Live provider objects. A dataclass, not a model: these are not data."""

    llm: LLMProvider
    search: SearchProvider
    image: ImageProvider
    video: VideoProvider
    tts: TTSProvider
    prompt_adapter: VideoPromptAdapter

    def as_dict(self) -> dict[str, Any]:
        """The five generation providers, keyed by kind."""
        return {
            "llm": self.llm,
            "search": self.search,
            "image": self.image,
            "video": self.video,
            "tts": self.tts,
        }

    def names(self) -> dict[str, str]:
        names = {kind: provider.name for kind, provider in self.as_dict().items()}
        names["prompt_adapter"] = self.prompt_adapter.name
        return names

    @property
    def has_mock(self) -> bool:
        return any(provider.is_mock for provider in self.as_dict().values())

    @property
    def production_ready(self) -> bool:
        """False whenever any output would be a stand-in rather than the real thing."""
        return not self.has_mock


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
    if name == "gemini":
        return GeminiLLMProvider(
            model=llm.model,
            base_url=llm.base_url,
            temperature=llm.temperature,
            max_output_tokens=llm.max_output_tokens,
            timeout_sec=llm.timeout_sec,
        )
    raise ConfigError(
        f"unknown llm provider '{name}'; available: mock, openai, gemini. "
        "Run scripts/list_gemini_models.py --kind llm to see which models your key can use."
    )


def build_search(config: AppConfig) -> SearchProvider:
    name = config.settings.providers.search
    if name == "mock":
        return MockSearchProvider(results_per_query=config.settings.search.max_results_per_query)
    if name == "gemini":
        search = config.settings.search
        return GeminiSearchProvider(
            model=search.model,
            base_url=search.base_url,
            timeout_sec=search.timeout_sec,
            resolve_redirects=search.resolve_redirects,
        )
    raise ConfigError(
        f"unknown search provider '{name}'; known: mock, gemini. "
        "Run scripts/list_gemini_models.py to see which models your key can use."
    )


def build_image(config: AppConfig) -> ImageProvider:
    name = config.settings.providers.image
    if name == "mock":
        return MockImageProvider(model=config.settings.image.model)
    if name == "gemini":
        image = config.settings.image
        return GeminiImageProvider(
            model=image.model,
            base_url=image.base_url,
            aspect_ratio=image.aspect_ratio,
            person_generation=image.person_generation,
            extra_parameters=image.extra_parameters,
            timeout_sec=image.timeout_sec,
        )
    raise ConfigError(
        f"unknown image provider '{name}'; known: mock, gemini. "
        "Run scripts/list_gemini_models.py to see which models your key can use."
    )


#: Video model ids Google shut down on 2026-06-30. Failing here beats a 404
#: halfway through a paid run.
RETIRED_VIDEO_MODELS = {
    "veo-2.0-generate-001",
    "veo-3.0-generate-001",
    "veo-3.0-fast-generate-001",
    "veo-3.0-generate-preview",
}


def build_video(config: AppConfig) -> VideoProvider:
    name = config.settings.providers.video
    video = config.settings.video
    if name == "mock":
        return MockVideoProvider(
            model=video.model,
            width=config.settings.output.width,
            height=config.settings.output.height,
            fps=config.settings.output.fps,
        )
    if name == "veo":
        if video.model in RETIRED_VIDEO_MODELS:
            raise ConfigError(
                f"video.model '{video.model}' was shut down on 2026-06-30. "
                "Use a Veo 3.1 id such as 'veo-3.1-fast-generate-preview', and "
                "check config/budgets.yaml has a rate for it."
            )
        if not video.allowed_durations:
            raise ConfigError(
                "video.allowed_durations is empty, but Veo only returns fixed-length "
                "clips. Set it to the lengths your model accepts (e.g. [4, 6, 8]) so "
                "the cost estimate matches what you are billed."
            )
        return VeoVideoProvider(
            model=video.model,
            base_url=video.base_url,
            allowed_durations=tuple(video.allowed_durations),
            sample_count=video.sample_count,
            person_generation=video.person_generation,
            resolution=video.resolution,
            generate_audio=video.generate_audio,
            extra_parameters=video.extra_parameters,
            timeout_sec=video.timeout_sec,
            download_timeout_sec=video.download_timeout_sec,
        )
    raise ConfigError(f"unknown video provider '{name}'; available: mock, veo")


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
    if name == "gemini":
        return GeminiTTSProvider(
            model=tts.model,
            voice=tts.voice,
            base_url=tts.base_url,
            sample_rate=tts.sample_rate,
            style_instruction=tts.style_instruction,
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
