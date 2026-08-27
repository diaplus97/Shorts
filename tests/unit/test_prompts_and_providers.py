"""Prompt rendering, provider guards and the prompt adapter."""

from __future__ import annotations

import pytest

from factories import make_plan, make_scene
from shorts_factory.domain import RealityType
from shorts_factory.errors import ConfigError, ProviderError
from shorts_factory.prompts import PROMPT_VERSIONS, load_prompt, render, unused_variables
from shorts_factory.providers.base import assert_live_calls_allowed, require_secret
from shorts_factory.providers.llm._promptio import field, int_field, json_block
from shorts_factory.providers.llm.openai import to_strict_schema
from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter


def test_render_substitutes_and_serialises() -> None:
    out = render("a={{a}} b={{ b }}", {"a": 1, "b": ["x", "y"]})
    assert "a=1" in out
    assert '"x"' in out


def test_render_reports_missing_variables() -> None:
    with pytest.raises(ConfigError, match="missing variables"):
        render("{{a}} {{b}}", {"a": 1})


def test_unused_variables_are_reported() -> None:
    assert unused_variables("{{a}}", {"a": 1, "b": 2}) == ["b"]


@pytest.mark.parametrize("name", sorted(PROMPT_VERSIONS))
def test_every_prompt_loads_and_is_hashed(name: str) -> None:
    prompt = load_prompt(name)
    assert prompt.system.strip()
    assert prompt.user_template.strip()
    assert len(prompt.hash) == 16
    assert prompt.version == PROMPT_VERSIONS[name]


def test_missing_prompt_directory_is_an_error(tmp_path) -> None:
    with pytest.raises(ConfigError, match="missing prompt file"):
        load_prompt("research", tmp_path)


def test_prompt_io_reads_fields_and_blocks() -> None:
    prompt = 'TOPIC: ATM은?\nMIN_SCENES: 8\n\nSOURCES_JSON:\n```json\n[{"id": "S01"}]\n```\n'
    assert field(prompt, "TOPIC") == "ATM은?"
    assert int_field(prompt, "MIN_SCENES", 0) == 8
    assert int_field(prompt, "ABSENT", 5) == 5
    assert json_block(prompt, "SOURCES_JSON") == [{"id": "S01"}]
    assert json_block(prompt, "MISSING_JSON", "fallback") == "fallback"


def test_live_api_guard_blocks_during_tests() -> None:
    with pytest.raises(ProviderError, match="blocked during tests"):
        assert_live_calls_allowed("openai")


def test_live_api_guard_can_be_opted_into(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_LIVE_API_TESTS", "1")
    assert_live_calls_allowed("openai")  # must not raise


def test_require_secret_names_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        require_secret("OPENAI_API_KEY", "openai")


def test_strict_schema_forbids_extras_and_requires_everything() -> None:
    from shorts_factory.domain import ScriptResult

    strict = to_strict_schema(ScriptResult.model_json_schema())

    def walk(node) -> None:
        if isinstance(node, dict):
            assert "default" not in node
            assert "title" not in node
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(strict)


def test_prompt_adapter_builds_a_provider_prompt(config) -> None:
    adapter = GenericPromptAdapter(config.visual_styles)
    scene = make_scene(
        visual_subject="ATM note counter",
        camera_path="macro dolly in along the note",
        reality_type=RealityType.CONCEPTUAL,
        negative_constraints=["duplicated notes"],
    )
    prompt = adapter.build_prompt(scene)
    assert "ATM note counter" in prompt
    assert "camera: macro dolly in along the note" in prompt
    # The change is the shot: a model given no change returns a still life.
    assert f"visible change during the shot: {scene.visible_change}" in prompt
    # Conceptual scenes must read as explanatory, not as real footage.
    assert "diagrammatic" in prompt

    negative = adapter.build_negative_prompt(scene)
    assert "duplicated notes" in negative
    assert "generated text" in negative
    # The Style Bible bans holograms outright, whatever the director wrote.
    assert "sci-fi holograms" in negative
    assert negative.count("logos") == 1  # de-duplicated


def test_prompt_adapter_injects_the_shared_world(config) -> None:
    """Every prompt carries the same machine and room, or scenes drift apart."""
    adapter = GenericPromptAdapter(config.visual_styles)
    plan = make_plan([make_scene(continuity_ids=["NOTE_HERO"])])
    prompt = adapter.build_prompt(plan.scenes[0], plan)
    assert plan.world.environment in prompt
    assert "consistent NOTE_HERO" in prompt
    assert "one worn banknote" in prompt
