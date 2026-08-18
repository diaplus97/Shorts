"""Configuration loading.

Non-secret settings live in ``config/*.yaml`` and are validated into Pydantic
models so a typo fails at startup instead of half-way through a paid run.
Secrets are read from the environment only (spec section 51).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigError

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class ProviderSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: str = "mock"
    search: str = "mock"
    image: str = "mock"
    video: str = "mock"
    tts: str = "mock"

    def as_dict(self) -> dict[str, str]:
        return self.model_dump()


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "gpt-4o-mini"
    temperature: float = 0.4
    max_output_tokens: int = 8000
    timeout_sec: float = 120.0
    structured_output_retries: int = 1


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queries: int = 6
    max_results_per_query: int = 6


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_claims: int = 10


class QualitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Run the LLM fact-check prompt in addition to the structural checks.
    llm_fact_check: bool = False
    #: Refuse to render when a structural warning is present, not just an error.
    strict: bool = False


class VideoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "mock-video-1"
    aspect_ratio: str = "9:16"
    poll_interval_sec: float = 5.0
    poll_timeout_sec: float = 900.0
    max_clip_duration_sec: float = 8.0


class ImageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "mock-image-1"
    width: int = 1080
    height: int = 1920


class TTSSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "mock-tts-1"
    voice: str = "default"
    format: str = "wav"
    sample_rate: int = 24000


class ScriptSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_duration_sec: float = 58.0
    min_duration_sec: float = 45.0
    max_duration_sec: float = 70.0
    chars_per_sec: float = 6.2


class SceneSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_scenes: int = 8
    max_scenes: int = 14
    min_scene_duration_sec: float = 1.5
    max_scene_duration_sec: float = 9.0


class SubtitleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_lines: int = 2
    max_chars_per_line: int = 15
    min_cue_duration_sec: float = 0.8
    margin_v: int = 320
    margin_h: int = 60
    font_size: int = 64
    font_name: str = "Noto Sans CJK KR"
    outline: int = 4
    shadow: int = 1
    burn_in: bool = True


class OutputSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    video_preset: str = "medium"
    video_crf: int = 20
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 48000
    tail_padding_sec: float = 0.4

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.width, self.height)


class AudioSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_gain_db: float = 0.0
    bgm_gain_db: float = -18.0
    duck_ratio: float = 8.0
    duck_threshold: float = 0.05


class RetrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_max_attempts: int = 4
    provider_backoff_initial_sec: float = 2.0
    provider_backoff_max_sec: float = 30.0


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    json_file: str = "logs/pipeline.jsonl"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_root: str = "projects"
    providers: ProviderSelection = Field(default_factory=ProviderSelection)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    image: ImageSettings = Field(default_factory=ImageSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    script: ScriptSettings = Field(default_factory=ScriptSettings)
    scenes: SceneSettings = Field(default_factory=SceneSettings)
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


class ProjectBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_usd: float = 12.0


class VideoBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_scene_attempts: int = 3
    max_high_priority_scenes: int = 4


class ImageBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_scene_attempts: int = 2


class LLMBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls: int = 15


class Budgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectBudget = Field(default_factory=ProjectBudget)
    video: VideoBudget = Field(default_factory=VideoBudget)
    image: ImageBudget = Field(default_factory=ImageBudget)
    llm: LLMBudget = Field(default_factory=LLMBudget)
    #: pricing[kind][provider][metric] -> usd. Kept loose on purpose: each
    #: provider bills on a different unit and prices change often.
    pricing: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)

    def price(self, kind: str, provider: str, metric: str, default: float = 0.0) -> float:
        return float(self.pricing.get(kind, {}).get(provider, {}).get(metric, default))


class ContentTypeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    description: str = ""
    reveal_pattern: list[str] = Field(default_factory=list)
    preferred_camera: list[str] = Field(default_factory=list)
    preferred_visuals: list[str] = Field(default_factory=list)
    default_reality_type: str = "reconstructed"


class RealityTypeStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suffix: str = ""


class DefaultVisualStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_style: str = ""
    color_grade: str = ""
    motion: str = ""
    negative_constraints: list[str] = Field(default_factory=list)


class VisualStyles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: DefaultVisualStyle = Field(default_factory=DefaultVisualStyle)
    reality_type_style: dict[str, RealityTypeStyle] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Everything the pipeline needs to run, minus secrets."""

    model_config = ConfigDict(extra="forbid")

    config_dir: Path
    settings: Settings
    budgets: Budgets
    content_types: dict[str, ContentTypeConfig]
    visual_styles: VisualStyles

    def content_type(self, name: str) -> ContentTypeConfig:
        try:
            return self.content_types[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.content_types))
            raise ConfigError(f"unknown content type '{name}'; known: {known}") from exc


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing configuration file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_config(config_dir: str | Path | None = None, *, load_env: bool = True) -> AppConfig:
    """Load and validate every config file. Raises :class:`ConfigError` on problems."""
    if load_env:
        load_dotenv(override=False)
    directory = Path(config_dir or os.environ.get("SHORTS_CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    if not directory.is_dir():
        raise ConfigError(f"config directory not found: {directory}")

    try:
        settings = Settings.model_validate(_load_yaml(directory / "settings.yaml"))
        budgets = Budgets.model_validate(_load_yaml(directory / "budgets.yaml"))
        raw_types = _load_yaml(directory / "content_types.yaml")
        content_types = {
            name: ContentTypeConfig.model_validate(value) for name, value in raw_types.items()
        }
        visual_styles = VisualStyles.model_validate(_load_yaml(directory / "visual_styles.yaml"))
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError and friends
        raise ConfigError(f"invalid configuration in {directory}: {exc}") from exc

    return AppConfig(
        config_dir=directory,
        settings=settings,
        budgets=budgets,
        content_types=content_types,
        visual_styles=visual_styles,
    )


@lru_cache(maxsize=4)
def _cached_config(config_dir: str) -> AppConfig:
    return load_config(config_dir)


def get_config(config_dir: str | Path | None = None) -> AppConfig:
    """Cached variant of :func:`load_config` for CLI use."""
    directory = str(Path(config_dir or os.environ.get("SHORTS_CONFIG_DIR") or DEFAULT_CONFIG_DIR))
    return _cached_config(directory)


def secret(name: str) -> str | None:
    """Read a secret from the environment. Never logged, never persisted."""
    value = os.environ.get(name)
    return value or None
