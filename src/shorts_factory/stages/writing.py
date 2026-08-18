"""Writer stage: research -> one narration (spec sections 13-14).

Hook and script are written together in a single pass; separate hook and script
agents would just add context and cost (spec section 13).
"""

from __future__ import annotations

from ..domain import ResearchResult, ScriptResult
from ..pipeline.checkpoint import require_research, save_project, save_script
from ..pipeline.context import RunContext
from ..quality import QAIssue, check_script, check_script_traceability
from ..utils import atomic_write_text, relative_to
from ._llm import structured_call
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "write"


def char_budget(context: RunContext) -> tuple[int, int, int]:
    """Narration length in non-whitespace characters: (target, min, max)."""
    script = context.settings.script
    rate = script.chars_per_sec
    return (
        round(script.target_duration_sec * rate),
        round(script.min_duration_sec * rate),
        round(script.max_duration_sec * rate),
    )


def claims_payload(research: ResearchResult) -> list[dict[str, object]]:
    """Only sourced claims are offered to the writer (spec section 11)."""
    return [
        {
            "id": claim.id,
            "statement": claim.statement,
            "confidence": claim.confidence.value,
            "source_ids": claim.source_ids,
            "visualizable": claim.visualizable,
        }
        for claim in research.supported_claims()
    ]


def render_script_text(script: ScriptResult) -> str:
    lines = [f"# {script.title}", "", f"HOOK: {script.hook}", ""]
    for beat in script.beats:
        refs = f"  [{', '.join(beat.claim_ids)}]" if beat.claim_ids else ""
        lines.append(f"[{beat.id}] {beat.purpose}{refs}")
        lines.append(beat.text)
        lines.append("")
    lines += ["---", "", script.narration, ""]
    return "\n".join(lines)


def plan(context: RunContext) -> StagePlan:
    target, minimum, maximum = char_budget(context)
    return StagePlan(
        stage=STAGE_NAME,
        calls=[
            PlannedCall(
                kind="llm",
                provider=context.providers.llm.name,
                operation="writer",
                estimated_cost_usd=context.guard.estimate_llm_usd(
                    context.providers.llm.name,
                    3000,
                    context.settings.llm.max_output_tokens // 3,
                ),
                detail=f"narration target {target} chars ({minimum}-{maximum})",
            )
        ],
    )


async def run(context: RunContext) -> ScriptResult:
    research = require_research(context.workspace)
    settings = context.settings
    target, minimum, maximum = char_budget(context)

    def _validate(result: ScriptResult) -> list[QAIssue]:
        return check_script(result, settings) + check_script_traceability(result, research)

    script, prompt = await structured_call(
        context,
        prompt_name="writer",
        variables={
            "topic": context.project.topic,
            "content_type": context.project.content_type,
            "target_duration_sec": settings.script.target_duration_sec,
            "min_duration_sec": settings.script.min_duration_sec,
            "max_duration_sec": settings.script.max_duration_sec,
            "chars_per_sec": settings.script.chars_per_sec,
            "target_chars": target,
            "min_chars": minimum,
            "max_chars": maximum,
            "research_summary": research.summary,
            "claims_json": claims_payload(research),
        },
        schema=ScriptResult,
        validate=_validate,
    )

    script = script.model_copy(
        update={"prompt_version": prompt.version, "prompt_hash": prompt.hash}
    )
    save_script(context.workspace, script)
    atomic_write_text(context.workspace.script_txt, render_script_text(script))

    context.project.script_path = relative_to(context.workspace.script_json, context.workspace.root)
    context.project.prompt_versions["writer"] = prompt.version
    save_project(context.workspace, context.project)

    context.log.info(
        "script_completed",
        beats=len(script.beats),
        duration=script.target_duration_sec,
        claims=len(script.all_claim_ids()),
    )
    return script
