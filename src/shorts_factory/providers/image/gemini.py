"""Still images from Gemini's image models, over generateContent.

    POST models/{model}:generateContent
      generationConfig.responseModalities = ["IMAGE"]
    ->  candidates[].content.parts[].inlineData.data, base64

This was first written against Imagen's ``:predict`` endpoint, with
``instances`` and ``parameters``. Listing what the key can actually reach found
no ``imagen-*`` model at all: the image models are the ``gemini-*-image``
family, and every one of them supports ``generateContent`` and not ``predict``.
The original shape would have 404'd on the first call.

Two consequences of that API being the text one:

* **There is no negativePrompt field.** The Style Bible's avoid list is what
  keeps a still on-model, so it is folded into the prompt text instead.
* **There is no width or height.** Aspect ratio is requested through
  ``imageConfig``; the pixel size decides which ratio to ask for.

Stills are the fallback for a scene whose video generation failed, and the only
implementation before this was a mock that rendered a solid colour PNG. Using
the same vendor as the video provider is the point: a still from a different
generator to the clips beside it will not match them, and no prompt wording
fixes that.

**Not yet run against the live API.** ``scripts/list_gemini_models.py --kind
image`` reports what a key can reach, and the response is walked rather than
indexed so a shape change degrades to a clear error.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

import httpx

from ...errors import ContentBlockedError, ProviderError
from ...utils import ensure_dir, get_logger
from ..base import (
    ImageResult,
    assert_live_calls_allowed,
    is_retryable_429,
    require_secret,
)

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_BLOCK_KEYS = ("raiFilteredReason", "filteredReason", "blockedReason")
_BLOCK_PHRASES = ("safety", "blocked", "policy", "filtered", "prohibited")

#: Optional tuning fields Imagen revisions disagree about. Same treatment as the
#: video provider: a 400 naming one of these drops it and retries rather than
#: costing another round trip to discover.
#: Optional generationConfig fields these models disagree about. responseModalities
#: is deliberately absent: dropping it returns text instead of a picture.
DROPPABLE_PARAMETERS = ("imageConfig", "personGeneration", "safetySettings", "imageSize")


class GeminiImageProvider:
    name = "gemini"
    is_mock = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        aspect_ratio: str = "9:16",
        person_generation: str | None = None,
        extra_parameters: dict[str, Any] | None = None,
        timeout_sec: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.aspect_ratio = aspect_ratio
        self.person_generation = person_generation
        self.extra_parameters = dict(extra_parameters or {})
        self.timeout_sec = timeout_sec
        self._client = client

    async def generate(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        destination: str | Path,
        negative_prompt: str | None = None,
        reference_image: str | Path | None = None,
    ) -> ImageResult:
        assert_live_calls_allowed(self.name)
        target = Path(destination)
        ensure_dir(target.parent)

        # generateContent has no negativePrompt, so the avoid list has to be
        # said in words. Without it the model reaches for glowing holograms the
        # moment a prompt sounds technical, which is what the list exists for.
        text = prompt
        if negative_prompt:
            text = f"{prompt}\n\nDo not include: {negative_prompt}"

        config: dict[str, Any] = {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": _closest_ratio(width, height, self.aspect_ratio)},
        }
        config.update(self.extra_parameters)

        body = await self._generate_dropping_rejected(text, config, reference_image)

        payload = find_image_bytes(body)
        if payload is None:
            if reason := find_block_reason(body):
                raise ContentBlockedError(
                    f"the image model refused the prompt: {reason}",
                    provider=self.name,
                    reason=reason,
                )
            raise ProviderError(
                f"the image model returned no image: {str(body)[:300]}", provider=self.name
            )
        try:
            target.write_bytes(base64.b64decode(payload))
        except (binascii.Error, ValueError) as exc:
            raise ProviderError(
                f"the image model returned bytes that are not valid base64: {exc}",
                provider=self.name,
            ) from exc
        return ImageResult(path=str(target), model=self.model)

    async def _generate_dropping_rejected(
        self,
        text: str,
        config: dict[str, Any],
        reference_image: str | Path | None = None,
    ) -> dict[str, Any]:
        """POST, retrying without any config field the model rejects.

        The video provider learned this the expensive way: these are preview
        models, they disagree about which optional fields exist, and each
        rejection otherwise costs a round trip to discover. A 400 names the
        field, so drop it and try again.
        """
        attempted = dict(config)
        dropped: list[str] = []
        parts = build_parts(text, reference_image)
        while True:
            try:
                return await self._request(
                    f"{self.base_url}/models/{self.model}:generateContent",
                    {
                        "contents": [{"parts": parts}],
                        "generationConfig": attempted,
                    },
                )
            except ContentBlockedError:
                raise
            except ProviderError as exc:
                field = _rejected_parameter(str(exc), attempted)
                if field is None:
                    raise
                attempted.pop(field)
                dropped.append(field)
                log.warning(
                    "image_config_dropped",
                    field=field,
                    model=self.model,
                    dropped_so_far=dropped,
                )

    async def _request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = require_secret("IMAGE_API_KEY", self.name)
        client = self._client or httpx.AsyncClient(timeout=self.timeout_sec)
        owns = self._client is None
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"the image model timed out after {self.timeout_sec}s",
                provider=self.name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"image transport error: {exc}", provider=self.name, retryable=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        if response.status_code >= 400:
            text = response.text[:500]
            if response.status_code in (400, 403) and any(
                phrase in text.lower() for phrase in _BLOCK_PHRASES
            ):
                raise ContentBlockedError(
                    f"the image model refused the prompt: {text}", provider=self.name, reason=text
                )
            raise ProviderError(
                f"image model HTTP {response.status_code}: {text}",
                provider=self.name,
                retryable=(response.status_code == 429 and is_retryable_429(response.text))
                or response.status_code >= 500,
            )
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderError(
                f"the image model returned non-JSON: {response.text[:300]}", provider=self.name
            ) from exc


#: Extensions generateContent accepts as image input, mapped to their MIME type.
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def build_parts(text: str, reference_image: str | Path | None) -> list[dict[str, Any]]:
    """The request parts, with a reference picture in front of the instruction.

    This is what turns the call from "invent a machine" into "the machine in
    this picture, framed differently". generateContent is the same endpoint
    either way; an image part is simply added, which is the one advantage of
    the image models living on the text API.

    The image goes first deliberately. The instruction that follows reads as
    being *about* the picture rather than as a description competing with it.
    """
    parts: list[dict[str, Any]] = []
    if reference_image is not None:
        source = Path(reference_image)
        mime = _MIME_TYPES.get(source.suffix.lower())
        if mime is None:
            raise ProviderError(
                f"cannot send {source.suffix or 'a file with no extension'} as a reference "
                f"image; expected one of {', '.join(sorted(_MIME_TYPES))}",
                provider="gemini",
            )
        if not source.exists():
            raise ProviderError(f"reference image {source} does not exist", provider="gemini")
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(source.read_bytes()).decode("ascii"),
                }
            }
        )
    parts.append({"text": text})
    return parts


def _closest_ratio(width: int, height: int, default: str) -> str:
    """The aspect ratio nearest the requested pixel size.

    generateContent takes a ratio, not a size. 1080x1920 is exactly 9:16;
    composition rescales whatever comes back.
    """
    if not width or not height:
        return default
    wanted = width / height
    options = {"1:1": 1.0, "3:4": 0.75, "4:3": 4 / 3, "9:16": 0.5625, "16:9": 16 / 9}
    return min(options, key=lambda name: abs(options[name] - wanted))


def _rejected_parameter(message: str, sent: dict[str, Any]) -> str | None:
    if "400" not in message and "INVALID_ARGUMENT" not in message:
        return None
    lowered = message.lower()
    for field in DROPPABLE_PARAMETERS:
        if field in sent and field.lower() in lowered:
            return field
    return None


def find_image_bytes(node: Any) -> str | None:
    """First base64 image payload in the response, wherever it sits.

    generateContent nests it under ``inlineData``; the older ``:predict`` shape
    used ``bytesBase64Encoded``. Both are accepted so a model that answers
    either way still works.
    """
    if isinstance(node, dict):
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict):
            data = inline.get("data")
            if isinstance(data, str) and data:
                return data
        for key in ("bytesBase64Encoded", "imageBytes", "b64_json"):
            value = node.get(key)
            if isinstance(value, str) and value:
                return value
        for value in node.values():
            if (found := find_image_bytes(value)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := find_image_bytes(item)) is not None:
                return found
    return None


def find_block_reason(node: Any) -> str | None:
    """A refusal reason, so a policy block is not reported as a broken response."""
    if isinstance(node, dict):
        for key in _BLOCK_KEYS:
            value = node.get(key)
            if value:
                return str(value)
        for value in node.values():
            if (found := find_block_reason(value)) is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            if (found := find_block_reason(item)) is not None:
                return found
    return None
