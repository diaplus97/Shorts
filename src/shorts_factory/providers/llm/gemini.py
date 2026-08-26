"""Structured JSON generation over the Gemini API.

    POST models/{model}:generateContent
      generationConfig.responseMimeType = "application/json"
      generationConfig.responseSchema  = the Pydantic model's schema

Every stage that calls an LLM here validates the reply against a Pydantic
model, so the reply has to be JSON and it has to fit. Asking the API to enforce
the schema is cheaper than discovering a mismatch after paying for the call.

Gemini's schema dialect is a subset of JSON Schema, and it rejects several
keywords Pydantic emits -- ``$defs``, ``$ref``, ``additionalProperties``,
``const``. ``to_gemini_schema`` inlines and strips those. When the API still
refuses the schema, the request falls back to plain JSON mode with the schema
in the prompt, which is what the OpenAI adapter does for the same reason.

**Verified against the live API.** It has written scripts across several
paid runs. Model ids still move; run
``scripts/list_gemini_models.py --kind llm`` to see what this key can reach.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel

from ...errors import ProviderError
from ...utils import get_logger
from ..base import (
    LLMJsonResponse,
    LLMUsage,
    assert_live_calls_allowed,
    is_retryable_429,
    require_secret,
)

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: JSON Schema keywords Gemini's subset does not accept.
_UNSUPPORTED_KEYWORDS = (
    "additionalProperties",
    "$schema",
    "$defs",
    "definitions",
    "discriminator",
    "const",
    "examples",
    "default",
    "title",
)


class GeminiLLMProvider:
    name = "gemini"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0.4,
        max_output_tokens: int = 8000,
        timeout_sec: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_sec = timeout_sec
        self._client = client

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> LLMJsonResponse:
        assert_live_calls_allowed(self.name)
        gemini_schema = to_gemini_schema(schema.model_json_schema())

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": gemini_schema,
            },
        }

        try:
            body = await self._post(payload)
        except ProviderError as exc:
            # A schema Gemini's subset cannot express is not worth failing the
            # run over: the reply is validated against the Pydantic model
            # regardless, so JSON mode with the schema in the prompt still ends
            # in the same place, one retry later at worst.
            if "responseSchema" not in str(exc) and "schema" not in str(exc).lower():
                raise
            log.warning("gemini_schema_rejected", model=self.model, detail=str(exc)[:200])
            config = {k: v for k, v in payload["generationConfig"].items() if k != "responseSchema"}
            fallback = {**payload, "generationConfig": config}
            fallback["systemInstruction"] = {
                "parts": [
                    {
                        "text": (
                            f"{system_prompt}\n\nRespond with JSON matching this schema "
                            f"exactly:\n{json.dumps(gemini_schema, ensure_ascii=False)}"
                        )
                    }
                ]
            }
            body = await self._post(fallback)

        text = find_text(body)
        if not text:
            if reason := blocked_reason(body):
                raise ProviderError(f"Gemini refused the request: {reason}", provider=self.name)
            raise ProviderError(f"Gemini returned no text: {str(body)[:300]}", provider=self.name)

        try:
            data = json.loads(strip_code_fence(text))
        except ValueError as exc:
            raise ProviderError(
                f"Gemini returned text that is not JSON: {text[:300]}", provider=self.name
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                f"Gemini returned JSON that is not an object: {text[:200]}", provider=self.name
            )

        return LLMJsonResponse(data=data, model=self.model, usage=usage_from(body), raw_text=text)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = require_secret("LLM_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Gemini request timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Gemini transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini HTTP {response.status_code}: {response.text[:400]}",
                provider=self.name,
                retryable=(response.status_code == 429 and is_retryable_429(response.text))
                or response.status_code >= 500,
            )
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"Gemini returned non-JSON: {response.text[:300]}", provider=self.name
            ) from exc


def to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A Pydantic JSON schema in the subset Gemini accepts.

    ``$ref``/``$defs`` are inlined because Gemini has no reference resolution,
    and the keywords it rejects are dropped. Losing them costs nothing here:
    the reply is validated against the real Pydantic model afterwards, which is
    where a schema violation is actually caught.
    """
    defs = schema.get("$defs") or schema.get("definitions") or {}
    return _clean(schema, defs, depth=0)


def _clean(node: Any, defs: dict[str, Any], *, depth: int) -> Any:
    # A self-referential model would otherwise inline forever.
    if depth > 12:
        return {"type": "object"}
    if isinstance(node, list):
        return [_clean(item, defs, depth=depth + 1) for item in node]
    if not isinstance(node, dict):
        return node

    if ref := node.get("$ref"):
        name = str(ref).rsplit("/", 1)[-1]
        target = defs.get(name)
        if target is None:
            return {"type": "object"}
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _clean(merged, defs, depth=depth + 1)

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        # Keys under "properties" are field names, not schema keywords. Filtering
        # them as keywords deletes any field called title, default or const --
        # and ScriptResult has a field called title, so the writer's schema came
        # out without it.
        if key == "properties" and isinstance(value, dict):
            out[key] = {
                field: _clean(subschema, defs, depth=depth + 1)
                for field, subschema in value.items()
            }
            continue
        # anyOf carrying a null is Pydantic's `X | None`; Gemini expresses that
        # as nullable on the branch that is not null.
        if key == "anyOf" and isinstance(value, list):
            branches = [b for b in value if not (isinstance(b, dict) and b.get("type") == "null")]
            if len(branches) == 1:
                cleaned = _clean(branches[0], defs, depth=depth + 1)
                if isinstance(cleaned, dict):
                    cleaned["nullable"] = True
                    out.update(cleaned)
                    continue
            out["anyOf"] = [_clean(b, defs, depth=depth + 1) for b in branches or value]
            continue
        out[key] = _clean(value, defs, depth=depth + 1)
    return out


def strip_code_fence(text: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
    return body.rsplit("```", 1)[0].strip()


def find_text(body: Any) -> str:
    """Concatenate the text parts of the first candidate."""
    candidates = body.get("candidates") if isinstance(body, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return ""
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))


def blocked_reason(body: Any) -> str | None:
    """Why an empty reply was empty, when the API says so."""
    if not isinstance(body, dict):
        return None
    feedback = body.get("promptFeedback") or {}
    if reason := feedback.get("blockReason"):
        return str(reason)
    candidates = body.get("candidates") or []
    if candidates and isinstance(candidates[0], dict):
        finish = candidates[0].get("finishReason")
        if finish and finish not in ("STOP", "MAX_TOKENS"):
            return str(finish)
    return None


def usage_from(body: Any) -> LLMUsage:
    meta = body.get("usageMetadata") if isinstance(body, dict) else None
    if not isinstance(meta, dict):
        return LLMUsage()
    return LLMUsage(
        input_tokens=int(meta.get("promptTokenCount") or 0),
        output_tokens=int(meta.get("candidatesTokenCount") or 0),
    )
