"""CLI surface (spec section 45)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shorts_factory.cli import app

runner = CliRunner()


@pytest.fixture
def cli_config(tmp_path: Path) -> Path:
    """A copy of the shipped config pointed at a temporary project root."""
    source = Path(__file__).resolve().parents[2] / "config"
    target = tmp_path / "config"
    shutil.copytree(source, target)
    settings = target / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace(
            "project_root: projects", f"project_root: {tmp_path / 'projects'}"
        ),
        encoding="utf-8",
    )
    return target


def invoke(cli_config: Path, *args: str):
    return runner.invoke(app, ["--config-dir", str(cli_config), *args])


def test_version(cli_config: Path) -> None:
    result = invoke(cli_config, "version")
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_help_lists_every_documented_command(cli_config: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "create",
        "research",
        "write",
        "direct",
        "generate",
        "narrate",
        "inspect",
        "render",
        "resume",
        "status",
        "doctor",
    ):
        assert command in result.stdout


def test_doctor_reports_a_healthy_environment(cli_config: Path) -> None:
    result = invoke(cli_config, "doctor")
    assert result.exit_code == 0, result.stdout
    assert "configuration loaded" in result.stdout


def test_dry_run_calls_nothing(cli_config: Path, tmp_path: Path) -> None:
    result = invoke(
        cli_config,
        "create",
        "--topic",
        "자동문은 사람을 어떻게 알아볼까?",
        "--type",
        "inside_object",
        "--dry-run",
    )
    assert result.exit_code == 0, result.stdout
    assert "DRY RUN" in result.stdout
    assert "estimated total" in result.stdout

    projects = list((tmp_path / "projects").iterdir())
    assert len(projects) == 1
    # The project shell exists, but no stage output was produced.
    assert (projects[0] / "project.json").exists()
    assert not (projects[0] / "research.json").exists()


def test_create_until_direct_then_inspect_and_status(cli_config: Path, tmp_path: Path) -> None:
    created = invoke(
        cli_config,
        "create",
        "--topic",
        "에스컬레이터 계단은 끝에서 어디로 갈까?",
        "--type",
        "inside_object",
        "--until",
        "direct",
    )
    assert created.exit_code == 0, created.stdout
    slug = next((tmp_path / "projects").iterdir()).name

    assert (tmp_path / "projects" / slug / "scenes.json").exists()
    assert not (tmp_path / "projects" / slug / "output" / "final.mp4").exists()

    inspected = invoke(cli_config, "inspect", slug)
    assert inspected.exit_code == 0, inspected.stdout
    assert "## Claims" in inspected.stdout
    assert "## Scenes" in inspected.stdout
    assert "PROJECT COST" in inspected.stdout

    status = invoke(cli_config, "status", slug)
    assert status.exit_code == 0
    assert "research" in status.stdout
    assert "completed" in status.stdout


def test_status_without_an_argument_lists_projects(cli_config: Path) -> None:
    invoke(
        cli_config,
        "create",
        "--topic",
        "복사기는 종이를 어떻게 복사할까?",
        "--type",
        "inside_object",
        "--until",
        "research",
    )
    result = invoke(cli_config, "status")
    assert result.exit_code == 0
    assert "boksagineun" in result.stdout


def test_unknown_project_exits_with_an_error(cli_config: Path) -> None:
    result = invoke(cli_config, "status", "no-such-project")
    assert result.exit_code == 1
    assert "no project found" in result.stderr


def test_unknown_content_type_is_rejected(cli_config: Path) -> None:
    result = invoke(cli_config, "create", "--topic", "x", "--type", "not_a_type")
    assert result.exit_code != 0
