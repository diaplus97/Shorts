"""Shared fixtures.

The default suite must never touch a paid API (spec section 56), so live calls
are blocked for every test unless it opts in with the ``live`` marker.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shorts_factory.config import AppConfig, load_config
from shorts_factory.cost import BudgetGuard, CostTracker
from shorts_factory.domain import ContentType
from shorts_factory.pipeline import ProjectWorkspace, build_context, create_project
from shorts_factory.providers import build_providers
from shorts_factory.utils import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


def pytest_configure(config: pytest.Config) -> None:
    configure_logging("WARNING", force=True)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip ffmpeg-dependent tests when ffmpeg is not installed.

    Tests only declare `@pytest.mark.media`; whether it can run is decided here,
    so `pytest -m "not media"` also works on a machine that does have ffmpeg.
    """
    from shorts_factory.media import is_available

    if is_available():
        return
    skip = pytest.mark.skip(reason="ffmpeg/ffprobe not installed")
    for item in items:
        if item.get_closest_marker("media"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _block_live_api(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("SHORTS_BLOCK_LIVE_API", "1")
    monkeypatch.delenv("ALLOW_LIVE_API_TESTS", raising=False)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    """The real shipped config, pointed at a temporary project root."""
    cfg = load_config(CONFIG_DIR, load_env=False)
    cfg.settings.project_root = str(tmp_path / "projects")
    # Mock jobs complete immediately; do not make tests wait on the real cadence.
    cfg.settings.video.poll_interval_sec = 0.001
    cfg.settings.video.poll_timeout_sec = 5.0
    return cfg


@pytest.fixture
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture
def settings(config: AppConfig):
    return config.settings


@pytest.fixture
def budgets(config: AppConfig):
    return config.budgets


@pytest.fixture
def project_and_workspace(config: AppConfig):
    return create_project(
        topic="ATM은 돈을 어떻게 세는 걸까?",
        content_type=ContentType.INSIDE_OBJECT,
        config=config,
    )


@pytest.fixture
def context(config: AppConfig, project_and_workspace):
    project, workspace = project_and_workspace
    return build_context(
        config=config,
        project=project,
        workspace=workspace,
        providers=build_providers(config),
    )


@pytest.fixture
def tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(tmp_path / "costs.jsonl")


@pytest.fixture
def guard(config: AppConfig, tracker: CostTracker) -> BudgetGuard:
    return BudgetGuard(config.budgets, tracker)


@pytest.fixture
def ffmpeg_available() -> bool:
    from shorts_factory.media import is_available

    return is_available()


def requires_media() -> pytest.MarkDecorator:
    from shorts_factory.media import is_available

    return pytest.mark.skipif(not is_available(), reason="ffmpeg/ffprobe not installed")


def has_env(name: str) -> bool:
    return bool(os.environ.get(name))


__all__ = ["CONFIG_DIR", "REPO_ROOT", "ProjectWorkspace", "has_env", "requires_media"]
