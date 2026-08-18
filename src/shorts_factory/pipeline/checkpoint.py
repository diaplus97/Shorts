"""Load and save the artefacts that make a project resumable (spec section 25).

Every write is atomic, so a kill -9 mid-stage never corrupts prior results.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..domain import (
    AssetLedger,
    Manifest,
    Project,
    ResearchResult,
    ScenePlan,
    ScriptResult,
    SpeechPlan,
    SpeechTimeline,
)
from ..errors import PipelineValidationError
from ..utils import atomic_write_model, read_json
from .workspace import ProjectWorkspace


def _load[T: BaseModel](path: Path, model: type[T]) -> T | None:
    if not path.exists():
        return None
    try:
        return model.model_validate(read_json(path))
    except (ValidationError, ValueError) as exc:
        raise PipelineValidationError(f"{path} is not a valid {model.__name__}: {exc}") from exc


def load_project(workspace: ProjectWorkspace) -> Project | None:
    return _load(workspace.project_json, Project)


def save_project(workspace: ProjectWorkspace, project: Project) -> Path:
    return atomic_write_model(workspace.project_json, project)


def load_research(workspace: ProjectWorkspace) -> ResearchResult | None:
    return _load(workspace.research_json, ResearchResult)


def save_research(workspace: ProjectWorkspace, research: ResearchResult) -> Path:
    return atomic_write_model(workspace.research_json, research)


def load_script(workspace: ProjectWorkspace) -> ScriptResult | None:
    return _load(workspace.script_json, ScriptResult)


def save_script(workspace: ProjectWorkspace, script: ScriptResult) -> Path:
    return atomic_write_model(workspace.script_json, script)


def load_speech_plan(workspace: ProjectWorkspace) -> SpeechPlan | None:
    return _load(workspace.speech_json, SpeechPlan)


def save_speech_plan(workspace: ProjectWorkspace, plan: SpeechPlan) -> Path:
    return atomic_write_model(workspace.speech_json, plan)


def load_speech_timeline(workspace: ProjectWorkspace) -> SpeechTimeline | None:
    return _load(workspace.speech_timeline_json, SpeechTimeline)


def save_speech_timeline(workspace: ProjectWorkspace, timeline: SpeechTimeline) -> Path:
    return atomic_write_model(workspace.speech_timeline_json, timeline)


def require_speech_plan(workspace: ProjectWorkspace) -> SpeechPlan:
    plan = load_speech_plan(workspace)
    if plan is None:
        raise PipelineValidationError("speech.json is missing; run `shorts speak` first")
    return plan


def load_scenes(workspace: ProjectWorkspace) -> ScenePlan | None:
    return _load(workspace.scenes_json, ScenePlan)


def save_scenes(workspace: ProjectWorkspace, plan: ScenePlan) -> Path:
    return atomic_write_model(workspace.scenes_json, plan)


def load_assets(workspace: ProjectWorkspace) -> AssetLedger:
    return _load(workspace.assets_json, AssetLedger) or AssetLedger()


def save_assets(workspace: ProjectWorkspace, ledger: AssetLedger) -> Path:
    return atomic_write_model(workspace.assets_json, ledger)


def load_manifest(workspace: ProjectWorkspace) -> Manifest | None:
    return _load(workspace.manifest_json, Manifest)


def save_manifest(workspace: ProjectWorkspace, manifest: Manifest) -> Path:
    return atomic_write_model(workspace.manifest_json, manifest)


def require_research(workspace: ProjectWorkspace) -> ResearchResult:
    research = load_research(workspace)
    if research is None:
        raise PipelineValidationError("research.json is missing; run `shorts research` first")
    return research


def require_script(workspace: ProjectWorkspace) -> ScriptResult:
    script = load_script(workspace)
    if script is None:
        raise PipelineValidationError("script.json is missing; run `shorts write` first")
    return script


def require_scenes(workspace: ProjectWorkspace) -> ScenePlan:
    plan = load_scenes(workspace)
    if plan is None:
        raise PipelineValidationError("scenes.json is missing; run `shorts direct` first")
    return plan


def require_manifest(workspace: ProjectWorkspace) -> Manifest:
    manifest = load_manifest(workspace)
    if manifest is None:
        raise PipelineValidationError("manifest.json is missing; run `shorts narrate` first")
    return manifest
