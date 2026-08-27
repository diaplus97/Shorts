"""The deterministic pipeline (spec section 3.2).

A plain ordered sequence of stages with explicit state, not an agent swarm.
Each stage is skipped when it is already complete, and running a stage
invalidates everything downstream of it.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from ..domain import (
    STAGE_COMPLETION_STATE,
    STAGE_ORDER,
    PipelineState,
    Project,
    Stage,
    StageStatus,
    stages_up_to,
)
from ..errors import ShortsFactoryError
from ..stages import (
    asset_generation,
    composition,
    directing,
    fact_lock,
    narration,
    research,
    speech,
    validation,
    writing,
)
from ..stages._plan import StagePlan
from .checkpoint import save_project
from .context import RunContext

STAGE_MODULES = {
    Stage.RESEARCH: research,
    Stage.WRITE: writing,
    Stage.FACT_LOCK: fact_lock,
    Stage.SPEAK: speech,
    Stage.DIRECT: directing,
    Stage.GENERATE: asset_generation,
    Stage.NARRATE: narration,
    Stage.VALIDATE: validation,
    Stage.COMPOSE: composition,
}

#: Stages that spend money. `shorts inspect` warns before these run.
PAID_STAGES = frozenset({Stage.RESEARCH, Stage.WRITE, Stage.DIRECT, Stage.GENERATE, Stage.NARRATE})


class PipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    state: PipelineState
    total_cost_usd: float = 0.0
    final_video_path: str | None = None
    preview_video_path: str | None = None


def invalidate_downstream(project: Project, stage: Stage) -> None:
    """Re-running a stage makes every later stage stale."""
    index = STAGE_ORDER.index(stage)
    for later in STAGE_ORDER[index + 1 :]:
        record = project.stage(later)
        if record.status is not StageStatus.PENDING:
            record.status = StageStatus.PENDING
            record.error = None
            record.completed_at = None


def should_skip(context: RunContext, stage: Stage) -> bool:
    return not context.force and context.project.is_stage_completed(stage)


async def run_stage(context: RunContext, stage: Stage) -> bool:
    """Run one stage. Returns ``False`` when it was skipped as already done."""
    if should_skip(context, stage):
        context.log.info("stage_skipped", stage=stage.value, reason="already completed")
        return False

    module = STAGE_MODULES[stage]
    context.project.mark_stage_running(stage)
    save_project(context.workspace, context.project)
    context.log.info("stage_started", stage=stage.value)

    try:
        await module.run(context)
    except ShortsFactoryError as exc:
        context.project.mark_stage_failed(stage, f"{type(exc).__name__}: {exc}")
        save_project(context.workspace, context.project)
        context.log.error("stage_failed", stage=stage.value, error=str(exc)[:500])
        raise

    invalidate_downstream(context.project, stage)
    context.project.mark_stage_completed(stage, STAGE_COMPLETION_STATE[stage])
    context.project.cost_breakdown = context.tracker.summary()
    context.project.actual_cost_usd = context.tracker.total_usd()
    if all(context.project.is_stage_completed(s) for s in STAGE_ORDER):
        context.project.state = PipelineState.DONE
    save_project(context.workspace, context.project)
    context.log.info("stage_completed", stage=stage.value)
    return True


#: Consulted before each stage. Returning False stops the run cleanly, with
#: everything already done left on disk for `resume`.
StageGate = Callable[[RunContext, Stage], bool]


async def run_pipeline(
    context: RunContext,
    *,
    until: Stage | None = None,
    before_stage: StageGate | None = None,
) -> PipelineResult:
    """Run the stages in order, optionally asking before each one.

    ``before_stage`` exists so the CLI can put a human in front of the money:
    the script is worth reading before eleven video clips are bought against
    it, and a caller that declines simply stops -- the completed stages stay on
    disk and `resume` picks up from there.
    """
    executed: list[str] = []
    skipped: list[str] = []

    for stage in stages_up_to(until):
        if before_stage is not None and not before_stage(context, stage):
            context.log.info("run_stopped_at_gate", stage=stage.value)
            break
        if await run_stage(context, stage):
            executed.append(stage.value)
        else:
            skipped.append(stage.value)

    return PipelineResult(
        executed=executed,
        skipped=skipped,
        state=context.project.state,
        total_cost_usd=context.tracker.total_usd(),
        final_video_path=context.project.final_video_path,
        preview_video_path=context.project.preview_video_path,
    )


def plan_pipeline(context: RunContext, *, until: Stage | None = None) -> list[StagePlan]:
    """Dry-run plan: what would be called, and roughly what it would cost."""
    plans: list[StagePlan] = []
    for stage in stages_up_to(until):
        module = STAGE_MODULES[stage]
        if should_skip(context, stage):
            plans.append(StagePlan(stage=stage.value, skipped=True, reason="already completed"))
            continue
        plans.append(module.plan(context))
    return plans


def total_estimated_cost(plans: list[StagePlan]) -> float:
    return round(sum(plan.estimated_cost_usd for plan in plans), 6)
