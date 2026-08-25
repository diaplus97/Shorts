"""Machine-specific config: ``config/<name>.local.yaml`` over ``<name>.yaml``.

The committed config stays on mock providers so a fresh checkout cannot spend
money by accident. That makes a local override the normal way to run against a
real provider, and it has to be reliable: a partial file must merge rather than
replace, a list must replace rather than append, and the fact that an override
is in effect must be visible.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from shorts_factory.config import (
    ConfigError,
    active_local_overrides,
    load_config,
    local_override_path,
)


@pytest.fixture
def config_copy(tmp_path: Path, config_dir: Path) -> Path:
    """A writable copy of the shipped config directory."""
    target = tmp_path / "config"
    shutil.copytree(config_dir, target)
    for stale in target.glob("*.local.yaml"):
        stale.unlink()
    return target


def write_override(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_without_an_override_the_committed_defaults_win(config_copy: Path) -> None:
    config = load_config(config_copy, load_env=False)
    assert config.settings.providers.video == "mock"
    assert config.settings.video.model == "mock-video-1"
    assert active_local_overrides(config_copy) == []


def test_an_override_replaces_only_the_keys_it_names(config_copy: Path) -> None:
    """The whole point: change the provider without restating the file."""
    write_override(
        config_copy,
        "settings.local.yaml",
        "providers:\n  video: veo\nvideo:\n  model: veo-3.1-fast-generate-preview\n",
    )
    config = load_config(config_copy, load_env=False)

    assert config.settings.providers.video == "veo"
    assert config.settings.video.model == "veo-3.1-fast-generate-preview"
    # Siblings under the same keys survive rather than being wiped out.
    assert config.settings.providers.llm == "mock"
    assert config.settings.video.aspect_ratio == "9:16"
    assert config.settings.output.width == 1080


def test_a_list_is_replaced_not_appended(config_copy: Path) -> None:
    """``allowed_durations: [4, 6, 8]`` has to mean exactly those three."""
    write_override(config_copy, "settings.local.yaml", "video:\n  allowed_durations: [4, 6, 8]\n")
    config = load_config(config_copy, load_env=False)
    assert config.settings.video.allowed_durations == [4.0, 6.0, 8.0]


def test_overrides_apply_to_every_config_file(config_copy: Path) -> None:
    write_override(config_copy, "budgets.local.yaml", "project:\n  max_total_usd: 3.0\n")
    config = load_config(config_copy, load_env=False)
    assert config.budgets.project.max_total_usd == 3.0


def test_an_override_is_still_validated(config_copy: Path) -> None:
    """A typo in the override must fail at startup, not mid-run."""
    write_override(
        config_copy, "settings.local.yaml", "video:\n  aspect_ratio: 42\n  nonsense: 1\n"
    )
    with pytest.raises(ConfigError):
        load_config(config_copy, load_env=False)


def test_active_overrides_are_discoverable(config_copy: Path) -> None:
    """Doctor prints these; running against invisible settings should be visible."""
    write_override(config_copy, "settings.local.yaml", "providers:\n  video: veo\n")
    write_override(config_copy, "budgets.local.yaml", "project:\n  max_total_usd: 3.0\n")
    names = [path.name for path in active_local_overrides(config_copy)]
    assert names == ["budgets.local.yaml", "settings.local.yaml"]


def test_local_override_path_naming() -> None:
    assert local_override_path(Path("config/settings.yaml")).name == "settings.local.yaml"
    assert local_override_path(Path("config/voice.yaml")).name == "voice.local.yaml"


def test_the_shipped_example_is_a_working_override(config_copy: Path, config_dir: Path) -> None:
    """The example is the first thing anyone copies; it must actually load."""
    example = config_dir / "settings.local.yaml.example"
    assert example.exists(), "config/settings.local.yaml.example is missing"
    shutil.copy(example, config_copy / "settings.local.yaml")

    config = load_config(config_copy, load_env=False)
    assert config.settings.providers.video == "veo"
    assert config.settings.video.allowed_durations == [4.0, 6.0, 8.0]
    # The example must not quietly switch on a paid LLM as well.
    assert config.settings.providers.llm == "mock"
