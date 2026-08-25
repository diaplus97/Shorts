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


def invoke(cli_config: Path, *args: str, answer: str | None = None):
    return runner.invoke(app, ["--config-dir", str(cli_config), *args], input=answer)


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
    # The mock has one hand-written scenario. Use its topic: any other one is
    # placeholder material, and placeholder material is supposed to fail the
    # content gates -- see test_a_topic_the_mock_has_no_scenario_for_is_rejected.
    created = invoke(
        cli_config,
        "create",
        "--topic",
        "ATM은 돈을 어떻게 세는 걸까?",
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


def test_a_topic_the_mock_has_no_scenario_for_is_rejected(cli_config: Path) -> None:
    """Placeholder content must fail the content gates, loudly.

    ``scenarios.py`` says a mock that returns vague text means the quality
    checks are only ever tested against material that would fail in production.
    It had one hand-written scenario and a generic fallback that told the same
    parcel-sorting story about every other topic -- kimchi fermentation
    included -- in language made of pronouns. That passed every check.

    Now it does not. Failing here is the correct outcome: it says the mock has
    no data for this topic, which is true, instead of fabricating a plausible
    answer that is about something else.
    """
    result = invoke(
        cli_config,
        "create",
        "--topic",
        "김치는 어떻게 발효될까?",
        "--type",
        "inside_object",
        "--until",
        "write",
    )
    assert result.exit_code == 1, result.stdout


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


# -- the review gate -------------------------------------------------------
#
# One command should be able to run end to end, but not spend on a script
# nobody read. The gate stops once, before the first paid stage.


ATM = ("--topic", "ATM은 돈을 어떻게 세는 걸까?", "--type", "inside_object")


def test_declining_the_script_stops_before_the_paid_stage(cli_config: Path, tmp_path: Path) -> None:
    """Answering no leaves everything already done on disk for resume."""
    result = invoke(cli_config, "create", *ATM, "--slug", "gated", answer="n\n")

    assert result.exit_code == 0, result.stdout
    assert "Generate the video from this script?" in result.stdout
    # Stopped at the last free stage, with nothing generated.
    assert "state: directed" in result.stdout
    project = tmp_path / "projects" / "gated"
    assert not (project / "output" / "final.mp4").exists()
    assert not (project / "output" / "mock_preview.mp4").exists()


def test_the_gate_shows_the_script_it_is_asking_about(cli_config: Path) -> None:
    """Asking "spend money?" without showing what on is not a review."""
    result = invoke(cli_config, "create", *ATM, "--slug", "gated", answer="n\n")

    assert "SCRIPT" in result.stdout
    assert "[hook" in result.stdout
    assert "[closing" in result.stdout
    assert "spent so far" in result.stdout


def test_resume_after_declining_finishes_the_run(cli_config: Path, tmp_path: Path) -> None:
    invoke(cli_config, "create", *ATM, "--slug", "gated", answer="n\n")
    result = invoke(cli_config, "resume", "gated", answer="y\n")

    assert result.exit_code == 0, result.stdout
    assert "state: done" in result.stdout
    # The free stages are not paid for twice.
    assert "skipped : ['research'" in result.stdout


def test_yes_runs_straight_through_without_asking(cli_config: Path) -> None:
    """Unattended use has to stay possible; the gate is a default, not a wall."""
    result = invoke(cli_config, "create", *ATM, "--slug", "gated", "--yes")

    assert result.exit_code == 0, result.stdout
    assert "Generate the video from this script?" not in result.stdout
    assert "state: done" in result.stdout


def test_stopping_before_the_paid_stage_never_asks(cli_config: Path) -> None:
    """--until direct is already a decision not to spend."""
    result = invoke(cli_config, "create", *ATM, "--until", "direct", "--slug", "gated")

    assert result.exit_code == 0, result.stdout
    assert "Generate the video from this script?" not in result.stdout
