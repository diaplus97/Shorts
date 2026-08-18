"""Pipeline orchestration, state and persistence."""

from .checkpoint import (
    load_assets,
    load_manifest,
    load_project,
    load_research,
    load_scenes,
    load_script,
    save_assets,
    save_manifest,
    save_project,
    save_research,
    save_scenes,
    save_script,
)
from .context import RunContext, build_context
from .orchestrator import (
    PAID_STAGES,
    STAGE_MODULES,
    PipelineResult,
    invalidate_downstream,
    plan_pipeline,
    run_pipeline,
    run_stage,
    total_estimated_cost,
)
from .state import create_project, list_projects, load_existing, projects_root, resolve_workspace
from .workspace import ProjectWorkspace

__all__ = [
    "PAID_STAGES",
    "STAGE_MODULES",
    "PipelineResult",
    "ProjectWorkspace",
    "RunContext",
    "build_context",
    "create_project",
    "invalidate_downstream",
    "list_projects",
    "load_assets",
    "load_existing",
    "load_manifest",
    "load_project",
    "load_research",
    "load_scenes",
    "load_script",
    "plan_pipeline",
    "projects_root",
    "resolve_workspace",
    "run_pipeline",
    "run_stage",
    "save_assets",
    "save_manifest",
    "save_project",
    "save_research",
    "save_scenes",
    "save_script",
    "total_estimated_cost",
]
