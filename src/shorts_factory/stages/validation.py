"""Validation stage: everything that can be checked without spending money."""

from __future__ import annotations

from pathlib import Path

from ..domain import Manifest
from ..errors import MediaError, PipelineValidationError
from ..media import probe
from ..pipeline.checkpoint import (
    load_assets,
    require_manifest,
    require_research,
    require_scenes,
    require_script,
    require_speech_plan,
)
from ..pipeline.context import RunContext
from ..quality import (
    QAIssue,
    QAReport,
    assess,
    check_assets,
    check_scene_contract,
    check_scene_plan,
    check_scene_speech_alignment,
    check_scene_traceability,
    check_script,
    check_script_contract,
    check_speech_plan,
    error,
    fact_lock_issues,
    warning,
)
from ..utils import atomic_write_model
from ._plan import StagePlan

STAGE_NAME = "validate"


def check_source_assets(context: RunContext, manifest: Manifest) -> QAReport:
    """Every scene must have a source file that ffprobe can actually read."""
    report = QAReport()
    ledger = load_assets(context.workspace)
    for entry in manifest.scenes:
        record = ledger.get(entry.scene_id)
        if record is None or not record.local_path:
            report.issues.append(error("asset_missing", "no asset record", entry.scene_id))
            continue
        source = context.workspace.root / record.local_path
        if not source.exists():
            source = Path(record.local_path)
        if not source.exists():
            report.issues.append(
                error("asset_file_missing", f"{record.local_path} is gone", entry.scene_id)
            )
            continue
        try:
            info = probe(source)
        except MediaError as exc:
            report.issues.append(error("asset_unreadable", str(exc), entry.scene_id))
            continue
        if not info.has_video and source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            report.issues.append(
                error("asset_no_video", "source has no video stream", entry.scene_id)
            )
    return report


def check_readiness(context: RunContext, scene_plan, ledger) -> list:
    """Catch a dead voice track here, before anything is encoded.

    An MP4 with a valid AAC stream and no signal in it used to pass every check
    in this pipeline. It does not any more (spec v0.2 section 36.4).
    """
    voice = context.workspace.narration_wav
    readiness = assess(
        config=context.config,
        providers=context.providers,
        plan=scene_plan,
        ledger=ledger,
        voice_path=voice if voice.exists() else None,
    )
    atomic_write_model(context.workspace.logs_dir / "production_readiness.json", readiness)

    issues: list[QAIssue] = []
    if voice.exists() and not readiness.audio_valid:
        issues.extend(
            error("audio_invalid", reason)
            for reason in readiness.blocking_reasons
            if "mock providers" not in reason
        )
    # Mocks do not block validation; they block *publishing* as final.mp4.
    if readiness.contains_mock_assets:
        issues.append(
            warning(
                "mock_providers_in_use",
                f"{', '.join(readiness.mock_providers)} are stand-ins; this run can only "
                "produce mock_preview.mp4",
            )
        )
    issues.extend(warning("production_warning", detail) for detail in readiness.warnings)
    return issues


def plan(context: RunContext) -> StagePlan:
    notes = ["local checks only, no paid calls"]
    if not context.production_ready:
        notes.append("mock providers in use: validation will not clear this run for final.mp4")
    return StagePlan(stage=STAGE_NAME, notes=notes)


async def run(context: RunContext) -> QAReport:
    research = require_research(context.workspace)
    script = require_script(context.workspace)
    scene_plan = require_scenes(context.workspace)
    speech = require_speech_plan(context.workspace)
    manifest = require_manifest(context.workspace)
    ledger = load_assets(context.workspace)

    contract = context.config.content_contract
    report = QAReport()
    report.extend(fact_lock_issues(script, research))
    report.extend(check_script(script, context.settings))
    report.extend(check_script_contract(script, research, contract, context.settings.script))
    report.extend(check_scene_plan(scene_plan, script, context.settings, context.config.budgets))
    report.extend(check_scene_traceability(scene_plan, research))
    report.extend(check_scene_contract(scene_plan, contract))
    report.extend(check_speech_plan(speech, context.config.voice.speech))
    report.extend(check_scene_speech_alignment(scene_plan, speech))
    report.extend(check_assets(scene_plan, ledger))
    report.extend(check_source_assets(context, manifest).issues)
    report.extend(check_readiness(context, scene_plan, ledger))

    atomic_write_model(context.workspace.logs_dir / "validation.json", report)
    for issue in report.warnings:
        context.log.warning("validation_warning", issue=issue.render())

    strict_failure = context.settings.quality.strict and report.warnings
    if not report.ok or strict_failure:
        blocking = report.errors or report.warnings
        raise PipelineValidationError(
            "validation failed:\n" + "\n".join(issue.render() for issue in blocking)
        )

    context.log.info(
        "validation_passed", scenes=len(scene_plan.scenes), warnings=len(report.warnings)
    )
    return report
