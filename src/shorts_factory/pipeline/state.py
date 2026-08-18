"""Project creation and lookup."""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import AppConfig
from ..domain import ContentType, PipelineState, Project, utcnow
from ..errors import PipelineValidationError
from ..prompts import PROMPT_VERSIONS
from ..utils import slugify, unique_slug
from .checkpoint import load_project, save_project
from .workspace import ProjectWorkspace


def projects_root(config: AppConfig) -> Path:
    root = Path(config.settings.project_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def existing_slugs(config: AppConfig) -> set[str]:
    root = projects_root(config)
    if not root.is_dir():
        return set()
    return {entry.name for entry in root.iterdir() if entry.is_dir()}


def create_project(
    *,
    topic: str,
    content_type: ContentType,
    config: AppConfig,
    slug: str | None = None,
) -> tuple[Project, ProjectWorkspace]:
    """Create the directory and ``project.json`` for a new topic."""
    if not topic.strip():
        raise PipelineValidationError("topic must not be empty")
    config.content_type(content_type.value)  # fail fast on an unknown type

    base_slug = slug or slugify(topic)
    final_slug = unique_slug(base_slug, existing_slugs(config))
    workspace = ProjectWorkspace(projects_root(config) / final_slug).ensure()

    now = utcnow()
    project = Project(
        project_id=str(uuid.uuid4()),
        slug=final_slug,
        topic=topic.strip(),
        content_type=content_type.value,
        created_at=now,
        updated_at=now,
        state=PipelineState.CREATED,
        providers=config.settings.providers.as_dict(),
        prompt_versions=dict(PROMPT_VERSIONS),
    )
    save_project(workspace, project)
    return project, workspace


def resolve_workspace(path_or_slug: str, config: AppConfig) -> ProjectWorkspace:
    """Accept either a path to a project directory or a bare slug."""
    candidate = Path(path_or_slug)
    if candidate.is_dir():
        workspace = ProjectWorkspace(candidate)
        if workspace.exists():
            return workspace
    workspace = ProjectWorkspace(projects_root(config) / path_or_slug)
    if workspace.exists():
        return workspace
    raise PipelineValidationError(f"no project found at '{path_or_slug}'")


def load_existing(path_or_slug: str, config: AppConfig) -> tuple[Project, ProjectWorkspace]:
    workspace = resolve_workspace(path_or_slug, config)
    project = load_project(workspace)
    if project is None:
        raise PipelineValidationError(f"{workspace.project_json} is missing or unreadable")
    return project, workspace


def list_projects(config: AppConfig) -> list[tuple[Project, ProjectWorkspace]]:
    root = projects_root(config)
    if not root.is_dir():
        return []
    found: list[tuple[Project, ProjectWorkspace]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        workspace = ProjectWorkspace(entry)
        project = load_project(workspace) if workspace.exists() else None
        if project is not None:
            found.append((project, workspace))
    return found
