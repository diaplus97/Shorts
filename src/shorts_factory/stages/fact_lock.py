"""Fact lock: the gate in front of every paid generation call (spec section 35).

research complete -> every factual sentence has a claim
-> every claim has a source -> unsupported claims removed -> SCRIPT_LOCKED
"""

from __future__ import annotations

from ..domain import ResearchResult, ScriptResult
from ..errors import FactCheckError
from ..pipeline.checkpoint import require_research, require_script, save_project
from ..pipeline.context import RunContext
from ..quality import FactCheckReport, QAReport, fact_lock_issues
from ._llm import structured_call
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "fact_lock"


def structural_report(script: ScriptResult, research: ResearchResult) -> QAReport:
    return QAReport(issues=fact_lock_issues(script, research))


async def llm_report(
    context: RunContext, script: ScriptResult, research: ResearchResult
) -> FactCheckReport:
    report, _ = await structured_call(
        context,
        prompt_name="qa",
        variables={
            "topic": context.project.topic,
            "narration": script.narration,
            "claims_json": [
                {"id": claim.id, "statement": claim.statement, "source_ids": claim.source_ids}
                for claim in research.supported_claims()
            ],
        },
        schema=FactCheckReport,
    )
    return report


def plan(context: RunContext) -> StagePlan:
    calls: list[PlannedCall] = []
    if context.settings.quality.llm_fact_check:
        calls.append(
            PlannedCall(
                kind="llm",
                provider=context.providers.llm.name,
                operation="qa",
                estimated_cost_usd=context.guard.estimate_llm_usd(
                    context.providers.llm.name, 3000, 1000
                ),
            )
        )
    return StagePlan(
        stage=STAGE_NAME,
        calls=calls,
        notes=["structural fact traceability check (free)"],
    )


async def run(context: RunContext) -> QAReport:
    research = require_research(context.workspace)
    script = require_script(context.workspace)

    report = structural_report(script, research)
    for issue in report.warnings:
        context.log.warning("fact_lock_warning", issue=issue.render())
    if not report.ok:
        raise FactCheckError(
            "fact lock failed; no paid generation will run:\n"
            + "\n".join(issue.render() for issue in report.errors)
        )

    if context.settings.quality.llm_fact_check:
        llm = await llm_report(context, script, research)
        if llm.verdict == "fail":
            details = [
                f"- unsupported: {finding.sentence} ({finding.reason})"
                for finding in llm.unsupported_sentences
            ] + [
                f"- overreaching: {finding.sentence} ({finding.reason})"
                for finding in llm.overreaching_sentences
            ]
            raise FactCheckError("LLM fact check failed:\n" + "\n".join(details))
        context.log.info("llm_fact_check_passed", notes=llm.notes)

    context.project.notes = [
        note for note in context.project.notes if not note.startswith("fact_lock:")
    ]
    context.project.notes.append(
        f"fact_lock: {len(script.all_claim_ids())} claims locked into the script"
    )
    save_project(context.workspace, context.project)
    context.log.info("script_locked", claims=len(script.all_claim_ids()))
    return report
