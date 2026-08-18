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
