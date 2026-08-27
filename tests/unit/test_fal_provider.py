"""The fal.ai adapter, against a mocked transport.

fal exists in this pipeline for one reason: Veo 3.1 Standard at $0.40/s was the
most expensive option on the market and it was the default, which priced a
65-second Short at about $26. Everything here is checked without a live call.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from shorts_factory.errors import ContentBlockedError, ProviderError
from shorts_factory.providers.video.fal import (
    FalVideoProvider,
    base_app_id,
    data_uri,
    find_duration,
    find_video_url,
    queue_app_id,
    unknown_endpoint,
)

MODEL = "fal-ai/wan/v2.6/image-to-video"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "k")
    # Every transport below is a MockTransport, so nothing leaves the process.
    # This only satisfies the guard against *accidental* live calls.
    monkeypatch.setenv("ALLOW_LIVE_API_TESTS", "1")


def provider(handler, **kwargs) -> FalVideoProvider:
    return FalVideoProvider(
        model=MODEL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs
    )


def png(tmp_path: Path, name: str = "anchor.png") -> Path:
    target = tmp_path / name
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return target


# -- submit -----------------------------------------------------------------


async def test_submit_sends_the_frame_and_returns_the_request_id(tmp_path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = httpx.Request("POST", "http://x", content=request.content).content.decode()
        return httpx.Response(200, json={"request_id": "abc123"})

    job = await provider(handler).submit(
        prompt="a banknote separating",
        duration_sec=5,
        aspect_ratio="9:16",
        first_frame=png(tmp_path),
    )
    assert job == "abc123"
    assert seen["url"] == f"https://queue.fal.run/{MODEL}"
    assert seen["auth"] == "Key k"
    # The frame is what stops twelve clips being twelve machines.
    assert '"image_url":"data:image/png;base64,' in seen["body"]


async def test_submit_without_a_frame_sends_no_image(tmp_path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"request_id": "r"})

    await provider(handler).submit(prompt="p", duration_sec=5, aspect_ratio="9:16")
    assert "image_url" not in seen["body"]


async def test_a_model_that_wants_duration_as_a_string_gets_one() -> None:
    """Models on fal disagree about this, which is why it is configuration."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"request_id": "r"})

    await provider(handler, duration_as_string=True).submit(
        prompt="p", duration_sec=5, aspect_ratio="9:16"
    )
    assert '"duration":"5"' in seen["body"]


async def test_a_field_the_model_does_not_have_can_be_switched_off() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"request_id": "r"})

    await provider(handler, aspect_ratio_field=None).submit(
        prompt="p", duration_sec=5, aspect_ratio="9:16"
    )
    assert "aspect_ratio" not in seen["body"]


async def test_a_refusal_is_not_retried() -> None:
    """Paying to be refused a second time helps nobody."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "flagged by the content filter"})

    with pytest.raises(ContentBlockedError):
        await provider(handler).submit(prompt="p", duration_sec=5, aspect_ratio="9:16")


async def test_a_reply_with_no_request_id_is_an_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"detail": "queued"})

    with pytest.raises(ProviderError, match="no request_id"):
        await provider(handler).submit(prompt="p", duration_sec=5, aspect_ratio="9:16")


# -- status and download ----------------------------------------------------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [("IN_QUEUE", "processing"), ("IN_PROGRESS", "processing"), ("COMPLETED", "completed")],
)
async def test_queue_states_map_onto_pipeline_states(reported, expected) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": reported})

    state = await provider(handler).status("r")
    assert state.state == expected


async def test_download_writes_the_clip(tmp_path) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        if "requests/" in str(request.url):
            return httpx.Response(200, json={"video": {"url": "https://cdn.fal/x/out.mp4"}})
        return httpx.Response(200, content=b"MP4DATA")

    result = await provider(handler).download("r", tmp_path / "clip.mp4")
    assert Path(result.path).read_bytes() == b"MP4DATA"


async def test_a_finished_job_with_no_video_says_so(tmp_path) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"logs": ["done"]})

    with pytest.raises(ProviderError, match="held no video"):
        await provider(handler).download("r", tmp_path / "clip.mp4")


# -- response walking -------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"video": {"url": "https://c/out.mp4"}},
        {"videos": [{"url": "https://c/out.mp4"}]},
        {"output": {"video": {"file_url": "https://c/out.mp4"}}},
    ],
)
def test_the_video_is_found_wherever_a_model_puts_it(body) -> None:
    """Models nest their output differently; indexing one shape breaks the rest."""
    assert find_video_url(body) == "https://c/out.mp4"


def test_a_still_image_in_the_result_is_not_mistaken_for_the_clip() -> None:
    assert find_video_url({"image": {"url": "https://c/thumb.png"}}) is None


def test_duration_is_read_when_reported() -> None:
    assert find_duration({"video": {"duration": 5.0}}) == 5.0
    assert find_duration({"video": {"url": "x"}}) is None


# -- the frame --------------------------------------------------------------


def test_a_missing_frame_is_caught_before_the_call(tmp_path) -> None:
    with pytest.raises(ProviderError, match="does not exist"):
        data_uri(tmp_path / "nope.png")


def test_a_file_that_is_not_an_image_is_refused(tmp_path) -> None:
    bad = tmp_path / "clip.mp4"
    bad.write_bytes(b"0")
    with pytest.raises(ProviderError, match="first frame"):
        data_uri(bad)


# -- duration snapping ------------------------------------------------------


def test_a_model_with_fixed_lengths_rounds_up() -> None:
    p = FalVideoProvider(model=MODEL, allowed_durations=(5.0, 10.0))
    assert p.snap_duration(3.3) == 5.0
    assert p.snap_duration(5.0) == 5.0
    assert p.snap_duration(99.0) == 10.0


def test_a_model_that_takes_any_length_is_left_alone() -> None:
    """Veo forced this; several models on fal do not, and rounding would overpay."""
    assert FalVideoProvider(model=MODEL).snap_duration(3.3) == 3.3


# -- the queue lives somewhere other than the model path --------------------


async def test_polling_follows_the_url_fal_returned(tmp_path) -> None:
    """Submitting to a versioned model path returns a queue url without it.

    Real reply from fal-ai/wan/v2.6/image-to-video:

        "status_url": ".../fal-ai/wan/requests/<id>/status"

    Rebuilding that url from the model path asks
    .../fal-ai/wan/v2.6/image-to-video/requests/<id>/status, which answers 405
    Method Not Allowed on every poll -- indistinguishable from a stuck job
    while the clip has already been paid for.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "abc",
                    "status_url": "https://queue.fal.run/fal-ai/wan/requests/abc/status",
                    "response_url": "https://queue.fal.run/fal-ai/wan/requests/abc",
                },
            )
        return httpx.Response(200, json={"status": "COMPLETED"})

    p = provider(handler)
    await p.submit(prompt="x", duration_sec=5, aspect_ratio="9:16")
    await p.status("abc")

    assert seen[-1] == "https://queue.fal.run/fal-ai/wan/requests/abc/status"
    assert "v2.6" not in seen[-1]


