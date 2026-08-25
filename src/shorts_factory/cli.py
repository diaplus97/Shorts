"""Typer CLI (spec section 45).

shorts create | research | write | direct | generate | narrate
       | inspect | render | resume | status | doctor
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import AppConfig, load_config
from .domain import ContentType, Stage, StageStatus
from .errors import ShortsFactoryError
from .pipeline import (
    PAID_STAGES,
    ProjectWorkspace,
    RunContext,
    build_context,
    create_project,
    list_projects,
    load_assets,
    load_existing,
    load_research,
    load_scenes,
    load_script,
    plan_pipeline,
    run_pipeline,
    run_stage,
    total_estimated_cost,
)
from .providers import build_providers
from .quality import QAReport, check_scene_plan, check_script, fact_lock_issues
from .utils import bind_project_log, configure_logging

app = typer.Typer(
    name="shorts",
    help="Invisible Systems Shorts Factory — topic in, vertical MP4 out.",
    no_args_is_help=True,
    add_completion=False,
)

_STATE: dict[str, object] = {}


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _config() -> AppConfig:
    config_dir = _STATE.get("config_dir")
    try:
        return load_config(config_dir)  # type: ignore[arg-type]
    except ShortsFactoryError as exc:
        raise _fail(f"{type(exc).__name__}: {exc}") from exc


def _context(
    project_ref: str, *, dry_run: bool = False, force: bool = False
) -> tuple[RunContext, ProjectWorkspace]:
    config = _config()
    try:
        project, workspace = load_existing(project_ref, config)
    except ShortsFactoryError as exc:
        raise _fail(f"{type(exc).__name__}: {exc}") from exc
    bind_project_log(workspace.pipeline_log)
    context = build_context(
        config=config,
        project=project,
        workspace=workspace,
        providers=build_providers(config),
        dry_run=dry_run,
        force=force,
    )
    return context, workspace


def _run(coro):
    try:
        return asyncio.run(coro)
    except ShortsFactoryError as exc:
        raise _fail(f"{type(exc).__name__}: {exc}") from exc


def _print_plans(context: RunContext, until: Stage | None) -> None:
    plans = plan_pipeline(context, until=until)
    typer.echo("")
    typer.secho("DRY RUN — no paid API will be called", fg=typer.colors.YELLOW, bold=True)
    typer.echo(f"project directory: {context.workspace.root}")
    typer.echo(f"providers:         {context.providers.names()}")
    typer.echo("")
    for plan in plans:
        if plan.skipped:
            typer.echo(f"[{plan.stage}] skipped — {plan.reason}")
            continue
        typer.secho(
            f"[{plan.stage}] {plan.call_count} call(s), est. ${plan.estimated_cost_usd:.4f}",
            bold=True,
        )
        for call in plan.calls:
            detail = f" — {call.detail}" if call.detail else ""
            typer.echo(
                f"    {call.kind:<6} {call.provider}/{call.operation} x{call.count} "
                f"${call.estimated_cost_usd:.4f}{detail}"
            )
        for note in plan.notes:
            typer.echo(f"    note: {note}")
    total = total_estimated_cost(plans)
    limit = context.config.budgets.project.max_total_usd
    typer.echo("")
    typer.secho(f"estimated total: ${total:.4f} (budget ${limit:.2f})", bold=True)
    if total > limit:
        typer.secho("this plan exceeds the project budget", fg=typer.colors.RED)


#: The first stage that spends real money on assets. Everything before it is
#: research and text, which is cheap; everything after commits to the script.
FIRST_PAID_STAGE = Stage.GENERATE


def _review_gate(until: Stage | None, auto_yes: bool):
    """A gate that shows the script and asks once, before anything expensive.

    Reading the narration before eleven clips are bought against it is the
    cheapest quality control available -- a bad script cannot be rescued by
    good pictures, and by the generate stage the money is already gone.
    """
    asked = {"done": False}

    def gate(context: RunContext, stage: Stage) -> bool:
        if asked["done"] or stage is not FIRST_PAID_STAGE:
            return True
        asked["done"] = True

        script = load_script(context.workspace)
        if script is None:
            # Nothing written yet, so there is nothing to review; the stage
            # itself will fail with a clearer message than this gate could.
            return True
        typer.echo("")
        typer.secho("  SCRIPT", bold=True)
        typer.echo(f"    {script.hook}")
        typer.echo("")
        for beat in script.beats:
            typer.echo(f"    [{beat.purpose:<10}] {beat.text}")
        typer.echo("")

        plans = plan_pipeline(context, until=until)
        remaining = total_estimated_cost([plan for plan in plans if not plan.skipped])
        spent = context.tracker.total_usd()
        typer.secho(
            f"  spent so far ${spent:.4f} — the stages after this cost about ${remaining:.4f} more",
            bold=True,
        )
        typer.echo("")

        if auto_yes:
            return True
        return typer.confirm("  Generate the video from this script?", default=False)

    return gate


@app.callback()
def main(
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    log_level: Annotated[
        str, typer.Option("--log-level", help="DEBUG, INFO, WARNING, ERROR.")
    ] = "INFO",
) -> None:
    _STATE["config_dir"] = config_dir
    configure_logging(log_level, force=True)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def create(
    topic: Annotated[str, typer.Option("--topic", "-t", help="The question the Short answers.")],
    content_type: Annotated[
        ContentType, typer.Option("--type", help="hidden_system | inside_object | behind_action")
    ],
    until: Annotated[
        Stage | None,
        typer.Option("--until", help="Stop after this stage (e.g. direct) to avoid paid calls."),
    ] = None,
    slug: Annotated[str | None, typer.Option("--slug", help="Override the directory name.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plan only; call nothing.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run stages already completed.")
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the script review before paid generation."),
    ] = False,
) -> None:
    """Create a project and run the pipeline.

    Stops once before the first paid stage to show the script and ask, so one
    command can run end to end without spending on a script nobody read.
    Pass --yes to run straight through.
    """
    config = _config()
    try:
        project, workspace = create_project(
            topic=topic, content_type=content_type, config=config, slug=slug
        )
    except ShortsFactoryError as exc:
        raise _fail(f"{type(exc).__name__}: {exc}") from exc

    bind_project_log(workspace.pipeline_log)
    typer.secho(f"created {workspace.root}", fg=typer.colors.GREEN)

    context = build_context(
        config=config,
        project=project,
        workspace=workspace,
        providers=build_providers(config),
        dry_run=dry_run,
        force=force,
    )
    if dry_run:
        _print_plans(context, until)
        return

    result = _run(run_pipeline(context, until=until, before_stage=_review_gate(until, yes)))
    _print_result(context, result)


@app.command()
def resume(
    project: Annotated[str, typer.Argument(help="Project directory or slug.")],
    until: Annotated[Stage | None, typer.Option("--until")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the script review before paid generation."),
    ] = False,
) -> None:
    """Continue a project, skipping work that is already done."""
    context, _ = _context(project, dry_run=dry_run, force=force)
    if dry_run:
        _print_plans(context, until)
        return
    result = _run(run_pipeline(context, until=until, before_stage=_review_gate(until, yes)))
    _print_result(context, result)


def _single_stage(project: str, stage: Stage, dry_run: bool, force: bool) -> None:
    context, _ = _context(project, dry_run=dry_run, force=force)
    if dry_run:
        _print_plans(context, stage)
        return
    _run(run_stage(context, stage))
    typer.secho(f"{stage.value}: done", fg=typer.colors.GREEN)
    typer.echo(context.tracker.render_table())


@app.command()
def research(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Gather sources and turn them into claims."""
    _single_stage(project, Stage.RESEARCH, dry_run, force)


