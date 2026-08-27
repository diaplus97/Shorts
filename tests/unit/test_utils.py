"""Slug, hashing, timing, text and atomic-write helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from shorts_factory.utils import (
    asset_prompt_hash,
    atomic_write_json,
    atomic_write_text,
    distribute_durations,
    slugify,
    split_for_subtitles,
    stable_hash,
    unique_slug,
    visible_length,
    wrap_cue,
)
from shorts_factory.utils.slug import _FINALS, _INITIALS, _VOWELS, romanize_hangul


def test_hangul_tables_have_the_right_lengths() -> None:
    assert (len(_INITIALS), len(_VOWELS), len(_FINALS)) == (19, 21, 28)


@pytest.mark.parametrize("text", ["값", "없", "읊", "밟", "핣", "힣", "가", "긐"])
def test_romanize_covers_every_syllable_block(text: str) -> None:
    assert romanize_hangul(text)  # must not raise IndexError


def test_slugify_korean_topic() -> None:
    assert slugify("ATM은 돈을 어떻게 세는 걸까?") == "atmeun-doneul-eotteotge-seneun-geolkka"


def test_slugify_falls_back_when_nothing_survives() -> None:
    slug = slugify("!!!???")
    assert slug.startswith("project-")


def test_slugify_respects_max_length() -> None:
    assert len(slugify("a" * 200)) <= 48


def test_unique_slug_appends_a_counter() -> None:
    assert unique_slug("atm", {"atm", "atm-2"}) == "atm-3"
    assert unique_slug("atm", set()) == "atm"


def test_stable_hash_ignores_key_order() -> None:
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_asset_prompt_hash_identity() -> None:
    args = {
        "provider": "mock",
        "model": "m1",
        "prompt": "a wide shot",
        "duration_sec": 4.0,
        "aspect_ratio": "9:16",
        "negative_constraints": ["text", "logos"],
    }
    same = dict(args, negative_constraints=["logos", "text"])
    assert asset_prompt_hash(**args) == asset_prompt_hash(**same)
    assert asset_prompt_hash(**args) != asset_prompt_hash(**dict(args, prompt="other"))
    assert asset_prompt_hash(**args) != asset_prompt_hash(**dict(args, duration_sec=5.0))
    # Sub-10ms jitter in scene timing must not invalidate the cache.
    assert asset_prompt_hash(**args) == asset_prompt_hash(**dict(args, duration_sec=4.001))


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.json"
    atomic_write_json(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in target.parent.iterdir()] == ["out.json"]


def test_atomic_write_replaces_previous_content(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "first")
    atomic_write_text(target, "second")
    assert target.read_text() == "second"


def test_atomic_write_cleans_up_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "out.json"

    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        atomic_write_json(target, {"a": Boom()})
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_distribute_durations_sums_exactly() -> None:
    values = distribute_durations([1, 2, 3, 4, 2, 3, 4, 5, 3, 2], 58.0, min_each=1.5, max_each=9.0)
    assert round(sum(values), 3) == 58.0
    assert all(1.5 <= v <= 9.0 for v in values)


def test_distribute_durations_clamps_a_dominant_weight() -> None:
    values = distribute_durations([1000, 1, 1, 1, 1, 1, 1, 1], 58.0, min_each=1.5, max_each=9.0)
    assert max(values) <= 9.0
    assert round(sum(values), 3) == 58.0


def test_distribute_durations_rejects_impossible_bounds() -> None:
    with pytest.raises(ValueError, match="min"):
        distribute_durations([1, 1], 1.0, min_each=1.5, max_each=9.0)
    with pytest.raises(ValueError, match="max"):
        distribute_durations([1, 1], 100.0, min_each=1.5, max_each=9.0)
    with pytest.raises(ValueError):
        distribute_durations([], 10.0, min_each=1.0, max_each=5.0)


def test_visible_length_ignores_whitespace() -> None:
    assert visible_length("가 나  다\n라") == 4


def test_split_for_subtitles_respects_the_cap_and_merges_fragments() -> None:
    text = "이 장치의 내부는 입력, 이송, 판별, 저장의 네 구간으로 나뉜다. 첫 단계에서는 센서가 감지한다."
    chunks = split_for_subtitles(text, 30)
    assert chunks
    assert all(len(chunk) <= 30 for chunk in chunks)
    # Fragments like "이송," must not survive as their own cue.
    assert all(len(chunk) > 5 for chunk in chunks)


def test_wrap_cue_never_exceeds_the_line_budget() -> None:
    cue = wrap_cue("가나다라마바사아자차카타파하가나다라마바사", 10, 2)
    assert cue.count("\n") <= 1


def test_env_is_not_leaked_by_slugify() -> None:
    # Guards against accidentally interpolating secrets into a directory name.
    os.environ["OPENAI_API_KEY"] = "sk-should-not-appear"
    try:
        assert "sk-should-not-appear" not in slugify("topic")
    finally:
        del os.environ["OPENAI_API_KEY"]


def test_every_accepted_secret_name_is_also_redacted() -> None:
    """An alias is exactly as secret as the canonical name.

    Accepting FAL_API_KEY as well as FAL_KEY is a convenience; leaving the
    alias out of the redaction list would make it a way to get a live key into
    a log file. The two lists have to be added to together, so this fails if
    only one of them is.
    """
    from shorts_factory.providers.base import SECRET_ALIASES, secret_names
    from shorts_factory.utils.logging import _SECRET_ENV_NAMES

    accepted = {name for canonical in SECRET_ALIASES for name in secret_names(canonical)}
    assert accepted <= set(_SECRET_ENV_NAMES), (
        f"these names satisfy a provider but are never redacted: "
        f"{sorted(accepted - set(_SECRET_ENV_NAMES))}"
    )


def test_an_alias_value_is_redacted_from_a_log_line(monkeypatch) -> None:
    from shorts_factory.utils.logging import redact_secrets

    monkeypatch.setenv("FAL_API_KEY", "fal-secret-value-1234")
    out = redact_secrets(None, "info", {"event": "x", "url": "https://q/?k=fal-secret-value-1234"})
    assert "fal-secret-value-1234" not in str(out)


def test_no_script_reads_a_secret_straight_from_the_environment() -> None:
    """Aliases only help if everything resolves secrets the same way.

    ``require_secret`` accepts FAL_API_KEY for FAL_KEY, but probe_fal.py read
    os.environ["FAL_KEY"] directly, so it reported the key missing -- while
    printing "did you mean FAL_API_KEY?" about a key that was present and would
    have worked in a real run. Three scripts had the same bug. A lookup that
    bypasses find_secret disagrees with the pipeline about what is configured.
    """
    import re

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"""environ(?:\.get\(|\[)['"]([A-Z_]*(?:KEY|SECRET|TOKEN))['"]""")

    offenders: list[str] = []
    for path in [*(root / "scripts").glob("*.py"), *(root / "src").rglob("*.py")]:
        # base.py is where find_secret is implemented; it has to read os.environ.
        if path.name == "base.py" and path.parent.name == "providers":
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(root)}:{line_no}: {line.strip()}")

    assert not offenders, "these read a secret without alias resolution:\n" + "\n".join(offenders)


def test_an_empty_key_is_reported_as_empty_not_as_missing(tmp_path, monkeypatch) -> None:
    """A blank line in .env is present and does not work.

    Reporting only names put "search needs SEARCH_API_KEY" directly underneath
    a list containing SEARCH_API_KEY, which reads as a broken check rather than
    as an empty line in a file.
    """
    from shorts_factory.scripts_doctor import env_entries

    env = tmp_path / ".env"
    env.write_text("IMAGE_API_KEY=abcdef123456\nSEARCH_API_KEY=\n# LLM_API_KEY=x\n")
    entries = env_entries(env)

    assert entries == {"IMAGE_API_KEY": True, "SEARCH_API_KEY": False}
    assert "abcdef123456" not in str(entries), "the value must never be reported"
