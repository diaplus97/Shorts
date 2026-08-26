"""Google Veo 3 video provider, over the Gemini API.

    POST models/{model}:predictLongRunning  ->  operation name
    GET  {operation name}                   ->  done / error / still running
    GET  {video uri}                        ->  the mp4

Three things about Veo shape this adapter more than the endpoints do:

* **Clip lengths are discrete.** Veo returns a fixed-length clip, so asking for
  3.3 seconds is not a thing. `snap_duration` rounds *up* to the shortest
  accepted length, which keeps the picture long enough to trim and keeps the
  cost estimate honest.
* **It generates its own audio.** We mix our own narration, so audio is turned
  off in the request; normalisation strips any that arrives anyway.
* **Prompts get refused.** A content-policy refusal is not a transient error.
  Retrying one costs money and fails again, so it raises
  :class:`ContentBlockedError` and the scene falls back to a still.

**Partly verified against the live API.** Two clips of ten came back in the
first paid run; the other eight were refused with "1080p is not supported for
a duration of 6 seconds", which is why rejected parameters are matched on
their value and not only their name. The rest is written from the
documented request and response shape, and every value that could drift lives in
`config/settings.yaml` -- including `extra_parameters`, an escape hatch for a
field this code does not know about. Check Google's current Veo documentation
before the first paid run, and expect to adjust.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from ...errors import ContentBlockedError, ProviderError
from ...utils import ensure_dir, get_logger
from ..base import VideoJobState, VideoResult, assert_live_calls_allowed, require_secret

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Response keys that mean "we refused this prompt" rather than "it broke".
_BLOCK_KEYS = (
    "raiFilteredReason",
    "raiMediaFilteredReason",
    "raiMediaFilteredCount",
    "filteredReason",
    "blockedReason",
)
_BLOCK_PHRASES = ("safety", "blocked", "policy", "filtered", "prohibited")


class VeoVideoProvider:
    name = "veo"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        allowed_durations: tuple[float, ...] = (4.0, 6.0, 8.0),
        sample_count: int = 1,
        person_generation: str | None = None,
        resolution: str | None = "1080p",
        generate_audio: bool | None = None,
        extra_parameters: dict[str, Any] | None = None,
        timeout_sec: float = 120.0,
        download_timeout_sec: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.allowed_durations = tuple(sorted(allowed_durations))
        self.sample_count = sample_count
        self.person_generation = person_generation
        self.resolution = resolution
        self.generate_audio = generate_audio
        self.extra_parameters = dict(extra_parameters or {})
        self.timeout_sec = timeout_sec
        self.download_timeout_sec = download_timeout_sec
        self._client = client

    # -- duration --------------------------------------------------------

    def snap_duration(self, seconds: float) -> float:
        """Shortest accepted clip length that still covers ``seconds``."""
        if not self.allowed_durations:
            return seconds
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
                "veo_duration_snapped",
                requested=round(duration_sec, 2),
                billed=snapped,
                allowed=list(self.allowed_durations),
            )

        parameters: dict[str, Any] = {
            "aspectRatio": aspect_ratio,
            "durationSeconds": int(snapped),
            "sampleCount": self.sample_count,
        }
        # Veo 3.1 generates audio natively and rejects the field outright
        # ("`generateAudio` isn't supported by this model", HTTP 400), while
        # earlier revisions required it. None means "do not send it at all",
        # which is the only setting Veo 3.1 accepts. We strip the audio at
        # normalisation regardless, so our own narration is never fought.
        if self.generate_audio is not None:
            parameters["generateAudio"] = self.generate_audio
        if negative_prompt:
            parameters["negativePrompt"] = negative_prompt
        if self.person_generation:
            parameters["personGeneration"] = self.person_generation
        if self.resolution:
            parameters["resolution"] = self.resolution
        parameters.update(self.extra_parameters)

        body = await self._submit_dropping_rejected(prompt, parameters, first_frame)
        operation = body.get("name")
        if not operation:
            raise ProviderError(
                f"Veo accepted the request but returned no operation name: {body}",
                provider=self.name,
            )
        return str(operation)

    async def _submit_dropping_rejected(
        self,
        prompt: str,
        parameters: dict[str, Any],
        first_frame: str | Path | None = None,
    ) -> dict[str, Any]:
        """POST the request, retrying without any tuning field Veo rejects.

        These are preview models and the accepted parameter set moves between
        revisions -- ``generateAudio`` and ``personGeneration`` were both
        rejected outright by veo-3.1-fast-generate-preview with HTTP 400
        INVALID_ARGUMENT, one per round trip. The rejection names the field, so
        drop it and try again rather than failing the scene over a field that
        was optional to begin with.

        Only DROPPABLE_PARAMETERS are removed. A rejection of aspectRatio or
        durationSeconds changes what we would get back, so it stays an error.
        Nothing here is billed: a 400 is refused before generation starts.
        """
        attempted = dict(parameters)
        dropped: list[str] = []
        instance = build_instance(prompt, first_frame)
        while True:
            try:
                return await self._request(
                    "POST",
                    f"{self.base_url}/models/{self.model}:predictLongRunning",
                    json={"instances": [instance], "parameters": attempted},
                )
            except ContentBlockedError:
                raise
            except ProviderError as exc:
                field = find_rejected_parameter(str(exc), attempted)
                if field is None:
                    raise
                attempted.pop(field)
                dropped.append(field)
                log.warning(
                    "veo_parameter_dropped",
                    parameter=field,
                    model=self.model,
                    dropped_so_far=dropped,
                    detail=str(exc)[:200],
                )

    async def status(self, job_id: str) -> VideoJobState:
        assert_live_calls_allowed(self.name)
        body = await self._request("GET", self._operation_url(job_id))

        error = body.get("error")
        if error:
            message = str(error.get("message", error))
            return VideoJobState(
                job_id=job_id,
                state="failed",
                error=message,
                blocked=_looks_blocked(message),
            )

        if not body.get("done"):
            return VideoJobState(job_id=job_id, state="processing")

        blocked_reason = find_block_reason(body)
        if blocked_reason:
            return VideoJobState(job_id=job_id, state="failed", error=blocked_reason, blocked=True)
        if find_video_payload(body) is None:
            return VideoJobState(
                job_id=job_id,
                state="failed",
                error="the operation finished with no video in the response",
            )
        return VideoJobState(job_id=job_id, state="completed", progress=1.0)

    async def download(self, job_id: str, destination: str | Path) -> VideoResult:
        assert_live_calls_allowed(self.name)
        target = Path(destination)
        ensure_dir(target.parent)

        # Re-read the operation rather than caching it between calls: the job id
        # is all a resumed run has, and it survives in the asset ledger.
        body = await self._request("GET", self._operation_url(job_id))
        payload = find_video_payload(body)
        if payload is None:
            reason = find_block_reason(body) or "no video in the operation response"
            raise ProviderError(f"Veo job {job_id}: {reason}", provider=self.name)

        inline = payload.get("bytesBase64Encoded") or payload.get("videoBytes")
        if inline:
            target.write_bytes(base64.b64decode(inline))
        else:
            uri = payload.get("uri") or payload.get("gcsUri")
            if not uri:
                raise ProviderError(
                    f"Veo job {job_id}: video payload has neither bytes nor a uri",
                    provider=self.name,
                )
            await self._download_file(str(uri), target)

        if target.stat().st_size == 0:
            raise ProviderError(f"Veo job {job_id}: downloaded an empty file", provider=self.name)
        return VideoResult(path=str(target), model=self.model)

    # -- transport -------------------------------------------------------

    def _operation_url(self, job_id: str) -> str:
        if job_id.startswith("http://") or job_id.startswith("https://"):
            return job_id
        return f"{self.base_url}/{job_id.lstrip('/')}"

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        api_key = require_secret("VIDEO_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns_client = self._client is None
        try:
            response = await client.request(
                method, url, headers={"x-goog-api-key": api_key}, **kwargs
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Veo request timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Veo transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        self._raise_for_status(response)
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"Veo returned non-JSON content: {response.text[:300]}", provider=self.name
            ) from exc

    async def _download_file(self, uri: str, target: Path) -> None:
        api_key = require_secret("VIDEO_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(
            timeout=self.download_timeout_sec, follow_redirects=True
        )
        owns_client = self._client is None
        try:
            response = await client.get(uri, headers={"x-goog-api-key": api_key})
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Veo download failed: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        self._raise_for_status(response)
        target.write_bytes(response.content)

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        text = response.text[:500]
        if response.status_code in (400, 403) and _looks_blocked(text):
            raise ContentBlockedError(
                f"Veo refused the prompt: {text}", provider=self.name, reason=text
            )
        retryable = response.status_code == 429 or response.status_code >= 500
        raise ProviderError(
            f"Veo HTTP {response.status_code}: {text}",
            provider=self.name,
            retryable=retryable,
        )


#: Optional tuning fields that may be dropped when the model rejects them.
#: aspectRatio and durationSeconds are deliberately absent: dropping either
#: would silently change the clip we get back, so a rejection there is an error.
DROPPABLE_PARAMETERS = (
    "generateAudio",
    "personGeneration",
    "resolution",
    "sampleCount",
    "negativePrompt",
)


#: Extensions Veo accepts as a conditioning frame, mapped to their MIME type.
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def build_instance(prompt: str, first_frame: str | Path | None) -> dict[str, Any]:
    """The request instance, optionally pinned to a picture that already exists.

    Text-to-video redesigns the machine on every call: a different roller count,
    a different layout, banknotes travelling the other way. Each clip is
    individually plausible and together they are twelve machines. Handing Veo
    the first frame moves the design decision out of the video model, which only
    has to animate what it was given.

    **Not verified against the live API.** Veo's documented image-to-video shape
    puts the picture on the instance next to the prompt; if a revision moves it,
    this is the one place that changes.
    """
    instance: dict[str, Any] = {"prompt": prompt}
    if first_frame is None:
        return instance

    source = Path(first_frame)
    mime = _MIME_TYPES.get(source.suffix.lower())
    if mime is None:
        raise ProviderError(
            f"cannot send {source.suffix or 'a file with no extension'} as a first frame; "
            f"expected one of {', '.join(sorted(_MIME_TYPES))}",
            provider="veo",
        )
    if not source.exists():
        raise ProviderError(f"first frame {source} does not exist", provider="veo")

    instance["image"] = {
        "bytesBase64Encoded": base64.b64encode(source.read_bytes()).decode("ascii"),
        "mimeType": mime,
    }
    return instance


def find_rejected_parameter(message: str, sent: dict[str, Any]) -> str | None:
    """The droppable parameter an INVALID_ARGUMENT complains about, if any.

    Veo names the offending field in some messages and only its *value* in
    others:

        "`generateAudio` isn't supported by this model."
        "allow_adult for personGeneration is currently not supported."
        "1080p is not supported for a duration of 6 seconds."

    The third names no field at all, so matching field names alone missed it
    and eight scenes in a row fell back to stills. Values are matched too, and
    only for a parameter we actually sent -- a message mentioning something we
    omitted is a different problem and must not be swallowed.
    """
    if "400" not in message and "INVALID_ARGUMENT" not in message:
        return None
    lowered = message.lower()
    for field in DROPPABLE_PARAMETERS:
        if field not in sent:
            continue
        if field.lower() in lowered:
            return field
        # A value like "1080p" is distinctive enough to identify its field; a
        # bare number is not, and would match any duration or count in the text.
        value = str(sent[field]).strip().lower()
        if len(value) > 2 and not value.isdigit() and value in lowered:
            return field
    return None


# -- response walking ------------------------------------------------------
#
# The exact nesting has moved between Veo revisions, so these walk the tree for
# what they need instead of hardcoding one path. A shape change should degrade
# to a clear error, not a KeyError.


def find_video_payload(node: Any) -> dict[str, Any] | None:
    """First dict that looks like a video: has a uri or inline bytes."""
    if isinstance(node, dict):
        if any(key in node for key in ("uri", "gcsUri", "bytesBase64Encoded", "videoBytes")):
            return node
        for key in ("video", "generatedSamples", "generatedVideos", "videos"):
            if key in node:
                found = find_video_payload(node[key])
                if found is not None:
                    return found
        for value in node.values():
            found = find_video_payload(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_video_payload(item)
            if found is not None:
                return found
    return None


def find_block_reason(node: Any) -> str | None:
    """A content-policy refusal reported inside a successful operation."""
    if isinstance(node, dict):
        for key in _BLOCK_KEYS:
            if node.get(key):
                return f"{key}: {node[key]}"
        for value in node.values():
            found = find_block_reason(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_block_reason(item)
            if found is not None:
                return found
    return None


def _looks_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _BLOCK_PHRASES)