@app.command()
def write(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Write the narration from the verified claims."""
    _single_stage(project, Stage.WRITE, dry_run, force)


@app.command()
def speak(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Break the narration into speech units and plan the pauses. No LLM call."""
    _single_stage(project, Stage.SPEAK, dry_run, force)


@app.command()
def direct(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Turn the narration into a scene plan."""
    _single_stage(project, Stage.DIRECT, dry_run, force)


@app.command()
def generate(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Generate the scene assets. This is the expensive stage."""
    _single_stage(project, Stage.GENERATE, dry_run, force)


@app.command()
def narrate(
    project: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Synthesise the voice track, then lock timing, subtitles and manifest."""
    _single_stage(project, Stage.NARRATE, dry_run, force)


def _mock_summary(context: RunContext) -> str:
    from .quality import mock_provider_kinds

    return ", ".join(mock_provider_kinds(context.providers))


@app.command()
def render(
    project: Annotated[str, typer.Argument()],
    bgm: Annotated[
        Path | None, typer.Option("--bgm", help="Optional background music track.")
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Validate everything, then compose final.mp4 (real providers only)."""
    context, workspace = _context(project, force=force)
    if not context.production_ready:
        _fail(
            f"this project uses mock providers ({_mock_summary(context)}), so it cannot "
            "produce final.mp4. Run `shorts mock-render` for a watermarked preview, or "
            "switch config/settings.yaml to real providers."
        )
    context.bgm_path = str(bgm) if bgm is not None else None
    _run(run_stage(context, Stage.VALIDATE))
    _run(run_stage(context, Stage.COMPOSE))
    typer.secho(f"rendered {workspace.final_video}", fg=typer.colors.GREEN)
    typer.echo(context.tracker.render_table())


@app.command(name="mock-render")
def mock_render(
    project: Annotated[str, typer.Argument()],
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Compose a watermarked mock_preview.mp4. Never upload the result."""
    context, workspace = _context(project, force=force)
    if context.production_ready:
        _fail(
            "every provider is real, so this would be a production render.\n"
            "Use `shorts render` instead."
        )
    typer.secho(
        f"mock providers: {_mock_summary(context)} — output will be watermarked",
        fg=typer.colors.YELLOW,
    )
    _run(run_stage(context, Stage.VALIDATE))
    _run(run_stage(context, Stage.COMPOSE))
    typer.secho(f"rendered {workspace.mock_preview}", fg=typer.colors.YELLOW)
    typer.echo(context.tracker.render_table())


@app.command()
def inspect(project: Annotated[str, typer.Argument()]) -> None:
    """Human review before spending money (spec section 38)."""
    context, workspace = _context(project)
    proj = context.project
    typer.secho(f"# {proj.topic}", bold=True)
    typer.echo(f"slug         : {proj.slug}")
    typer.echo(f"content type : {proj.content_type}")
    typer.echo(f"state        : {proj.state}")
    typer.echo(f"providers    : {proj.providers}")
    typer.echo(f"directory    : {workspace.root}")
    if context.production_ready:
        typer.secho("production   : real providers — will produce final.mp4", fg=typer.colors.GREEN)
    else:
        typer.secho(
            f"production   : MOCK ({_mock_summary(context)}) — will produce mock_preview.mp4",
            fg=typer.colors.YELLOW,
        )

    script = load_script(workspace)
    if script is not None:
        typer.echo("")
        typer.secho("## Script", bold=True)
        typer.echo(f"title    : {script.title}")
        typer.echo(f"hook     : {script.hook}")
        typer.echo(f"duration : {script.target_duration_sec:.1f}s target")
        typer.echo(f"beats    : {len(script.beats)}")

    research_result = load_research(workspace)
    if research_result is not None:
        typer.echo("")
        typer.secho("## Claims", bold=True)
        for claim in research_result.claims:
            typer.echo(
                f"  {claim.id} [{claim.confidence}] {claim.statement}  "
                f"({', '.join(claim.source_ids) or 'NO SOURCE'})"
            )

    plan = load_scenes(workspace)
    ledger = load_assets(workspace)
    if plan is not None:
        typer.echo("")
        typer.secho("## Scenes", bold=True)
        for scene in plan.scenes:
            record = ledger.get(scene.id)
            status = record.status.value if record else "pending"
            flag = " (fallback)" if record and record.fallback_used else ""
            typer.echo(
                f"  {scene.id} {scene.duration_sec:>5.2f}s {scene.priority:<6} "
                f"{scene.reality_type:<13} {status}{flag}  {scene.visual_subject[:48]}"
            )
        typer.echo(f"  total: {plan.total_duration_sec:.2f}s across {len(plan.scenes)} scenes")

    typer.echo("")
    typer.secho("## Cost", bold=True)
    typer.echo(context.tracker.render_table())
    plans = plan_pipeline(context)
    remaining = total_estimated_cost(plans)
    pending_paid = [
        plan.stage
        for plan in plans
        if not plan.skipped and Stage(plan.stage) in PAID_STAGES and plan.calls
    ]
    typer.echo(f"estimated remaining: ${remaining:.4f}")
    typer.echo(f"paid stages left   : {pending_paid or '—'}")
    typer.echo(f"budget remaining   : ${context.guard.remaining_usd:.4f}")

    warnings = _collect_warnings(context)
    typer.echo("")
    typer.secho("## Warnings", bold=True)
    typer.echo("\n".join(f"  {w}" for w in warnings) if warnings else "  none")


def _collect_warnings(context: RunContext) -> list[str]:
    workspace = context.workspace
    report = QAReport()
    script = load_script(workspace)
    research_result = load_research(workspace)
    plan = load_scenes(workspace)
    if script is not None:
        report.extend(check_script(script, context.settings))
    if script is not None and research_result is not None:
        report.extend(fact_lock_issues(script, research_result))
    if plan is not None and script is not None:
        report.extend(check_scene_plan(plan, script, context.settings, context.config.budgets))
    return [issue.render() for issue in report.issues]


@app.command()
def status(
    project: Annotated[str | None, typer.Argument(help="Omit to list every project.")] = None,
) -> None:
    """Show stage status and cost."""
    config = _config()
    if project is None:
        projects = list_projects(config)
        if not projects:
            typer.echo("no projects yet")
            return
        for proj, workspace in projects:
            typer.echo(
                f"{proj.slug:<40} {proj.state:<12} ${proj.actual_cost_usd:>7.4f}  {workspace.root}"
            )
        return

    context, workspace = _context(project)
    proj = context.project
    typer.secho(f"{proj.slug} — {proj.topic}", bold=True)
    typer.echo(f"state: {proj.state}")
    typer.echo("")
    for stage in Stage:
        record = proj.stage(stage)
        colour = {
            StageStatus.COMPLETED: typer.colors.GREEN,
            StageStatus.FAILED: typer.colors.RED,
            StageStatus.RUNNING: typer.colors.YELLOW,
        }.get(record.status)
        line = f"  {stage.value:<12} {record.status.value:<10} attempts={record.attempts}"
        if record.error:
            line += f"  error={record.error[:120]}"
        typer.secho(line, fg=colour)
    typer.echo("")
    typer.echo(context.tracker.render_table())
    typer.echo("")
    if proj.final_video_path:
        typer.secho(
            f"final video  : {workspace.root / proj.final_video_path}", fg=typer.colors.GREEN
        )
    elif proj.preview_video_path:
        typer.secho(
            f"mock preview : {workspace.root / proj.preview_video_path} (not for upload)",
            fg=typer.colors.YELLOW,
        )


@app.command()
def doctor() -> None:
    """Check that this machine can actually run the pipeline."""
    from .scripts_doctor import run_doctor

    ok = run_doctor(_STATE.get("config_dir"))  # type: ignore[arg-type]
    raise typer.Exit(code=0 if ok else 1)


def _print_result(context: RunContext, result) -> None:
    if result is None:
        return
    typer.echo("")
    typer.secho(f"state: {result.state}", bold=True)
    typer.echo(f"executed: {result.executed or '—'}")
    typer.echo(f"skipped : {result.skipped or '—'}")
    typer.echo("")
    typer.echo(context.tracker.render_table())
    if result.final_video_path:
        typer.secho(
            f"\nfinal video: {context.workspace.root / result.final_video_path}",
            fg=typer.colors.GREEN,
        )
    elif result.preview_video_path:
        typer.secho(
            f"\nmock preview: {context.workspace.root / result.preview_video_path} "
            "(watermarked, not for upload)",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":  # pragma: no cover
    app()
