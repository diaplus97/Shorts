"""OpenAI Chat Completions provider with JSON-schema structured output.

This is the one real LLM provider (spec section 22: implement exactly one per
kind). It is never exercised by the default test suite -- see
``assert_live_calls_allowed``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel

from ...errors import ProviderError
from ..base import (
    LLMJsonResponse,
    LLMUsage,
    assert_live_calls_allowed,
    require_secret,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"

#: JSON Schema keywords that strict structured output does not accept.
#: Pydantic emits them, and our Pydantic models re-validate the response anyway.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "default",
        "title",
        "examples",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "multipleOf",
        "$comment",
    }
)


def to_strict_schema(schema: Any) -> Any:
    """Rewrite a Pydantic JSON schema into the strict structured-output dialect.

    Strict mode requires every object to forbid extra properties and to list
    every property as required, and it rejects the annotation keywords above.
    """
    if isinstance(schema, list):
        return [to_strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned = {
        key: to_strict_schema(value)
        for key, value in schema.items()
        if key not in _UNSUPPORTED_KEYWORDS
    }
    if cleaned.get("type") == "object" or "properties" in cleaned:
        properties = cleaned.get("properties", {})
        cleaned["properties"] = properties
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(properties)
    return cleaned


class OpenAILLMProvider:
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.4,
        max_output_tokens: int = 8000,
        timeout_sec: float = 120.0,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_sec = timeout_sec
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> LLMJsonResponse:
        assert_live_calls_allowed(self.name)
        api_key = require_secret("OPENAI_API_KEY", self.name)
        strict_schema = to_strict_schema(schema.model_json_schema())

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": strict_schema,
                },
            },
        }

        try:
            body = await self._post(payload, api_key)
        except ProviderError as exc:
            # Older or smaller models may not support json_schema. Fall back to
            # plain JSON mode with the schema inlined in the system prompt.
            if "response_format" not in str(exc) and "json_schema" not in str(exc):
                raise
            fallback = dict(payload)
            fallback["response_format"] = {"type": "json_object"}
            fallback["messages"] = [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\nRespond with JSON matching this schema "
                        f"exactly:\n{json.dumps(strict_schema, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ]
            body = await self._post(fallback, api_key)

        try:
            choice = body["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"unexpected OpenAI response shape: {json.dumps(body)[:400]}",
                provider=self.name,
            ) from exc

        if choice.get("finish_reason") == "length":
            raise ProviderError(
                "OpenAI response was truncated; raise llm.max_output_tokens",
                provider=self.name,
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"OpenAI returned non-JSON content: {text[:400]}", provider=self.name
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError("OpenAI returned JSON that is not an object", provider=self.name)

        usage = body.get("usage") or {}
        return LLMJsonResponse(
            data=data,
            model=body.get("model", self.model),
            usage=LLMUsage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
            raw_text=text,
        )

    async def _post(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"OpenAI request timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenAI transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise ProviderError(
                f"OpenAI HTTP {response.status_code}: {response.text[:500]}",
                provider=self.name,
                retryable=retryable,
            )
        return response.json()
