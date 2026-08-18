"""Shared QA issue types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["error", "warning"]


class QAIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Level
    code: str
    message: str
    scene_id: str | None = None

    def render(self) -> str:
        where = f" [{self.scene_id}]" if self.scene_id else ""
        return f"{self.level.upper():<7} {self.code}{where}: {self.message}"


class QAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[QAIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[QAIssue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[QAIssue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, issues: list[QAIssue]) -> QAReport:
        self.issues.extend(issues)
        return self

    def render(self) -> str:
        if not self.issues:
            return "no issues"
        return "\n".join(issue.render() for issue in self.issues)


def error(code: str, message: str, scene_id: str | None = None) -> QAIssue:
    return QAIssue(level="error", code=code, message=message, scene_id=scene_id)


def warning(code: str, message: str, scene_id: str | None = None) -> QAIssue:
    return QAIssue(level="warning", code=code, message=message, scene_id=scene_id)