async def test_a_resumed_run_falls_back_to_the_base_app_id() -> None:
    """No submit reply is held after a restart, so the url has to be derived."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "IN_PROGRESS"})

    p = provider(handler)
    assert p._url("never-submitted", "status") == (
        "https://queue.fal.run/fal-ai/wan/requests/never-submitted/status"
    )


def test_the_queue_id_drops_the_version_and_the_task() -> None:
    assert base_app_id is queue_app_id, "the old name is kept as an alias"
    assert base_app_id("fal-ai/wan/v2.6/image-to-video") == "fal-ai/wan"
    assert base_app_id("fal-ai/kling-video/v2.6/pro/image-to-video") == "fal-ai/kling-video"
    assert base_app_id("fal-ai/wan") == "fal-ai/wan"


async def test_the_result_is_fetched_from_owner_slash_alias(tmp_path) -> None:
    """The queue answers under owner/alias, with version and task dropped.

    Transcribed from fal's own client rather than inferred. Inferring it cost
    two rounds: the full path answers 405 Method Not Allowed, and the short one
    is what fal itself returns as response_url.
    """
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "abc"})
        if url.endswith("/out.mp4"):
            return httpx.Response(200, content=b"MP4")
        asked.append(url)
        return httpx.Response(200, json={"video": {"url": "https://cdn.fal/out.mp4"}})

    p = provider(handler)
    await p.submit(prompt="x", duration_sec=5, aspect_ratio="9:16")
    result = await p.download("abc", tmp_path / "clip.mp4")

    assert Path(result.path).read_bytes() == b"MP4"
    assert asked == ["https://queue.fal.run/fal-ai/wan/requests/abc"]


async def test_an_endpoint_that_does_not_exist_says_so(tmp_path) -> None:
    """A wrong model id is not refused at submit -- only at the result.

    fal queues a submission to any path under an app that exists, reports
    COMPLETED in about five seconds having generated nothing, and then answers
    the result call with 404 naming a path the request never contained.
    Reporting that as "no video in the result" sends you to debug the adapter.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "abc"})
        return httpx.Response(404, json={"detail": "Path /v2.6/image-to-video not found"})

    p = FalVideoProvider(
        model="fal-ai/wan/v2.6/image-to-video",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await p.submit(prompt="x", duration_sec=5, aspect_ratio="9:16")
    with pytest.raises(
        ProviderError, match=re.escape("no endpoint 'fal-ai/wan/v2.6/image-to-video'")
    ):
        await p.download("abc", tmp_path / "clip.mp4")


def test_only_a_routing_404_is_read_as_a_bad_endpoint() -> None:
    assert unknown_endpoint('fal HTTP 404: {"detail":"Path /v2.6/image-to-video not found"}')
    assert not unknown_endpoint("fal HTTP 404: request not found")
    assert not unknown_endpoint("fal HTTP 500: server error")


def test_a_namespaced_id_keeps_its_prefix() -> None:
    """workflows/ and comfy/ shift owner and alias one segment along."""
    assert queue_app_id("workflows/me/my-flow") == "workflows/me/my-flow"
    assert queue_app_id("comfy/me/graph") == "comfy/me/graph"


async def test_a_plain_404_is_not_dressed_up_as_a_bad_endpoint(tmp_path) -> None:
    """Only a 404 that names a path means the endpoint id is wrong.

    A request id that has expired also 404s, and telling someone to go and
    check their model id over that would send them to fix something correct.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "abc"})
        return httpx.Response(404, json={"detail": "not found"})

    p = provider(handler)
    await p.submit(prompt="x", duration_sec=5, aspect_ratio="9:16")
    with pytest.raises(ProviderError, match="HTTP 404") as caught:
        await p.download("abc", tmp_path / "clip.mp4")
    assert "no endpoint" not in str(caught.value)
