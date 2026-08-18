"""Scene -> provider prompt (spec section 20).

The director never writes prompt strings. This adapter is the only place that
knows how a particular vendor likes to be spoken to, so swapping vendors does
not touch the director.
"""

from __future__ import annotations

from typing import Protocol

from ...config import VisualStyles
from ...domain import Scene


class VideoPromptAdapter(Protocol):
    name: str

    def build_prompt(self, scene: Scene) -> str: ...

    def build_negative_prompt(self, scene: Scene) -> str: ...


class GenericPromptAdapter:
    """Plain descriptive prompt: subject, environment, action, camera, style.

    Written to be understood by every text-to-video and text-to-image model.
    Add a vendor-specific adapter when a vendor actually needs one -- not before
    (spec section 84).
    """

    name = "generic"

    def __init__(self, styles: VisualStyles) -> None:
        self.styles = styles

    def build_prompt(self, scene: Scene) -> str:
        default = self.styles.default
        reality = self.styles.reality_type_style.get(scene.reality_type.value)
        parts: list[str] = [
            scene.visual_subject.strip(),
            scene.environment.strip(),
            scene.action.strip(),
            f"camera: {scene.camera.strip()}",
        ]
        if scene.framing:
            parts.append(f"framing: {scene.framing.strip()}")
        if scene.lighting:
            parts.append(f"lighting: {scene.lighting.strip()}")
        for spec in scene.continuity:
            parts.append(f"consistent {spec.continuity_id}: {spec.fixed_description.strip()}")
        if reality and reality.suffix.strip():
            parts.append(_squash(reality.suffix))
        if default.base_style.strip():
            parts.append(_squash(default.base_style))
        if default.color_grade.strip():
            parts.append(_squash(default.color_grade))
        if default.motion.strip():
            parts.append(_squash(default.motion))
        return ", ".join(part for part in parts if part)

    def build_negative_prompt(self, scene: Scene) -> str:
        constraints = list(self.styles.default.negative_constraints)
        constraints.extend(scene.negative_constraints)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in constraints:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                ordered.append(item.strip())
        return ", ".join(ordered)


def _squash(text: str) -> str:
    return " ".join(text.split())
