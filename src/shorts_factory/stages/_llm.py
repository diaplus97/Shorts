"""Shared LLM call path: render prompt, call, validate, record cost.

Structured output is validated by Pydantic and retried exactly once with the
validation error fed back (spec section 65). Never in a loop.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from ..cost import CostEvent
from ..errors import PipelineValidationError
from ..pipeline.context import RunContext
from ..prompts import PromptPair, load_prompt
from ..providers import with_retry
from ..quality import QAIssue
from ..utils import atomic_write_text

#: Rough character-per-token ratio, used only for pre-call budget estimates.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(len(text) // _CHARS_PER_TOKEN, 1)


async def structured_call[T: BaseModel](
    context: RunContext,
    *,
    prompt_name: str,
    variables: dict[str, object],
    schema: type[T],
    validate: Callable[[T], list[QAIssue]] | None = None,
) -> tuple[T, PromptPair]:
    """Run one LLM stage and return a validated domain object.

    ``validate`` lets a stage reject a structurally valid but unusable result
    (wrong scene count, narration out of range) and give the model one more try
    with the specific complaints attached.
    """
    prompt = load_prompt(prompt_name)
    user_prompt = prompt.render_user(variables)
    atomic_write_text(context.workspace.stage_prompt_file(prompt_name), user_prompt)

    attempt_prompt = user_prompt
    last_error: str | None = None
    retries = max(context.settings.llm.structured_output_retries, 0)

    for attempt in range(retries + 1):
        response = await _call_provider(context, prompt, attempt_prompt, schema)
        try:
            result = schema.model_validate(response.data)
        except ValidationError as exc:
            last_error = f"schema validation failed:\n{exc}"
            context.log.warning(
                "llm_schema_invalid", stage=prompt_name, attempt=attempt + 1, error=str(exc)[:500]
            )
            attempt_prompt = _with_feedback(user_prompt, last_error)
            continue

        issues = validate(result) if validate else []
        blocking = [issue for issue in issues if issue.level == "error"]
        if not blocking:
            for issue in issues:
                context.log.warning("stage_warning", stage=prompt_name, issue=issue.render())
            return result, prompt

        last_error = "the result violated these rules:\n" + "\n".join(
            f"- {issue.code}: {issue.message}" for issue in blocking
        )
        context.log.warning(
            "llm_result_rejected", stage=prompt_name, attempt=attempt + 1, issues=len(blocking)
        )
        attempt_prompt = _with_feedback(user_prompt, last_error)

    raise PipelineValidationError(
        f"{prompt_name} stage could not produce a usable {schema.__name__} "
        f"after {retries + 1} attempts. Last problem:\n{last_error}"
    )


async def _call_provider(
    context: RunContext, prompt: PromptPair, user_prompt: str, schema: type[BaseModel]
):
    provider = context.providers.llm
    input_tokens = estimate_tokens(prompt.system + user_prompt)
    estimated = context.guard.estimate_llm_usd(
        provider.name, input_tokens, context.settings.llm.max_output_tokens // 2
    )
    context.guard.check_llm_call()
    context.guard.check_total(estimated, operation=f"llm:{prompt.name}")

    async def _invoke():
        return await provider.generate_json(
            system_prompt=prompt.system,
            user_prompt=user_prompt,
            schema=schema,
        )

    response = await with_retry(f"llm:{prompt.name}", _invoke, context.settings.retry)
    actual = context.guard.estimate_llm_usd(
        provider.name, response.usage.input_tokens, response.usage.output_tokens
    )
    context.tracker.record(
        CostEvent(
            kind="llm",
            provider=provider.name,
            operation=prompt.name,
            estimated_cost_usd=estimated,
            actual_cost_usd=actual,
            metadata={
                "model": response.model,
                "prompt_version": prompt.version,
                "prompt_hash": prompt.hash,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
    )
    context.log.info(
        "llm_call_completed",
        stage=prompt.name,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=actual,
    )
    return response


def _with_feedback(user_prompt: str, error: str) -> str:
    return (
        f"{user_prompt}\n\n"
        "The previous attempt was rejected. Fix exactly this and return the "
        f"corrected JSON object:\n{error}\n"
    )
