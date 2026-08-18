"""The bundle every stage receives.

Stages take a ``RunContext`` and return nothing: they persist their own output
through the checkpoint helpers, which is what makes each one independently
resumable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import AppConfig
from ..cost import BudgetGuard, CostTracker
from ..domain import Project
from ..providers import ProviderSet
from ..utils import get_logger
from .workspace import ProjectWorkspace


@dataclass
class RunContext:
    config: AppConfig
    project: Project
    workspace: ProjectWorkspace
    providers: ProviderSet
    tracker: CostTracker
    guard: BudgetGuard
    #: ``True`` suppresses every paid call; stages report a plan instead.
    dry_run: bool = False
    #: Optional background music mixed under the narration during composition.
    bgm_path: str | None = None
    #: Re-run stages that are already marked completed.
    force: bool = False
    log: Any = field(default_factory=lambda: get_logger("pipeline"))

    @property
    def settings(self):
        return self.config.settings

    def bind(self, **kwargs: Any) -> None:
        """Attach persistent fields to every subsequent log line."""
        self.log = self.log.bind(**kwargs)


def build_context(
    *,
    config: AppConfig,
    project: Project,
    workspace: ProjectWorkspace,
    providers: ProviderSet,
    dry_run: bool = False,
    force: bool = False,
) -> RunContext:
    tracker = CostTracker(workspace.cost_ledger)
    guard = BudgetGuard(config.budgets, tracker)
    context = RunContext(
        config=config,
        project=project,
        workspace=workspace,
        providers=providers,
        tracker=tracker,
        guard=guard,
        dry_run=dry_run,
        force=force,
    )
    context.bind(project=project.slug)
    return context
