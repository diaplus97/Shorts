"""Fact traceability and the fact lock (spec sections 34-35).

Nothing paid runs until every factual sentence in the script traces back to a
sourced claim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..domain import ResearchResult, ScenePlan, ScriptResult
from .report import QAIssue, error, warning

#: Beat purposes that are allowed to carry no claim id.
NON_FACTUAL_PURPOSES = frozenset({"hook", "closing", "transition", "question"})


class FactCheckFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    reason: str


class FactCheckReport(BaseModel):
    """Schema the QA prompt asks the LLM to fill in (spec section 36.2)."""

    model_config = ConfigDict(extra="forbid")

    unsupported_sentences: list[FactCheckFinding] = Field(default_factory=list)
    overreaching_sentences: list[FactCheckFinding] = Field(default_factory=list)
    verdict: Literal["pass", "fail"] = "pass"
    notes: str | None = None


def check_research(research: ResearchResult) -> list[QAIssue]:
    issues: list[QAIssue] = []
    if not research.claims:
        issues.append(error("research_empty", "research produced no claims"))
    dangling = research.dangling_source_ids()
    if dangling:
        issues.append(
            error("research_dangling_sources", f"claims cite unknown source ids: {dangling}")
        )
    unsupported = [claim.id for claim in research.claims if not claim.is_supported]
    if unsupported:
        issues.append(
            warning(
                "research_unsupported_claims",
                f"claims with no source will be excluded from the script: {unsupported}",
            )
        )
    if not research.supported_claims():
        issues.append(error("research_no_supported_claims", "no claim cites a source"))
    return issues


def check_script_traceability(script: ScriptResult, research: ResearchResult) -> list[QAIssue]:
    """Spec section 11: a factual claim with no source may not reach the script."""
    issues: list[QAIssue] = []
    known = {claim.id: claim for claim in research.claims}

    for claim_id in sorted(script.all_claim_ids()):
        claim = known.get(claim_id)
        if claim is None:
            issues.append(
                error("script_unknown_claim", f"script references unknown claim '{claim_id}'")
            )
        elif not claim.is_supported:
            issues.append(
                error(
                    "script_unsourced_claim",
                    f"claim '{claim_id}' has no source and must not be used in the script",
                )
            )

    for beat in script.beats:
        if beat.claim_ids:
            continue
        if beat.purpose in NON_FACTUAL_PURPOSES:
            continue
        issues.append(
            warning(
                "beat_unsourced",
                f"beat {beat.id} ('{beat.purpose}') states something with no claim id",
            )
        )
    return issues


def check_scene_traceability(plan: ScenePlan, research: ResearchResult) -> list[QAIssue]:
    issues: list[QAIssue] = []
    known = {claim.id for claim in research.claims}
    for scene in plan.scenes:
        unknown = [cid for cid in scene.claim_ids if cid not in known]
        if unknown:
            issues.append(
                error("scene_unknown_claim", f"references unknown claims {unknown}", scene.id)
            )
    return issues


def affected_scenes(plan: ScenePlan, claim_id: str) -> list[str]:
    """Which scenes would need to change if a claim turns out to be wrong."""
    return [scene.id for scene in plan.scenes if claim_id in scene.claim_ids]


def fact_lock_issues(script: ScriptResult, research: ResearchResult) -> list[QAIssue]:
    """The gate that must pass before any paid generation runs."""
    return check_research(research) + check_script_traceability(script, research)
