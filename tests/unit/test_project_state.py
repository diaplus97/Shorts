"""Project creation, checkpointing and resume logic (spec sections 25, 63)."""

from __future__ import annotations

import json

import pytest

from shorts_factory.domain import ContentType, PipelineState, Stage, StageStatus
from shorts_factory.errors import PipelineValidationError
from shorts_factory.pipeline import (
    create_project,
    invalidate_downstream,
    list_projects,
    load_existing,
    load_project,
    resolve_workspace,
    save_project,
)
from shorts_factory.pipeline.orchestrator import should_skip


def test_create_project_lays_out_the_directory(config) -> None:
    project, workspace = create_project(
        topic="ATM은 돈을 어떻게 세는 걸까?", content_type=ContentType.INSIDE_OBJECT, config=config
    )
    assert workspace.project_json.exists()
    for directory in (
        workspace.prompts_dir,
        workspace.assets_dir,
        workspace.audio_dir,
        workspace.subtitles_dir,
        workspace.logs_dir,
        workspace.output_dir,
    ):
        assert directory.is_dir()
    assert project.slug == "atmeun-doneul-eotteotge-seneun-geolkka"
    assert project.state is PipelineState.CREATED
    assert project.providers["llm"] == "mock"


def test_slug_collisions_get_a_suffix(config) -> None:
    first, _ = create_project(
        topic="같은 주제", content_type=ContentType.HIDDEN_SYSTEM, config=config
    )
    second, _ = create_project(
        topic="같은 주제", content_type=ContentType.HIDDEN_SYSTEM, config=config
    )
    assert second.slug == f"{first.slug}-2"


def test_empty_topic_is_rejected(config) -> None:
    with pytest.raises(PipelineValidationError, match="topic"):
        create_project(topic="   ", content_type=ContentType.HIDDEN_SYSTEM, config=config)


def test_project_json_is_valid_json_after_every_write(config, project_and_workspace) -> None:
    project, workspace = project_and_workspace
    project.mark_stage_completed(Stage.RESEARCH, PipelineState.RESEARCHED)
    save_project(workspace, project)
    payload = json.loads(workspace.project_json.read_text())
    assert payload["stages"]["research"]["status"] == "completed"


def test_resolve_workspace_accepts_a_slug_or_a_path(config, project_and_workspace) -> None:
    project, workspace = project_and_workspace
    assert resolve_workspace(project.slug, config).root == workspace.root
    assert resolve_workspace(str(workspace.root), config).root == workspace.root
    with pytest.raises(PipelineValidationError, match="no project found"):
        resolve_workspace("does-not-exist", config)


def test_load_existing_round_trips(config, project_and_workspace) -> None:
    project, _ = project_and_workspace
    reloaded, _ = load_existing(project.slug, config)
    assert reloaded.project_id == project.project_id
    assert reloaded.topic == project.topic


def test_list_projects_finds_created_projects(config, project_and_workspace) -> None:
    assert [proj.slug for proj, _ in list_projects(config)] == [project_and_workspace[0].slug]


def test_completed_stages_are_skipped(context) -> None:
    context.project.mark_stage_completed(Stage.RESEARCH, PipelineState.RESEARCHED)
    assert should_skip(context, Stage.RESEARCH)
    assert not should_skip(context, Stage.WRITE)


def test_force_disables_skipping(context) -> None:
    context.project.mark_stage_completed(Stage.RESEARCH, PipelineState.RESEARCHED)
    context.force = True
    assert not should_skip(context, Stage.RESEARCH)


def test_rerunning_a_stage_invalidates_everything_after_it(project_and_workspace) -> None:
    project, _ = project_and_workspace
    for stage in Stage:
        project.mark_stage_completed(stage)

    invalidate_downstream(project, Stage.WRITE)

    assert project.is_stage_completed(Stage.RESEARCH)
    assert project.is_stage_completed(Stage.WRITE)
    for stage in (Stage.FACT_LOCK, Stage.DIRECT, Stage.GENERATE, Stage.NARRATE):
        assert project.stage(stage).status is StageStatus.PENDING


def test_failure_keeps_earlier_results(project_and_workspace) -> None:
    project, workspace = project_and_workspace
    project.mark_stage_completed(Stage.RESEARCH, PipelineState.RESEARCHED)
    project.mark_stage_failed(Stage.WRITE, "provider exploded")
    save_project(workspace, project)

    reloaded = load_project(workspace)
    assert reloaded.is_stage_completed(Stage.RESEARCH)
    assert reloaded.stage(Stage.WRITE).status is StageStatus.FAILED
    assert "provider exploded" in reloaded.stage(Stage.WRITE).error
    assert reloaded.state is PipelineState.FAILED
