"""Cost tracking and the budget guard (spec sections 29-30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts_factory.config import Budgets
from shorts_factory.cost import BudgetGuard, CostEvent, CostTracker
from shorts_factory.errors import BudgetExceededError


def make_budgets() -> Budgets:
    return Budgets.model_validate(
        {
            "project": {"max_total_usd": 1.0},
            "video": {"max_scene_attempts": 3, "max_high_priority_scenes": 4},
            "image": {"max_scene_attempts": 2},
            "llm": {"max_calls": 2},
            "pricing": {
                "llm": {"p": {"input_usd_per_1k_tokens": 0.01, "output_usd_per_1k_tokens": 0.02}},
                "video": {"p": {"usd_per_second": 0.10}},
                "image": {"p": {"usd_per_image": 0.04}},
                "tts": {"p": {"usd_per_1k_chars": 0.015}},
                "search": {"p": {"usd_per_query": 0.005}},
            },
        }
    )


def test_price_lookup_falls_back_to_zero() -> None:
    budgets = make_budgets()
    assert budgets.price("video", "p", "usd_per_second") == 0.10
    assert budgets.price("video", "unknown", "usd_per_second") == 0.0


def test_estimates_use_configured_prices(tracker: CostTracker) -> None:
    guard = BudgetGuard(make_budgets(), tracker)
    assert guard.estimate_llm_usd("p", 1000, 500) == pytest.approx(0.02)
    assert guard.estimate_video_usd("p", 4.0) == pytest.approx(0.40)
    assert guard.estimate_image_usd("p", 2) == pytest.approx(0.08)
    assert guard.estimate_tts_usd("p", 2000) == pytest.approx(0.03)
    assert guard.estimate_search_usd("p", 6) == pytest.approx(0.03)


def test_total_guard_blocks_an_overrun(tracker: CostTracker) -> None:
    guard = BudgetGuard(make_budgets(), tracker)
    guard.check_total(0.9, operation="video")
    tracker.record(
        CostEvent(kind="video", provider="p", operation="generate_video", actual_cost_usd=0.9)
    )
    with pytest.raises(BudgetExceededError, match="over the"):
        guard.check_total(0.2, operation="video")


def test_llm_call_budget(tracker: CostTracker) -> None:
    guard = BudgetGuard(make_budgets(), tracker)
    for _ in range(2):
        guard.check_llm_call()
        tracker.record(CostEvent(kind="llm", provider="p", operation="research"))
    with pytest.raises(BudgetExceededError, match="LLM call budget"):
        guard.check_llm_call()


def test_video_attempts_are_counted_per_scene(tracker: CostTracker) -> None:
    guard = BudgetGuard(make_budgets(), tracker)
    for _ in range(3):
        guard.check_video_attempt("S01")
        tracker.record(
            CostEvent(kind="video", provider="p", operation="generate_video", scene_id="S01")
        )
    with pytest.raises(BudgetExceededError, match="attempt budget"):
        guard.check_video_attempt("S01")
    guard.check_video_attempt("S02")  # a different scene still has its own budget


def test_ledger_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "costs.jsonl"
    first = CostTracker(path)
    first.record(
        CostEvent(kind="video", provider="p", operation="generate_video", actual_cost_usd=0.25)
    )
    first.record(CostEvent(kind="llm", provider="p", operation="writer", actual_cost_usd=0.01))

    reloaded = CostTracker(path)
    assert reloaded.total_usd() == pytest.approx(0.26)
    assert reloaded.total_for("video") == pytest.approx(0.25)
    assert reloaded.call_count("llm") == 1
    assert "TOTAL" in reloaded.render_table()


def test_estimated_cost_is_used_when_actual_is_unknown(tracker: CostTracker) -> None:
    tracker.record(
        CostEvent(kind="tts", provider="p", operation="synthesize", estimated_cost_usd=0.03)
    )
    assert tracker.total_usd() == pytest.approx(0.03)


def test_unknown_cost_kind_is_rejected(tracker: CostTracker) -> None:
    with pytest.raises(ValueError, match="unknown cost kind"):
        tracker.record(CostEvent(kind="rendering", provider="p", operation="x"))


def test_video_price_prefers_the_model_over_the_provider(tracker: CostTracker) -> None:
    """Veo Standard and Fast differ by 2.7x; one rate per provider would misprice one."""
    budgets = Budgets.model_validate(
        {
            "pricing": {
                "video": {
                    "veo": {"usd_per_second": 0.40},
                    "veo-3.1-fast-generate-preview": {"usd_per_second": 0.15},
                }
            }
        }
    )
    guard = BudgetGuard(budgets, tracker)

    assert guard.estimate_video_usd("veo", 60, "veo-3.1-fast-generate-preview") == pytest.approx(
        9.0
    )
    # An unlisted model falls back to the provider rate rather than to zero.
    assert guard.estimate_video_usd("veo", 60, "veo-9.9-unreleased") == pytest.approx(24.0)
    assert guard.estimate_video_usd("veo", 60) == pytest.approx(24.0)
