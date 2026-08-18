"""Quality gates. Small focused checks, not one large QA agent (spec section 36)."""

from .fact_check import (
    FactCheckFinding,
    FactCheckReport,
    affected_scenes,
    check_research,
    check_scene_traceability,
    check_script_traceability,
    fact_lock_issues,
)
from .report import QAIssue, QAReport, error, warning
from .scene_check import check_assets, check_scene_plan, check_script
from .technical_check import check_clip, check_final_video

__all__ = [
    "FactCheckFinding",
    "FactCheckReport",
    "QAIssue",
    "QAReport",
    "affected_scenes",
    "check_assets",
    "check_clip",
    "check_final_video",
    "check_research",
    "check_scene_plan",
    "check_scene_traceability",
    "check_script",
    "check_script_traceability",
    "error",
    "fact_lock_issues",
    "warning",
]
