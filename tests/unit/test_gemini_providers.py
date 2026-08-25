"""Gemini search and Imagen: request shape, response walking, failure modes.

No network is touched -- every test drives the provider through an
``httpx.MockTransport``. That covers what this repository is answerable for:
what we send, what we do with what comes back, and which failures are worth
retrying. Whether Google's live API matches these shapes is covered by
`pytest -m live`, and by nothing here.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from shorts_factory.errors import ContentBlockedError, ProviderError
from shorts_factory.providers.image.gemini import (
    GeminiImageProvider,
    _closest_ratio,
    find_image_bytes,
)
from shorts_factory.providers.search.gemini import (
    GeminiSearchProvider,
    find_grounding_chunks,
    snippets_by_chunk,
)

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", "test-key")
    monkeypatch.setenv("IMAGE_API_KEY", "test-key")
    # The transports below are MockTransports, so nothing leaves the process.
    monkeypatch.setenv("ALLOW_LIVE_API_TESTS", "1")


def search_provider(handler, **kwargs) -> GeminiSearchProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs.setdefault("resolve_redirects", False)
    return GeminiSearchProvider(model="gemini-2.5-flash", client=client, **kwargs)


def image_provider(handler, **kwargs) -> GeminiImageProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiImageProvider(model="imagen-4.0-generate-001", client=client, **kwargs)


def grounded(*sources: tuple[str, str]) -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": "An answer nobody reads."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": uri, "title": title}} for uri, title in sources
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"text": "Notes are separated one at a time."},
                            "groundingChunkIndices": [0],
                        }
                    ],
                },
            }
        ]
    }


# -- search ----------------------------------------------------------------


async def test_search_asks_for_grounding_and_returns_the_sources() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=grounded(
                ("https://example.org/atm", "example.org"),
                ("https://standards.example/iso", "standards.example"),
            ),
        )

    hits = await search_provider(handler).search("how an ATM counts notes", max_results=5)

    assert seen["key"] == "test-key"
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    # Without the tool the reply is ungrounded prose and there are no citations.
    assert seen["body"]["tools"] == [{"google_search": {}}]
    assert "how an ATM counts notes" in seen["body"]["contents"][0]["parts"][0]["text"]

    assert [hit.url for hit in hits] == [
        "https://example.org/atm",
        "https://standards.example/iso",
    ]
    assert hits[0].snippet == "Notes are separated one at a time."
    assert hits[0].publisher == "example.org"


async def test_search_respects_max_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=grounded(*[(f"https://example.org/{i}", "example.org") for i in range(9)])
        )

    hits = await search_provider(handler).search("anything", max_results=3)
    assert len(hits) == 3


async def test_search_drops_duplicate_urls() -> None:
    """The same page cited twice is one source, not two."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=grounded(
                ("https://example.org/a", "example.org"),
                ("https://example.org/a", "example.org"),
                ("https://example.org/b", "example.org"),
            ),
        )

    hits = await search_provider(handler).search("anything", max_results=5)
    assert [hit.url for hit in hits] == ["https://example.org/a", "https://example.org/b"]


