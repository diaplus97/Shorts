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


def _default_dir(name: str) -> Path:
    """Locate ``config/`` or ``prompts/``.

    An editable install finds them next to the package. A wheel install does
    not, so fall back to the working directory before giving up; ``doctor``
    prints whichever one was used, and SHORTS_CONFIG_DIR overrides both.
    """
    candidates = [Path(__file__).resolve().parents[2] / name, Path.cwd() / name]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


DEFAULT_CONFIG_DIR = _default_dir("config")


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


class AudioQualitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_mean_volume_db: float = -50.0
    max_silence_ratio: float = 0.5
    silence_threshold_db: float = -50.0
    min_silence_sec: float = 0.5


class QualitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Run the LLM fact-check prompt in addition to the structural checks.
    llm_fact_check: bool = False
    #: Refuse to render when a structural warning is present, not just an error.
    strict: bool = False
    audio: AudioQualitySettings = Field(default_factory=AudioQualitySettings)


class VideoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "mock-video-1"
    aspect_ratio: str = "9:16"
    poll_interval_sec: float = 5.0
    poll_timeout_sec: float = 900.0
    max_clip_duration_sec: float = 8.0

    # -- Veo --------------------------------------------------------------
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    #: Clip lengths the model accepts. Empty means continuous.
    allowed_durations: list[float] = Field(default_factory=list)
    sample_count: int = 1
    person_generation: str | None = None
    resolution: str | None = "1080p"
    #: Veo generates its own audio; we mix our own narration instead.
    generate_audio: bool | None = None
    timeout_sec: float = 120.0
    download_timeout_sec: float = 600.0
    #: Escape hatch for a request field this code does not know about.
    extra_parameters: dict[str, Any] = Field(default_factory=dict)


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
    pause_budget_sec: float = 6.0


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
    #: ASS colour (&HBBGGRR) used for the one stressed word in a cue.
    emphasis_colour: str = "&H0055D7FF"
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


class HookContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_create_question: bool = True
    max_seconds: float = 3.0


class ScriptContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ban_generic_nouns: bool = True
    max_generic_nouns: int = 3
    generic_nouns: list[str] = Field(default_factory=list)
    concrete_mechanism_required: bool = True


class SceneContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_change_required: bool = True
    question_answered_required: bool = True
    static_exposition_forbidden: bool = True
    shared_world_required: bool = True


class VideoContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    continuous_world_preferred: bool = True
    visual_subject_required: bool = True


class FinalContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mock_assets_allowed: bool = False
    silent_audio_allowed: bool = False


class ContentContract(BaseModel):
    """Acceptance criteria for the content itself, not for the code."""

    model_config = ConfigDict(extra="forbid")

    hook: HookContract = Field(default_factory=HookContract)
    script: ScriptContract = Field(default_factory=ScriptContract)
    scene: SceneContract = Field(default_factory=SceneContract)
    video: VideoContract = Field(default_factory=VideoContract)
    final: FinalContract = Field(default_factory=FinalContract)


class PauseTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause: int = 150
    shift: int = 250
    sentence: int = 320
    question: int = 380
    reveal: int = 450
    section: int = 550


class SpeechContract(BaseModel):
    """How narration must be broken into breaths (spec v0.3 section 19)."""

    model_config = ConfigDict(extra="forbid")

    min_unit_chars: int = 4
    max_preferred_unit_chars: int = 30
    hard_split_review_chars: int = 40
    max_information_events: int = 1
    max_consecutive_same_ending: int = 3
    min_length_variation_ratio: float = 0.25
    pauses_ms: PauseTable = Field(default_factory=PauseTable)
    clause_endings: list[str] = Field(default_factory=list)
    tracked_endings: list[str] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone_profile: dict[str, Any] = Field(default_factory=dict)
    speech: SpeechContract = Field(default_factory=SpeechContract)


class SfxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    gain_db: float | None = None


class SfxConfig(BaseModel):
    """Scene sound effects. Empty and disabled until the user supplies files."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_gain_db: float = -16.0
    vocabulary: list[str] = Field(default_factory=list)
    library: dict[str, SfxEntry] = Field(default_factory=dict)

    def entry_for(self, cue: str | None) -> SfxEntry | None:
        if not cue or cue == "none":
            return None
        return self.library.get(cue)

    def gain_for(self, entry: SfxEntry) -> float:
        return entry.gain_db if entry.gain_db is not None else self.default_gain_db


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


class Realism(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photorealistic: bool = True
    physically_plausible: bool = True


class StyleBible(BaseModel):
    """The look every scene shares, and what it must never contain."""

    model_config = ConfigDict(extra="forbid")

    genre: str = "documentary CGI"
    realism: Realism = Field(default_factory=Realism)
    palette: list[str] = Field(default_factory=list)
    camera: list[str] = Field(default_factory=list)
    lighting: list[str] = Field(default_factory=list)
    transitions: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)

    def as_prompt_fragment(self) -> str:
        parts = [self.genre]
        if self.realism.photorealistic:
            parts.append("photorealistic")
        if self.realism.physically_plausible:
            parts.append("physically plausible materials and motion")
        parts.extend(self.palette)
        parts.extend(self.camera)
        parts.extend(self.lighting)
        return ", ".join(part.strip() for part in parts if part.strip())


class VisualStyles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: StyleBible = Field(default_factory=StyleBible)
    reality_type_style: dict[str, RealityTypeStyle] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Everything the pipeline needs to run, minus secrets."""

    model_config = ConfigDict(extra="forbid")

    config_dir: Path
    settings: Settings
    budgets: Budgets
    content_types: dict[str, ContentTypeConfig]
    visual_styles: VisualStyles
    content_contract: ContentContract
    voice: VoiceConfig
    sfx: SfxConfig

    def content_type(self, name: str) -> ContentTypeConfig:
        try:
            return self.content_types[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.content_types))
            raise ConfigError(f"unknown content type '{name}'; known: {known}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """``override`` wins, recursing into mappings so a partial file works.

    Lists are replaced wholesale rather than concatenated: ``allowed_durations:
    [4, 6, 8]`` has to mean exactly that, not "append to whatever was there".
    """
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def local_override_path(path: Path) -> Path:
    """``config/settings.yaml`` -> ``config/settings.local.yaml``."""
    return path.with_suffix("").with_suffix(".local.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    """One config file, with any sibling ``*.local.yaml`` merged over it.

    The committed file stays the safe default -- mock providers, no spending --
    so a checkout runs without touching a paid API. Machine-specific choices
    (a real provider, a model id, a poll interval) go in the .local.yaml, which
    is gitignored. Without this every pull collides with local edits, and the
    usual resolution is to discard them and silently fall back to mock.
    """
    if not path.exists():
        raise ConfigError(f"missing configuration file: {path}")
    data = _read_yaml(path)
    override = local_override_path(path)
    if override.exists():
        data = _deep_merge(data, _read_yaml(override))
    return data


def active_local_overrides(directory: Path) -> list[Path]:
    """Local override files in effect, for diagnostics.

    Running against a config you cannot see in git is worth stating out loud,
    so `shorts doctor` reports these.
    """
    return sorted(directory.glob("*.local.yaml"))


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
        content_contract = ContentContract.model_validate(
            _load_yaml(directory / "content_contract.yaml")
        )
        voice = VoiceConfig.model_validate(_load_yaml(directory / "voice.yaml"))
        sfx = SfxConfig.model_validate(_load_yaml(directory / "sfx.yaml"))
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
        content_contract=content_contract,
        voice=voice,
        sfx=sfx,
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
