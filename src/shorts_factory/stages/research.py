"""Research stage: topic -> source-backed claims (spec sections 11-12)."""

from __future__ import annotations

from ..cost import CostEvent
from ..domain import Claim, ResearchResult, SourceRef, utcnow
from ..pipeline.checkpoint import save_project, save_research
from ..pipeline.context import RunContext
from ..providers import SearchHit, with_retry
from ..quality import QAIssue, check_research
from ..utils import atomic_write_text, relative_to
from ._llm import structured_call
from ._plan import PlannedCall, StagePlan

STAGE_NAME = "research"

_QUERY_SUFFIXES = ("", " 원리", " 구조", " 작동 과정", " 내부", " 시스템")


def build_queries(topic: str, max_queries: int) -> list[str]:
    """Deterministic query set. No LLM needed to ask the obvious questions."""
    queries = [f"{topic}{suffix}".strip() for suffix in _QUERY_SUFFIXES]
    seen: set[str] = set()
    unique = []
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            unique.append(query)
    return unique[:max_queries]


async def gather_sources(context: RunContext, queries: list[str]) -> list[SourceRef]:
    """Run every query and fold the hits into a de-duplicated source list."""
    provider = context.providers.search
    per_query = context.settings.search.max_results_per_query
    estimated = context.guard.estimate_search_usd(provider.name, len(queries))
    context.guard.check_total(estimated, operation="search")

    by_url: dict[str, SearchHit] = {}
    for query in queries:

        async def _invoke(q: str = query):
            return await provider.search(q, max_results=per_query)

        hits = await with_retry(f"search:{query}", _invoke, context.settings.retry)
        for hit in hits:
            by_url.setdefault(hit.url, hit)

    context.tracker.record(
        CostEvent(
            kind="search",
            provider=provider.name,
            operation="search",
            estimated_cost_usd=estimated,
            actual_cost_usd=estimated,
            metadata={"queries": len(queries), "unique_sources": len(by_url)},
        )
    )

    accessed = utcnow().date().isoformat()
    return [
        SourceRef(
            id=f"S{index:02d}",
            title=hit.title,
            url=hit.url,
            publisher=hit.publisher,
            published_at=hit.published_at,
            accessed_at=accessed,
        )
        for index, hit in enumerate(by_url.values(), start=1)
    ]


def enforce_source_integrity(result: ResearchResult, sources: list[SourceRef]) -> ResearchResult:
    """Drop anything the retrieved sources do not actually back.

    The model is told not to invent sources; this makes it structurally
    impossible for an invented one to survive into the script.
    """
    known = {source.id for source in sources}
    kept: list[Claim] = []
    dropped: list[str] = []
    for claim in result.claims:
        valid_ids = [sid for sid in claim.source_ids if sid in known]
        if valid_ids:
            kept.append(claim.model_copy(update={"source_ids": valid_ids}))
        else:
            dropped.append(claim.statement)

    return result.model_copy(
        update={
            "claims": kept,
            "sources": sources,
            "unsafe_or_uncertain_claims": [*result.unsafe_or_uncertain_claims, *dropped],
        }
    )


def render_markdown(result: ResearchResult) -> str:
    lines = [f"# {result.topic}", "", result.summary, "", "## Claims", ""]
    for claim in result.claims:
        refs = ", ".join(claim.source_ids) or "—"
        flag = " (visualizable)" if claim.visualizable else ""
        lines.append(
            f"- **{claim.id}** [{claim.confidence}]{flag} {claim.statement}  \n  sources: {refs}"
        )
    lines += ["", "## Sources", ""]
    for source in result.sources:
        publisher = f" — {source.publisher}" if source.publisher else ""
        lines.append(f"- **{source.id}** [{source.title}]({source.url}){publisher}")
    if result.unresolved_questions:
        lines += ["", "## Unresolved", ""]
        lines += [f"- {item}" for item in result.unresolved_questions]
    if result.unsafe_or_uncertain_claims:
        lines += ["", "## Dropped or uncertain", ""]
        lines += [f"- {item}" for item in result.unsafe_or_uncertain_claims]
    return "\n".join(lines) + "\n"


def plan(context: RunContext) -> StagePlan:
    settings = context.settings
    queries = build_queries(context.project.topic, settings.search.max_queries)
    return StagePlan(
        stage=STAGE_NAME,
        calls=[
            PlannedCall(
                kind="search",
                provider=context.providers.search.name,
                operation="search",
                count=len(queries),
                estimated_cost_usd=context.guard.estimate_search_usd(
                    context.providers.search.name, len(queries)
                ),
                detail=f"queries: {queries}",
            ),
            PlannedCall(
                kind="llm",
                provider=context.providers.llm.name,
                operation="research",
                estimated_cost_usd=context.guard.estimate_llm_usd(
                    context.providers.llm.name, 4000, settings.llm.max_output_tokens // 2
                ),
                detail=f"target claims: {settings.research.target_claims}",
            ),
        ],
    )


async def run(context: RunContext) -> ResearchResult:
    settings = context.settings
    content_type = context.config.content_type(context.project.content_type)
    queries = build_queries(context.project.topic, settings.search.max_queries)
    sources = await gather_sources(context, queries)
    context.log.info("research_sources_gathered", queries=len(queries), sources=len(sources))

    def _validate(result: ResearchResult) -> list[QAIssue]:
        return check_research(enforce_source_integrity(result, sources))

    result, prompt = await structured_call(
        context,
        prompt_name="research",
        variables={
            "topic": context.project.topic,
            "content_type": context.project.content_type,
            "content_type_label": content_type.label,
            "content_type_description": content_type.description.strip(),
            "target_claims": settings.research.target_claims,
            "sources_json": [source.model_dump(exclude_none=True) for source in sources],
        },
        schema=ResearchResult,
        validate=_validate,
    )

    result = enforce_source_integrity(result, sources)
    result = result.model_copy(
        update={"prompt_version": prompt.version, "prompt_hash": prompt.hash}
    )

    save_research(context.workspace, result)
    atomic_write_text(context.workspace.research_md, render_markdown(result))

    context.project.research_path = relative_to(
        context.workspace.research_json, context.workspace.root
    )
    context.project.prompt_versions["research"] = prompt.version
    save_project(context.workspace, context.project)

    context.log.info("research_completed", claims=len(result.claims), sources=len(result.sources))
    return result