async def test_an_ungrounded_answer_yields_no_sources() -> None:
    """Prose with no citations must not become a source. Silence is correct.

    The fact lock refuses to spend on generation until every factual sentence
    cites something, so returning nothing fails the run loudly rather than
    letting an uncited claim through.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})

    assert await search_provider(handler).search("anything", max_results=5) == []


async def test_search_follows_googles_redirect_to_the_real_page() -> None:
    """A stored citation has to outlive the redirect it arrived as."""
    real = "https://www.example.org/the-actual-page"

    def handler(request: httpx.Request) -> httpx.Response:
        if "grounding-api-redirect" in str(request.url):
            return httpx.Response(302, headers={"location": real})
        if str(request.url) == real:
            return httpx.Response(200, text="the page")
        return httpx.Response(
            200,
            json=grounded(
                ("https://vertexaisearch.example/grounding-api-redirect/abc", "example.org")
            ),
        )

    provider = search_provider(handler, resolve_redirects=True)
    hits = await provider.search("anything", max_results=5)
    assert hits[0].url == real


async def test_a_redirect_that_cannot_be_followed_keeps_its_url() -> None:
    """Resolution is a nicety; losing the citation entirely is not acceptable."""
    redirect = "https://vertexaisearch.example/grounding-api-redirect/abc"

    def handler(request: httpx.Request) -> httpx.Response:
        if "grounding-api-redirect" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=grounded((redirect, "example.org")))

    provider = search_provider(handler, resolve_redirects=True)
    hits = await provider.search("anything", max_results=5)
    assert hits[0].url == redirect


async def test_search_marks_a_rate_limit_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    with pytest.raises(ProviderError) as caught:
        await search_provider(handler).search("anything", max_results=5)
    assert caught.value.retryable is True


def test_grounding_chunks_are_found_wherever_they_sit() -> None:
    """The nesting has moved between revisions; a shape change is not a KeyError."""
    body = {"a": {"b": {"groundingChunks": [{"web": {"uri": "https://example.org"}}]}}}
    assert len(find_grounding_chunks(body)) == 1
    assert find_grounding_chunks({"nothing": "here"}) == []
    assert snippets_by_chunk({"nothing": "here"}) == {}


# -- images ----------------------------------------------------------------


async def test_image_sends_a_prediction_and_writes_the_file(tmp_path: Path) -> None:
    seen: dict = {}
    target = tmp_path / "S01" / "source.png"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "predictions": [
                    {"bytesBase64Encoded": base64.b64encode(IMAGE_BYTES).decode("ascii")}
                ]
            },
        )

    result = await image_provider(handler).generate(
        prompt="a rubber roller", width=1080, height=1920, destination=target
    )

    assert seen["url"].endswith("/models/imagen-4.0-generate-001:predict")
    assert seen["body"]["instances"] == [{"prompt": "a rubber roller"}]
    assert seen["body"]["parameters"]["aspectRatio"] == "9:16"
    assert Path(result.path).read_bytes() == IMAGE_BYTES


async def test_image_passes_the_negative_prompt(tmp_path: Path) -> None:
    """The Style Bible's avoid list is the whole reason stills are on-model."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "predictions": [
                    {"bytesBase64Encoded": base64.b64encode(IMAGE_BYTES).decode("ascii")}
                ]
            },
        )

    await image_provider(handler).generate(
        prompt="a roller",
        width=1080,
        height=1920,
        destination=tmp_path / "a.png",
        negative_prompt="floating UI panels, neon",
    )
    assert seen["body"]["parameters"]["negativePrompt"] == "floating UI panels, neon"


async def test_image_drops_a_rejected_parameter_and_retries(tmp_path: Path) -> None:
    """The lesson Veo taught: a 400 names the field, so drop it rather than fail."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "personGeneration" in body["parameters"]:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "personGeneration is not supported by this model.",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "predictions": [
                    {"bytesBase64Encoded": base64.b64encode(IMAGE_BYTES).decode("ascii")}
                ]
            },
        )

    provider = image_provider(handler, person_generation="allow_adult")
    await provider.generate(
        prompt="a roller", width=1080, height=1920, destination=tmp_path / "a.png"
    )
    assert len(bodies) == 2
    assert "personGeneration" not in bodies[-1]["parameters"]
    # What we actually asked for has to survive the dropping.
    assert bodies[-1]["parameters"]["aspectRatio"] == "9:16"


async def test_a_refused_image_prompt_is_not_a_broken_response(tmp_path: Path) -> None:
    """A policy refusal must fall back, not be retried into more spending."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="blocked by our safety filters")

    with pytest.raises(ContentBlockedError):
        await image_provider(handler).generate(
            prompt="a roller", width=1080, height=1920, destination=tmp_path / "a.png"
        )


async def test_a_response_with_no_image_is_a_clear_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"predictions": []})

    with pytest.raises(ProviderError, match="no image"):
        await image_provider(handler).generate(
            prompt="a roller", width=1080, height=1920, destination=tmp_path / "a.png"
        )


def test_image_bytes_are_found_wherever_they_sit() -> None:
    assert find_image_bytes({"a": [{"bytesBase64Encoded": "AAA"}]}) == "AAA"
    assert find_image_bytes({"nothing": "here"}) is None


def test_pixel_size_maps_to_the_nearest_ratio() -> None:
    """Imagen takes a ratio, not a size, and 1080x1920 is exactly 9:16."""
    assert _closest_ratio(1080, 1920, "1:1") == "9:16"
    assert _closest_ratio(1920, 1080, "1:1") == "16:9"
    assert _closest_ratio(1024, 1024, "9:16") == "1:1"
    assert _closest_ratio(0, 0, "9:16") == "9:16"
