"""Budget guard (spec section 29).

Every paid call asks the guard for permission first. Prices and limits come from
``config/budgets.yaml`` -- nothing is hardcoded here.
"""

from __future__ import annotations

from ..config import Budgets
from ..domain import ScenePriority
from ..errors import BudgetExceededError
from .tracker import CostTracker


class BudgetGuard:
    def __init__(self, budgets: Budgets, tracker: CostTracker) -> None:
        self.budgets = budgets
        self.tracker = tracker

    # -- pricing ---------------------------------------------------------

    def estimate_llm_usd(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        in_price = self.budgets.price("llm", provider, "input_usd_per_1k_tokens")
        out_price = self.budgets.price("llm", provider, "output_usd_per_1k_tokens")
        return round(input_tokens / 1000 * in_price + output_tokens / 1000 * out_price, 6)

    def estimate_search_usd(self, provider: str, queries: int) -> float:
        return round(queries * self.budgets.price("search", provider, "usd_per_query"), 6)

    def estimate_image_usd(self, provider: str, images: int) -> float:
        return round(images * self.budgets.price("image", provider, "usd_per_image"), 6)

    def estimate_video_usd(self, provider: str, seconds: float, model: str | None = None) -> float:
        """Price a clip, preferring a rate listed for the exact model.

        Veo Standard and Veo Fast differ by roughly 2.7x per second, so a single
        rate per provider would be wrong for one of them. A model entry wins;
        the provider entry is the fallback.
        """
        rate = self.budgets.price("video", model, "usd_per_second") if model else 0.0
        if not rate:
            rate = self.budgets.price("video", provider, "usd_per_second")
        return round(seconds * rate, 6)

    def estimate_tts_usd(self, provider: str, characters: int) -> float:
        return round(characters / 1000 * self.budgets.price("tts", provider, "usd_per_1k_chars"), 6)

    # -- guards ----------------------------------------------------------

    @property
    def remaining_usd(self) -> float:
        return round(self.budgets.project.max_total_usd - self.tracker.total_usd(), 6)

    def check_total(self, additional_usd: float, *, operation: str) -> None:
        projected = self.tracker.total_usd() + additional_usd
        limit = self.budgets.project.max_total_usd
        if projected > limit:
            raise BudgetExceededError(
                f"{operation} would bring project cost to ${projected:.4f}, "
                f"over the ${limit:.2f} limit (config/budgets.yaml: project.max_total_usd)"
            )

    def check_llm_call(self) -> None:
        used = self.tracker.call_count("llm")
        limit = self.budgets.llm.max_calls
        if used >= limit:
            raise BudgetExceededError(
                f"LLM call budget exhausted: {used}/{limit} calls "
                f"(config/budgets.yaml: llm.max_calls)"
            )

    def check_video_attempt(self, scene_id: str) -> None:
        used = self.tracker.scene_attempts("video", scene_id)
        limit = self.budgets.video.max_scene_attempts
        if used >= limit:
            raise BudgetExceededError(
                f"scene {scene_id}: video attempt budget exhausted ({used}/{limit})"
            )

    def check_image_attempt(self, scene_id: str) -> None:
        used = self.tracker.scene_attempts("image", scene_id)
        limit = self.budgets.image.max_scene_attempts
        if used >= limit:
            raise BudgetExceededError(
                f"scene {scene_id}: image attempt budget exhausted ({used}/{limit})"
            )

    def high_priority_allowance(self) -> int:
        return self.budgets.video.max_high_priority_scenes

    def clamp_high_priority(self, priorities: list[ScenePriority]) -> int:
        """Count how many HIGH scenes exceed the allowance (0 means fine)."""
        high = sum(1 for priority in priorities if priority is ScenePriority.HIGH)
        return max(0, high - self.high_priority_allowance())
