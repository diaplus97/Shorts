"""Live provider checks. Never run by default.

    ALLOW_LIVE_API_TESTS=1 pytest -m live

These cost real money, so they are opt-in twice over: the marker and the
environment variable (spec section 56).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shorts_factory.domain import ResearchResult
from shorts_factory.media import probe
from shorts_factory.prompts import load_prompt
from shorts_factory.providers.llm.openai import OpenAILLMProvider
from shorts_factory.providers.tts.openai import OpenAITTSProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ALLOW_LIVE_API_TESTS") != "1",
        reason="set ALLOW_LIVE_API_TESTS=1 to run live provider tests",
    ),
]


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not set")
async def test_openai_returns_schema_valid_research(config) -> None:
    provider = OpenAILLMProvider(model=config.settings.llm.model)
    prompt = load_prompt("research")
    user = prompt.render_user(
        {
            "topic": "자동문은 사람이 오는 것을 어떻게 알까?",
            "content_type": "inside_object",
            "content_type_label": "Inside Object",
            "content_type_description": "Internal structure of familiar machines.",
            "target_claims": 4,
            "sources_json": [
                {
                    "id": "S01",
                    "title": "Automatic door sensors",
                    "url": "https://example.com/doors",
                    "publisher": "Example",
                }
            ],
        }
    )
    response = await provider.generate_json(
        system_prompt=prompt.system, user_prompt=user, schema=ResearchResult
    )
    result = ResearchResult.model_validate(response.data)
    assert result.claims
    assert response.usage.output_tokens > 0


@pytest.mark.skipif(not os.environ.get("TTS_API_KEY"), reason="TTS_API_KEY is not set")
async def test_openai_tts_produces_audio(tmp_path: Path, config) -> None:
    provider = OpenAITTSProvider(model=config.settings.tts.model, voice=config.settings.tts.voice)
    destination = tmp_path / "narration.wav"
    result = await provider.synthesize("자동문은 사람을 어떻게 알아볼까요?", destination)
    assert Path(result.path).exists()
    assert probe(destination).duration_sec > 0


@pytest.mark.skipif(not os.environ.get("VIDEO_API_KEY"), reason="VIDEO_API_KEY is not set")
async def test_veo_generates_a_clip(tmp_path: Path, config) -> None:
    """The only test that can tell us whether the Veo adapter is actually right.

    Costs real money: one short clip at the configured per-second rate.
    """
    import asyncio

    from shorts_factory.providers.video.veo import VeoVideoProvider

    video = config.settings.video
    provider = VeoVideoProvider(
        model=video.model,
        base_url=video.base_url,
        allowed_durations=tuple(video.allowed_durations) or (4.0, 6.0, 8.0),
        resolution=video.resolution,
        generate_audio=False,
    )

    job = await provider.submit(
        prompt=(
            "macro tracking shot of a single sheet of paper being pulled from a stack "
            "by a rubber roller inside a machine, documentary CGI cutaway"
        ),
        duration_sec=4.0,
        aspect_ratio=video.aspect_ratio,
        negative_prompt="visible text, logos, holograms",
    )
    assert job

    waited = 0.0
    while waited < video.poll_timeout_sec:
        state = await provider.status(job)
        assert state.state != "failed", state.error
        if state.state == "completed":
            break
        await asyncio.sleep(video.poll_interval_sec)
        waited += video.poll_interval_sec
    else:  # pragma: no cover - only on a very slow job
        pytest.fail(f"Veo job {job} did not finish within {video.poll_timeout_sec}s")

    result = await provider.download(job, tmp_path / "clip.mp4")
    info = probe(result.path)
    assert info.has_video
    assert info.duration_sec > 0
