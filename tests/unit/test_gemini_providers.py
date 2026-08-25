"""The four Gemini providers: request shape, response walking, failure modes.

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
from pydantic import BaseModel

from shorts_factory.errors import ContentBlockedError, ProviderError
from shorts_factory.providers.image.gemini import (
    GeminiImageProvider,
    _closest_ratio,
    find_image_bytes,
)
from shorts_factory.providers.llm.gemini import GeminiLLMProvider, to_gemini_schema
from shorts_factory.providers.search.gemini import (
    GeminiSearchProvider,
    find_grounding_chunks,
    snippets_by_chunk,
)
from shorts_factory.providers.tts.gemini import GeminiTTSProvider, wav_from_pcm

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SEARCH_API_KEY", "IMAGE_API_KEY", "LLM_API_KEY", "TTS_API_KEY"):
        monkeypatch.setenv(name, "test-key")
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


# -- LLM -------------------------------------------------------------------


def llm_provider(handler, **kwargs) -> GeminiLLMProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiLLMProvider(model="gemini-2.5-flash", client=client, **kwargs)


class Inner(BaseModel):
    label: str
    score: float | None = None


class Outer(BaseModel):
    title: str
    items: list[Inner]
    note: str | None = None


def reply(text: str, **extra) -> dict:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    body.update(extra)
    return body


def test_the_schema_is_translated_into_geminis_subset() -> None:
    """Gemini has no $ref resolution and rejects several Pydantic keywords.

    Sending the raw model_json_schema() is a 400. Dropping the keywords costs
    nothing: the reply is validated against the real Pydantic model afterwards.
    """
    translated = to_gemini_schema(Outer.model_json_schema())
    flat = json.dumps(translated)

    assert "$ref" not in flat
    assert "$defs" not in flat
    assert "additionalProperties" not in flat
    # The structure has to survive the stripping.
    assert translated["properties"]["title"]["type"] == "string"
    assert translated["properties"]["items"]["items"]["properties"]["label"]["type"] == "string"


def test_an_optional_field_becomes_nullable_not_an_anyof() -> None:
    """Pydantic writes `X | None` as anyOf[..., null]; Gemini wants nullable."""
    translated = to_gemini_schema(Outer.model_json_schema())
    note = translated["properties"]["note"]
    assert note.get("nullable") is True
    assert "anyOf" not in note


def test_a_self_referential_schema_does_not_inline_forever() -> None:
    class Node(BaseModel):
        name: str
        child: Node | None = None

    Node.model_rebuild()
    translated = to_gemini_schema(Node.model_json_schema())
    assert isinstance(translated, dict)


async def test_llm_asks_for_json_and_returns_the_parsed_object() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json=reply(
                '{"title": "a", "items": []}',
                usageMetadata={"promptTokenCount": 11, "candidatesTokenCount": 7},
            ),
        )

    result = await llm_provider(handler).generate_json(
        system_prompt="be terse", user_prompt="write it", schema=Outer
    )

    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert result.data == {"title": "a", "items": []}
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7


async def test_a_rejected_schema_falls_back_to_plain_json_mode() -> None:
    """Losing schema enforcement beats failing the run; validation still happens."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "responseSchema" in body["generationConfig"]:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "Invalid JSON payload received. Unknown name responseSchema.",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            )
        return httpx.Response(200, json=reply('{"title": "a", "items": []}'))

    result = await llm_provider(handler).generate_json(
        system_prompt="be terse", user_prompt="write it", schema=Outer
    )
    assert len(bodies) == 2
    # The schema moves into the prompt so the model still knows the shape.
    assert (
        "Respond with JSON matching this schema"
        in bodies[-1]["systemInstruction"]["parts"][0]["text"]
    )
    assert result.data["title"] == "a"


async def test_a_code_fence_around_the_json_is_tolerated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply('```json\n{"title": "a", "items": []}\n```'))

    result = await llm_provider(handler).generate_json(
        system_prompt="s", user_prompt="u", schema=Outer
    )
    assert result.data["title"] == "a"


async def test_a_safety_block_is_reported_as_such() -> None:
    """An empty reply with a block reason is not "the API broke"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    with pytest.raises(ProviderError, match="refused"):
        await llm_provider(handler).generate_json(system_prompt="s", user_prompt="u", schema=Outer)


async def test_non_json_text_is_a_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply("I am afraid I cannot do that."))

    with pytest.raises(ProviderError, match="not JSON"):
        await llm_provider(handler).generate_json(system_prompt="s", user_prompt="u", schema=Outer)


# -- TTS -------------------------------------------------------------------


def tts_provider(handler, **kwargs) -> GeminiTTSProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiTTSProvider(model="gemini-2.5-flash-preview-tts", client=client, **kwargs)


def audio_reply(pcm: bytes) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/L16;rate=24000",
                                "data": base64.b64encode(pcm).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }


async def test_tts_writes_a_wav_that_ffprobe_can_read(tmp_path: Path) -> None:
    """Gemini returns headerless PCM; saved raw it is a file with no stream.

    The audio QA downstream would then report silence and blame the voice,
    which is a confusing way to discover a missing container.
    """
    pcm = b"\x01\x00" * 2400  # 0.1s of 16-bit mono at 24 kHz
    target = tmp_path / "voice.wav"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=audio_reply(pcm))

    result = await tts_provider(handler).synthesize("안녕하세요", target)

    written = Path(result.path).read_bytes()
    assert written[:4] == b"RIFF"
    assert written[8:12] == b"WAVE"
    assert written.endswith(pcm)
    assert result.characters == len("안녕하세요")


def test_the_wav_header_declares_the_right_rate_and_size() -> None:
    """A wrong rate plays the voice at the wrong pitch while durations pass."""
    import struct

    pcm = b"\x00\x01" * 100
    wav = wav_from_pcm(pcm, sample_rate=24000)

    (chunk_size,) = struct.unpack("<I", wav[4:8])
    channels, rate, byte_rate, block_align, bits = struct.unpack("<HHIIHH", wav[20:36])[1:]
    (data_size,) = struct.unpack("<I", wav[40:44])

    assert chunk_size == 36 + len(pcm)
    assert rate == 24000
    assert channels == 1
    assert bits == 16
    assert byte_rate == 24000 * 2
    assert block_align == 2
    assert data_size == len(pcm)


async def test_tts_sends_the_voice_and_the_style_instruction(tmp_path: Path) -> None:
    """Gemini takes delivery direction in the prompt, not as a parameter."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=audio_reply(b"\x00\x00" * 10))

    provider = tts_provider(handler, voice="Kore", style_instruction="차분하게 읽어주세요.")
    await provider.synthesize("지폐가 들어옵니다.", tmp_path / "a.wav")

    config = seen["body"]["generationConfig"]
    assert config["responseModalities"] == ["AUDIO"]
    assert config["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    spoken = seen["body"]["contents"][0]["parts"][0]["text"]
    assert "차분하게 읽어주세요." in spoken
    assert "지폐가 들어옵니다." in spoken


@pytest.mark.parametrize("payload", ["", "   "])
async def test_an_empty_audio_payload_is_an_error_not_a_silent_file(
    payload: str, tmp_path: Path
) -> None:
    """A zero-length wav passes every structural check and plays nothing.

    ffprobe reports a valid file with a stream of zero duration, so this has to
    fail here rather than surface later as "the narration is silent".
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"inlineData": {"data": payload}}]}}]},
        )

    with pytest.raises(ProviderError, match=r"no audio|empty audio"):
        await tts_provider(handler).synthesize("안녕", tmp_path / "a.wav")
    assert not (tmp_path / "a.wav").exists()
