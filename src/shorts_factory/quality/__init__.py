"""Quality gates. Small focused checks, not one large QA agent (spec section 36)."""

from .content_contract import (
    check_concrete_mechanism,
    check_generic_nouns,
    check_hook,
    check_scene_contract,
    check_script_contract,
)
from .fact_check import (
    FactCheckFinding,
    FactCheckReport,
    affected_scenes,
    check_research,
    check_scene_traceability,
    check_script_traceability,
    fact_lock_issues,
)
from .korean_register import (
    check_deictic_density,
    check_korean_register,
    check_language,
    check_translationese,
)
from .production import ProductionReadinessResult, assess, mock_provider_kinds
from .report import QAIssue, QAReport, error, warning
from .scene_check import check_assets, check_scene_plan, check_script
from .script_arc import (
    check_beat_arc,
    check_causal_linkage,
)
from .speech_contract import (
    check_ending_repetition,
    check_rhythm,
    check_scene_speech_alignment,
    check_speech_plan,
    check_unit_lengths,
    units_in_scene_order,
)
from .technical_check import check_clip, check_final_video

__all__ = [
    "FactCheckFinding",
    "FactCheckReport",
    "ProductionReadinessResult",
    "QAIssue",
    "QAReport",
    "affected_scenes",
    "assess",
    "check_assets",
    "check_beat_arc",
    "check_causal_linkage",
    "check_clip",
    "check_concrete_mechanism",
    "check_deictic_density",
    "check_ending_repetition",
    "check_final_video",
    "check_generic_nouns",
    "check_hook",
    "check_korean_register",
    "check_language",
    "check_research",
    "check_rhythm",
    "check_scene_contract",
    "check_scene_plan",
    "check_scene_speech_alignment",
    "check_scene_traceability",
    "check_script",
    "check_script_contract",
    "check_script_traceability",
    "check_speech_plan",
    "check_translationese",
    "check_unit_lengths",
    "error",
    "fact_lock_issues",
    "mock_provider_kinds",
    "units_in_scene_order",
    "warning",
]
