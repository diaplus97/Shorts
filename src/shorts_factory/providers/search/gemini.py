"""Search backed by Gemini's Google Search grounding.

    POST models/{model}:generateContent  with tools: [{"google_search": {}}]

The research stage needs sources it can cite, and the only implementation was a
mock whose URLs used the reserved ``.invalid`` TLD. So every fact in every
Short traced to a citation that could not exist -- the fact lock was checking
that claims *had* sources, never that the sources were real.

This closes that with the key the video provider already uses: one Gemini call
per query, grounded against Google Search, returning the pages the model
actually consulted.

**Known limitation, and it is a real one.** The URIs Google returns are
redirect links on its own domain, not the publisher's URL. They resolve to the
source in a browser, and they expire. ``resolve_redirects`` follows each one to
its destination so what is stored is the real address, at the cost of a HEAD
request per hit; turned off, citations are honest about being redirects but do
not survive being written down.

**This provider has not been run against the live API.** The request and
response shapes come from documentation, model ids move, and
``scripts/list_gemini_models.py`` will tell you what this key can actually see.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from ...errors import ProviderError
from ...utils import get_logger
from ..base import SearchHit, assert_live_calls_allowed, require_secret

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Asks for sources rather than an answer. The grounding metadata is what this
#: provider reads; the prose reply is discarded.
_INSTRUCTION = (
    "Find authoritative sources that explain: {query}\n\n"
    "Prefer manufacturer documentation, standards bodies, public agencies and "
    "engineering references over blogs and news summaries. Answer in two or "
    "three sentences; the citations matter, not the prose."
)


class GeminiSearchProvider:
    name = "gemini"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: float = 60.0,
        resolve_redirects: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.resolve_redirects = resolve_redirects
        self._client = client

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        assert_live_calls_allowed(self.name)
        body = await self._request(
            f"{self.base_url}/models/{self.model}:generateContent",
            {
                "contents": [{"parts": [{"text": _INSTRUCTION.format(query=query)}]}],
                "tools": [{"google_search": {}}],
            },
        )

        chunks = find_grounding_chunks(body)
        if not chunks:
            log.warning("gemini_search_no_grounding", query=query[:80], model=self.model)
            return []

        snippets = snippets_by_chunk(body)
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for index, chunk in enumerate(chunks[:max_results]):
            web = chunk.get("web") or {}
            uri = str(web.get("uri") or "").strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            title = str(web.get("title") or "").strip() or "(untitled)"
            hits.append(
                SearchHit(
                    title=title,
                    url=uri,
                    snippet=snippets.get(index, ""),
                    # Google returns the publisher's domain as the chunk title
                    # for most results, which is the best publisher signal here.
                    publisher=web.get("domain") or _domain_of(title) or None,
                )
            )

        if self.resolve_redirects:
            await self._resolve(hits)
        return hits

    async def _resolve(self, hits: list[SearchHit]) -> None:
        """Replace Google's redirect URIs with where they actually point.

        A stored citation has to survive the redirect expiring. Failure here is
        not fatal -- the redirect still resolves today -- so a hit that cannot
        be followed keeps the URL it came with.
        """
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            for hit in hits:
                if "grounding-api-redirect" not in hit.url:
                    continue
                try:
                    response = await client.get(hit.url, follow_redirects=True)
                except httpx.HTTPError as exc:
                    log.warning("gemini_search_redirect_failed", url=hit.url[:80], error=str(exc))
                    continue
                final = str(response.url)
                if final and "grounding-api-redirect" not in final:
                    hit.url = final
                    hit.publisher = hit.publisher or _domain_of(final)
        finally:
            if owns:
                await client.aclose()

    async def _request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = require_secret("SEARCH_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Gemini search timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Gemini search transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini search HTTP {response.status_code}: {response.text[:400]}",
                provider=self.name,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"Gemini search returned non-JSON: {response.text[:300]}", provider=self.name
            ) from exc


def _domain_of(value: str) -> str | None:
    host = urlparse(value if "//" in value else f"//{value}").netloc
    return host.removeprefix("www.") or None


def find_grounding_chunks(node: Any) -> list[dict[str, Any]]:
    """The sources, wherever ``groundingChunks`` sits in the response.

    Walked rather than indexed: the nesting around groundingMetadata has moved
    between API revisions, and a shape change should degrade to "no sources"
    rather than a KeyError halfway through a run.
    """
    if isinstance(node, dict):
        found = node.get("groundingChunks")
        if isinstance(found, list):
            return [chunk for chunk in found if isinstance(chunk, dict)]
        for value in node.values():
            if nested := find_grounding_chunks(value):
                return nested
    elif isinstance(node, list):
        for item in node:
            if nested := find_grounding_chunks(item):
                return nested
    return []


def snippets_by_chunk(body: Any) -> dict[int, str]:
    """Map each source to the sentence it supported.

    ``groundingSupports`` ties a span of the answer to the chunks backing it,
    which is the closest thing the API gives to a search snippet.
    """
    supports = _find_key(body, "groundingSupports")
    if not isinstance(supports, list):
        return {}
    out: dict[int, str] = {}
    for support in supports:
        if not isinstance(support, dict):
            continue
        text = str((support.get("segment") or {}).get("text") or "").strip()
        if not text:
            continue
        for index in support.get("groundingChunkIndices") or []:
            if isinstance(index, int):
                out.setdefault(index, text)
    return out


def _find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            if (found := _find_key(value, key)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := _find_key(item, key)) is not None:
                return found
    return None
