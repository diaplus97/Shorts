"""Veo 3 provider: request shape, response parsing and failure modes.

No network is touched: every test drives the provider through an
``httpx.MockTransport``. That covers the parts this repository can actually be
held responsible for — what we send, what we do with what comes back, and which
failures are worth retrying. Whether Google's live API matches this shape is
covered by `pytest -m live`, and by nothing here.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from shorts_factory.errors import ContentBlockedError, ProviderError
from shorts_factory.providers.video.veo import (
    VeoVideoProvider,
    find_block_reason,
    find_rejected_parameter,
    find_video_payload,
)

OPERATION = "models/veo-3.0-generate-001/operations/abc123"
VIDEO_BYTES = b"\x00\x01mp4-ish"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_API_KEY", "test-key")
    # The transport below is a MockTransport, so nothing leaves the process.
    # This only satisfies the guard against *accidental* live calls.
    monkeypatch.setenv("ALLOW_LIVE_API_TESTS", "1")


def provider(handler, **kwargs) -> VeoVideoProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return VeoVideoProvider(model="veo-3.0-generate-001", client=client, **kwargs)


def done_operation(**extra) -> dict:
    body = {
        "name": OPERATION,
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://files.invalid/v.mp4"}}]
            }
        },
    }
    body.update(extra)
    return body


# -- submit -----------------------------------------------------------------


async def test_submit_sends_the_documented_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": OPERATION})

    veo = provider(handler)
    job = await veo.submit(
        prompt="a banknote separating from a stack",
        duration_sec=3.3,
        aspect_ratio="9:16",
        negative_prompt="text, logos",
    )

    assert job == OPERATION
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/models/veo-3.0-generate-001:predictLongRunning")
    assert seen["key"] == "test-key"

    params = seen["body"]["parameters"]
    assert seen["body"]["instances"] == [{"prompt": "a banknote separating from a stack"}]
    assert params["aspectRatio"] == "9:16"
    assert params["negativePrompt"] == "text, logos"
    # 3.3s is not a length Veo returns; the request rounds up to 4.
    assert params["durationSeconds"] == 4
    # Veo 3.1 rejects generateAudio outright, so by default it is never sent.
    assert "generateAudio" not in params


async def test_generate_audio_is_sent_only_when_set() -> None:
    """Veo 3.1 answers HTTP 400 to the field, so ``None`` must omit it entirely.

    A model that does document the parameter still has to be able to receive it,
    hence the explicit-value case.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": OPERATION})

    for value, expected in ((None, None), (False, False), (True, True)):
        veo = provider(handler, generate_audio=value)
        await veo.submit(prompt="a stack of notes", duration_sec=4.0, aspect_ratio="9:16")
        params = seen["body"]["parameters"]
        if expected is None:
            assert "generateAudio" not in params
        else:
            assert params["generateAudio"] is expected


def invalid_argument(message: str) -> httpx.Response:
    return httpx.Response(
        400,
        json={"error": {"code": 400, "message": message, "status": "INVALID_ARGUMENT"}},
    )


async def test_a_rejected_tuning_parameter_is_dropped_and_resubmitted() -> None:
    """Both real rejections, in sequence, must resolve without failing the scene.

    veo-3.1-fast-generate-preview rejected generateAudio and personGeneration
    one per round trip. Each 400 names its field, so the request is retried
    without it rather than costing the caller another cycle.
    """
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        params = body["parameters"]
        if "generateAudio" in params:
            return invalid_argument("`generateAudio` isn't supported by this model.")
        if "personGeneration" in params:
            return invalid_argument("allow_adult for personGeneration is currently not supported.")
        return httpx.Response(200, json={"name": OPERATION})

    veo = provider(handler, generate_audio=False, person_generation="allow_adult")
    job = await veo.submit(prompt="a stack of notes", duration_sec=4.0, aspect_ratio="9:16")

    assert job == OPERATION
    assert len(bodies) == 3
    final = bodies[-1]["parameters"]
    assert "generateAudio" not in final
    assert "personGeneration" not in final
    # What we actually asked for has to survive the dropping.
    assert final["aspectRatio"] == "9:16"
    assert final["durationSeconds"] == 4
    assert final["resolution"] == "1080p"


async def test_a_rejection_of_a_load_bearing_parameter_still_fails() -> None:
    """Dropping aspectRatio would silently return a clip we cannot use."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return invalid_argument("aspectRatio 9:16 is not supported by this model.")

    veo = provider(handler)
    with pytest.raises(ProviderError):
        await veo.submit(prompt="a stack of notes", duration_sec=4.0, aspect_ratio="9:16")
    assert calls == 1


async def test_a_content_block_is_never_treated_as_a_bad_parameter() -> None:
    """A refusal must reach the caller as ContentBlockedError, not a retry loop."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return invalid_argument("The prompt was blocked by our safety filters.")

    veo = provider(handler, generate_audio=False)
    with pytest.raises(ContentBlockedError):
        await veo.submit(prompt="a stack of notes", duration_sec=4.0, aspect_ratio="9:16")
    assert calls == 1


