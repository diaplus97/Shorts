"""Video generation over fal.ai's queue API.

    POST https://queue.fal.run/{model}                     -> request_id
    GET  https://queue.fal.run/{model}/requests/{id}/status -> IN_QUEUE | IN_PROGRESS | COMPLETED
    GET  https://queue.fal.run/{model}/requests/{id}        -> the result, with a video url

fal is a router: one key reaches Kling, Wan, Seedance, Hailuo and others. That
matters here for one reason above all -- **Veo 3.1 Standard at $0.40/s was the
most expensive option on the market**, and the same 65-second Short costs
roughly $4.55 on Kling 2.6 Pro, $3.25 on Wan 2.6 and under $2 on Seedance Fast.
The first real run of this pipeline was priced at a number that made the format
pointless, and the model id was the whole reason.

Two design choices come from not being able to verify this against the live API:

* **Input fields are configuration, not code.** Every model on fal has its own
  input schema -- ``duration`` is a number on one and a string like "5" on the
  next, ``aspect_ratio`` exists on some and not others. ``extra_parameters``
  carries whatever the chosen model wants, so a field this file has never heard
  of does not need a code change.
* **The response is walked, not indexed.** ``find_video_url`` searches the
  result for anything that looks like a video, so a model that nests its output
  differently still works instead of raising a KeyError on ``["video"]["url"]``.

Reference-image conditioning is the point of using this rather than plain
text-to-video: ``image_url`` accepts a base64 data URI, so the anchor frame goes
in the request body and no upload step is needed. Handing the model the opening
frame is what stops twelve clips being twelve different machines, and it is what
the image-to-video workflows this is modelled on all do.

**Submission is verified; the rest is not.** A probe submitted successfully and
came back with a request_id, which also revealed that the queue does not live
under the model path -- see ``base_app_id``. That fix has not itself been run.
``scripts/probe_fal.py`` makes exactly one call and prints the raw response,
which is the cheap way to find the next shape change.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from ...errors import ContentBlockedError, ProviderError
from ...utils import ensure_dir, get_logger
from ..base import (
    VideoJobState,
    VideoResult,
    assert_live_calls_allowed,
    is_retryable_429,
    require_secret,
)

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://queue.fal.run"

#: fal queue states, mapped onto the pipeline's vocabulary.
_STATE_MAP = {
    "IN_QUEUE": "processing",
    "IN_PROGRESS": "processing",
    "COMPLETED": "completed",
    "OK": "completed",
    "FAILED": "failed",
    "ERROR": "failed",
    "CANCELLED": "failed",
}

_BLOCK_PHRASES = ("safety", "nsfw", "policy", "blocked", "prohibited", "content filter")

#: Extensions accepted as a conditioning frame.
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class FalVideoProvider:
    name = "fal"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        allowed_durations: tuple[float, ...] = (),
        aspect_ratio_field: str | None = "aspect_ratio",
        duration_field: str | None = "duration",
        duration_as_string: bool = False,
        extra_parameters: dict[str, Any] | None = None,
        timeout_sec: float = 120.0,
        download_timeout_sec: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model.strip("/")
        self.base_url = base_url.rstrip("/")
        self.allowed_durations = tuple(sorted(allowed_durations))
        self.aspect_ratio_field = aspect_ratio_field
        self.duration_field = duration_field
        self.duration_as_string = duration_as_string
        self.extra_parameters = dict(extra_parameters or {})
        self.timeout_sec = timeout_sec
        self.download_timeout_sec = download_timeout_sec
        self._client = client
        #: request_id -> the status and result urls fal returned for it.
        #:
        #: These are not built from the model path, because fal's queue
        #: endpoints do not use the model path. Submitting to
        #: fal-ai/wan/v2.6/image-to-video comes back with a status_url under
        #: fal-ai/wan -- the base app id, with the version and the task dropped
        #: -- and asking the full path returns 405 Method Not Allowed forever.
        #: The response says where to look, so that is where to look.
        self._jobs: dict[str, dict[str, str]] = {}

    # -- duration --------------------------------------------------------

    def snap_duration(self, seconds: float) -> float:
        """Round up to a length this model returns.

        Empty ``allowed_durations`` means the model takes any length, which is
        true of several models on fal and was not true of Veo. Rounding up
        rather than to nearest keeps the clip long enough to trim.
        """
        if not self.allowed_durations:
            return round(max(seconds, 1.0), 3)
        for allowed in self.allowed_durations:
            if allowed + 1e-6 >= seconds:
                return allowed
        return self.allowed_durations[-1]

    # -- lifecycle -------------------------------------------------------

    async def submit(
        self,
        *,
        prompt: str,
        duration_sec: float,
        aspect_ratio: str,
        negative_prompt: str | None = None,
        first_frame: str | Path | None = None,
    ) -> str:
        assert_live_calls_allowed(self.name)
        snapped = self.snap_duration(duration_sec)
        if abs(snapped - duration_sec) > 0.01:
            log.info(
                "fal_duration_snapped",
                requested=round(duration_sec, 2),
                billed=snapped,
                allowed=list(self.allowed_durations),
            )

        payload: dict[str, Any] = {"prompt": prompt}
        if self.duration_field:
            value: Any = int(snapped) if float(snapped).is_integer() else snapped
            payload[self.duration_field] = str(value) if self.duration_as_string else value
        if self.aspect_ratio_field:
            payload[self.aspect_ratio_field] = aspect_ratio
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if first_frame is not None:
            payload["image_url"] = data_uri(first_frame)
        payload.update(self.extra_parameters)

        body = await self._request("POST", f"{self.base_url}/{self.model}", json=payload)
        request_id = body.get("request_id") or body.get("requestId")
        if not request_id:
            raise ProviderError(
                f"fal accepted the request but returned no request_id: {str(body)[:300]}",
                provider=self.name,
            )
        self._jobs[str(request_id)] = {
            "status": str(body.get("status_url") or ""),
            "result": str(body.get("response_url") or ""),
        }
        return str(request_id)

    async def status(self, job_id: str) -> VideoJobState:
        body = await self._request("GET", self._url(job_id, "status"), allow_202=True)
        raw = str(body.get("status") or "").upper()
        state = _STATE_MAP.get(raw, "processing")
        error = body.get("error") or body.get("detail")
        blocked = bool(error) and any(p in str(error).lower() for p in _BLOCK_PHRASES)
        return VideoJobState(
            job_id=job_id,
            state="failed" if blocked else state,
            error=str(error) if error else None,
            blocked=blocked,
        )

    async def download(self, job_id: str, destination: str | Path) -> VideoResult:
        body = await self._request("GET", self._url(job_id, "result"))

        url = find_video_url(body)
        if url is None:
            raise ProviderError(
                f"fal reported the job finished but the result has no video url: {str(body)[:300]}",
                provider=self.name,
            )

        target = Path(destination)
        ensure_dir(target.parent)
        api_key = require_secret("FAL_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.download_timeout_sec)
        owns = self._client is None
        try:
            # The result url is usually a signed CDN link that needs no key, but
            # sending one costs nothing and covers the models that do.
            response = await client.get(url, headers={"Authorization": f"Key {api_key}"})
            if response.status_code >= 400:
                raise ProviderError(
                    f"downloading the clip failed with HTTP {response.status_code}",
                    provider=self.name,
                    retryable=response.status_code >= 500,
                )
            target.write_bytes(response.content)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"fal download transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        return VideoResult(path=str(target), model=self.model, duration_sec=find_duration(body))

    def _url(self, job_id: str, kind: str) -> str:
        """Where to poll or collect one job.

        Prefers the url fal returned at submit time. The fallback exists for a
        resumed run, where the response is long gone, and uses ``base_app_id``
        rather than the configured model path for the reason described on
        ``_jobs``.
        """
        recorded = self._jobs.get(job_id, {}).get(kind)
        if recorded:
            return recorded
        base = f"{self.base_url}/{base_app_id(self.model)}/requests/{job_id}"
        return f"{base}/status" if kind == "status" else base

    # -- transport -------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        allow_202: bool = False,
    ) -> dict[str, Any]:
        api_key = require_secret("FAL_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            response = await client.request(
                method, url, headers={"Authorization": f"Key {api_key}"}, json=json
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"fal request timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"fal transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        if response.status_code >= 400:
            text = response.text[:500]
            if response.status_code in (400, 422) and any(
                phrase in text.lower() for phrase in _BLOCK_PHRASES
            ):
                raise ContentBlockedError(
                    f"fal refused the prompt: {text}", provider=self.name, reason=text
                )
            raise ProviderError(
                f"fal HTTP {response.status_code}: {text}",
                provider=self.name,
                retryable=(response.status_code == 429 and is_retryable_429(response.text))
                or response.status_code >= 500,
            )
        if response.status_code == 202 and allow_202:
            return {"status": "IN_PROGRESS"}
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"fal returned non-JSON: {response.text[:300]}", provider=self.name
            ) from exc


def base_app_id(model: str) -> str:
    """The owner/app part of a fal model path.

    ``fal-ai/wan/v2.6/image-to-video`` is where a request is *submitted*, but
    its queue lives under ``fal-ai/wan``. Everything after the second segment is
    a version and a task, and including it gets 405 Method Not Allowed on every
    poll -- which reads like a broken job rather than a wrong url.
    """
    parts = [part for part in model.strip("/").split("/") if part]
    return "/".join(parts[:2]) if len(parts) >= 2 else model.strip("/")


def data_uri(path: str | Path) -> str:
    """A local image as a base64 data URI.

    fal accepts either a public URL or a data URI for a file input, and a data
    URI means the anchor frame never has to be uploaded anywhere first -- one
    fewer service, one fewer failure, and nothing of the user's leaves in a
    request they did not make.
    """
    source = Path(path)
    if not source.exists():
        raise ProviderError(f"first frame {source} does not exist", provider="fal")
    mime = _IMAGE_MIME.get(source.suffix.lower()) or mimetypes.guess_type(source.name)[0]
    if not mime or not mime.startswith("image/"):
        raise ProviderError(
            f"cannot send {source.suffix or 'a file with no extension'} as a first frame; "
            f"expected one of {', '.join(sorted(_IMAGE_MIME))}",
            provider="fal",
        )
    return f"data:{mime};base64,{base64.b64encode(source.read_bytes()).decode('ascii')}"


def find_video_url(node: Any) -> str | None:
    """The first thing in the result that looks like a generated video.

    Models on fal disagree about where the output sits -- ``video.url``,
    ``videos[0].url``, ``output.url``. Walking for it means a new model works
    without this file learning its shape first.
    """
    if isinstance(node, dict):
        for key in ("url", "video_url", "file_url"):
            value = node.get(key)
            if isinstance(value, str) and _looks_like_video(value):
                return value
        for value in node.values():
            if (found := find_video_url(value)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := find_video_url(item)) is not None:
                return found
    return None


def _looks_like_video(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    lowered = url.split("?", 1)[0].lower()
    return lowered.endswith((".mp4", ".webm", ".mov")) or "video" in lowered


def find_duration(node: Any) -> float | None:
    """A duration from the result, when the model reports one."""
    if isinstance(node, dict):
        for key in ("duration", "duration_sec", "duration_seconds"):
            value = node.get(key)
            if isinstance(value, int | float) and value > 0:
                return float(value)
        for value in node.values():
            if (found := find_duration(value)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := find_duration(item)) is not None:
                return found
    return None