def test_find_rejected_parameter_only_matches_what_we_sent() -> None:
    sent = {"aspectRatio": "9:16", "resolution": "1080p"}
    message = "Veo HTTP 400: `generateAudio` isn't supported by this model."
    # We never sent generateAudio, so this is a different problem entirely.
    assert find_rejected_parameter(message, sent) is None
    assert find_rejected_parameter("Veo HTTP 400: resolution is invalid", sent) == "resolution"
    # A 500 is transient, not a parameter problem.
    assert find_rejected_parameter("Veo HTTP 500: backend error", sent) is None


async def test_invalid_argument_is_not_retryable() -> None:
    """The real 400 Veo 3.1 returns for an unsupported field.

    It is not a content block and not transient: the same body fails the same
    way every time, so the scene loop must be told not to spend more attempts.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": (
                        "`generateAudio` isn't supported by this model. Please remove "
                        "it or refer to the Gemini API documentation for supported usage."
                    ),
                    "status": "INVALID_ARGUMENT",
                }
            },
        )

    veo = provider(handler, generate_audio=False)
    with pytest.raises(ProviderError) as caught:
        await veo.submit(prompt="a stack of notes", duration_sec=4.0, aspect_ratio="9:16")
    assert not isinstance(caught.value, ContentBlockedError)
    assert caught.value.retryable is False


async def test_extra_parameters_pass_through() -> None:
    """The escape hatch for a request field this code does not know about."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": OPERATION})

    veo = provider(handler, extra_parameters={"seed": 42, "resolution": "720p"})
    await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")

    assert seen["body"]["parameters"]["seed"] == 42
    # An explicit override wins over the configured default.
    assert seen["body"]["parameters"]["resolution"] == "720p"


async def test_submit_without_an_operation_name_is_an_error() -> None:
    veo = provider(lambda request: httpx.Response(200, json={"ok": True}))
    with pytest.raises(ProviderError, match="no operation name"):
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")


async def test_a_missing_api_key_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_API_KEY", raising=False)
    veo = provider(lambda request: httpx.Response(200, json={"name": OPERATION}))
    with pytest.raises(ProviderError, match="VIDEO_API_KEY"):
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")


# -- duration ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0.5, 4.0), (4.0, 4.0), (4.1, 6.0), (6.0, 6.0), (7.2, 8.0), (20.0, 8.0)],
)
def test_snap_duration_rounds_up_to_an_accepted_length(requested, expected) -> None:
    """Rounding up: a short clip cannot be padded, but a long one can be trimmed."""
    veo = provider(lambda request: httpx.Response(200), allowed_durations=(4.0, 6.0, 8.0))
    assert veo.snap_duration(requested) == expected


def test_no_allowed_durations_means_continuous() -> None:
    veo = provider(lambda request: httpx.Response(200), allowed_durations=())
    assert veo.snap_duration(3.3) == 3.3


# -- status -----------------------------------------------------------------


async def test_a_running_job_reports_processing() -> None:
    veo = provider(lambda request: httpx.Response(200, json={"name": OPERATION, "done": False}))
    state = await veo.status(OPERATION)
    assert state.state == "processing"
    assert not state.blocked


async def test_a_finished_job_reports_completed() -> None:
    veo = provider(lambda request: httpx.Response(200, json=done_operation()))
    state = await veo.status(OPERATION)
    assert state.state == "completed"
    assert state.progress == 1.0


async def test_an_operation_error_reports_failed() -> None:
    body = {"name": OPERATION, "done": True, "error": {"code": 13, "message": "internal"}}
    veo = provider(lambda request: httpx.Response(200, json=body))
    state = await veo.status(OPERATION)
    assert state.state == "failed"
    assert "internal" in state.error
    assert not state.blocked


async def test_a_filtered_result_is_marked_blocked() -> None:
    """A refusal must be distinguishable from a crash, or we retry and pay twice."""
    body = {
        "name": OPERATION,
        "done": True,
        "response": {"generateVideoResponse": {"raiMediaFilteredReason": "unsafe content"}},
    }
    veo = provider(lambda request: httpx.Response(200, json=body))
    state = await veo.status(OPERATION)
    assert state.state == "failed"
    assert state.blocked
    assert "unsafe content" in state.error


async def test_a_finished_job_with_no_video_is_failed_not_completed() -> None:
    body = {"name": OPERATION, "done": True, "response": {"generateVideoResponse": {}}}
    veo = provider(lambda request: httpx.Response(200, json=body))
    state = await veo.status(OPERATION)
    assert state.state == "failed"
    assert "no video" in state.error


# -- download ---------------------------------------------------------------


async def test_download_follows_the_uri(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "files.invalid" in str(request.url):
            assert request.headers.get("x-goog-api-key") == "test-key"
            return httpx.Response(200, content=VIDEO_BYTES)
        return httpx.Response(200, json=done_operation())

    veo = provider(handler)
    result = await veo.download(OPERATION, tmp_path / "source.mp4")

    assert Path(result.path).read_bytes() == VIDEO_BYTES
    assert result.model == "veo-3.0-generate-001"


async def test_download_accepts_inline_bytes(tmp_path: Path) -> None:
    body = {
        "name": OPERATION,
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {"video": {"bytesBase64Encoded": base64.b64encode(VIDEO_BYTES).decode()}}
                ]
            }
        },
    }
    veo = provider(lambda request: httpx.Response(200, json=body))
    result = await veo.download(OPERATION, tmp_path / "source.mp4")
    assert Path(result.path).read_bytes() == VIDEO_BYTES


async def test_an_empty_download_is_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "files.invalid" in str(request.url):
            return httpx.Response(200, content=b"")
        return httpx.Response(200, json=done_operation())

    veo = provider(handler)
    with pytest.raises(ProviderError, match="empty file"):
        await veo.download(OPERATION, tmp_path / "source.mp4")


# -- http failures ----------------------------------------------------------


async def test_rate_limiting_is_retryable() -> None:
    veo = provider(lambda request: httpx.Response(429, text="quota exceeded"))
    with pytest.raises(ProviderError) as caught:
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")
    assert caught.value.retryable


async def test_server_errors_are_retryable() -> None:
    veo = provider(lambda request: httpx.Response(503, text="unavailable"))
    with pytest.raises(ProviderError) as caught:
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")
    assert caught.value.retryable


async def test_a_bad_request_is_not_retryable() -> None:
    veo = provider(lambda request: httpx.Response(400, text="invalid aspectRatio"))
    with pytest.raises(ProviderError) as caught:
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="1:1")
    assert not caught.value.retryable
    assert not isinstance(caught.value, ContentBlockedError)


async def test_a_safety_rejection_is_content_blocked() -> None:
    veo = provider(lambda request: httpx.Response(400, text="blocked by safety filters"))
    with pytest.raises(ContentBlockedError):
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")


async def test_non_json_is_reported_clearly() -> None:
    veo = provider(lambda request: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(ProviderError, match="non-JSON"):
        await veo.submit(prompt="x", duration_sec=8, aspect_ratio="9:16")


# -- response walking -------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "u"}}]}}},
        {"response": {"generatedVideos": [{"video": {"uri": "u"}}]}},
        {"response": {"videos": [{"uri": "u"}]}},
        {"result": {"deeply": {"nested": {"video": {"uri": "u"}}}}},
    ],
)
def test_the_video_is_found_across_response_shapes(body) -> None:
    """The nesting has moved between Veo revisions; a shape change must not KeyError."""
    payload = find_video_payload(body)
    assert payload is not None
    assert payload.get("uri") == "u"


def test_no_video_returns_none() -> None:
    assert find_video_payload({"response": {"generateVideoResponse": {}}}) is None


def test_block_reasons_are_found_wherever_they_sit() -> None:
    assert find_block_reason({"a": {"raiFilteredReason": "x"}}) == "raiFilteredReason: x"
    assert find_block_reason({"a": [{"blockedReason": "y"}]}) == "blockedReason: y"
    assert find_block_reason({"a": {"b": 1}}) is None


def test_retired_model_ids_are_refused() -> None:
    """Veo 2 and Veo 3 were shut down on 2026-06-30; a 404 mid-run is a worse teacher."""
    from shorts_factory.config import load_config
    from shorts_factory.errors import ConfigError
    from shorts_factory.providers.registry import RETIRED_VIDEO_MODELS, build_video

    config = load_config(Path(__file__).resolve().parents[2] / "config", load_env=False)
    config.settings.providers.video = "veo"
    config.settings.video.allowed_durations = [4, 6, 8]

    assert "veo-3.0-generate-001" in RETIRED_VIDEO_MODELS
    config.settings.video.model = "veo-3.0-generate-001"
    with pytest.raises(ConfigError, match="shut down"):
        build_video(config)

    config.settings.video.model = "veo-3.1-fast-generate-preview"
    assert build_video(config).model == "veo-3.1-fast-generate-preview"


def test_veo_needs_explicit_clip_lengths() -> None:
    from shorts_factory.config import load_config
    from shorts_factory.errors import ConfigError
    from shorts_factory.providers.registry import build_video

    config = load_config(Path(__file__).resolve().parents[2] / "config", load_env=False)
    config.settings.providers.video = "veo"
    config.settings.video.model = "veo-3.1-fast-generate-preview"
    config.settings.video.allowed_durations = []
    with pytest.raises(ConfigError, match="allowed_durations"):
        build_video(config)
