"""Scene -> provider prompt (spec v0.2 section 20).

The director never writes prompt strings. This adapter is the only place that
knows how a vendor likes to be spoken to, so swapping vendors does not touch
the director.

Two things are injected into *every* prompt regardless of what the director
wrote, because they are what makes twelve clips read as one film:

* the shared world (same machine, same room, same look);
* the Style Bible's `avoid` list, which is the only reliable defence against a
  model turning "explain a mechanism" into glowing holograms and floating UI.
"""

from __future__ import annotations

from typing import Protocol

from ...config import VisualStyles
from ...domain import Scene, ScenePlan


class VideoPromptAdapter(Protocol):
    name: str

    def build_prompt(self, scene: Scene, plan: ScenePlan | None = None) -> str: ...

    def build_negative_prompt(self, scene: Scene) -> str: ...


class GenericPromptAdapter:
    """Plain descriptive prompt: subject, mechanism, visible change, camera, style.

    Written to be understood by every text-to-video and text-to-image model. Add
    a vendor-specific adapter when a vendor actually needs one -- not before.
    """

    name = "generic"

    def __init__(self, styles: VisualStyles) -> None:
        self.styles = styles

    def build_prompt(self, scene: Scene, plan: ScenePlan | None = None) -> str:
        style = self.styles.style
        reality = self.styles.reality_type_style.get(scene.reality_type.value)

        parts: list[str] = [
            scene.visual_subject.strip(),
            scene.environment.strip(),
            scene.action.strip(),
            f"mechanism: {scene.mechanism.strip()}",
            # The change is the shot. Without it a model returns a still life.
            f"visible change during the shot: {scene.visible_change.strip()}",
            f"camera: {scene.camera_path.strip()}",
        ]
        if scene.framing:
            parts.append(f"framing: {scene.framing.strip()}")
        if scene.lighting:
            parts.append(f"lighting: {scene.lighting.strip()}")

        if plan is not None:
            parts.append(f"same machine and location throughout: {plan.world.as_prompt_fragment()}")
            for spec in plan.continuity_for(scene):
                parts.append(f"consistent {spec.continuity_id}: {spec.fixed_description.strip()}")

        if reality and reality.suffix.strip():
            parts.append(_squash(reality.suffix))
        # Realism follows the scene's reality type. "photorealistic" used to be
        # appended to every prompt regardless, so a scene the taxonomy calls a
        # diagram was still ordered as footage.
        parts.append(style.as_prompt_fragment(reality.realism if reality else None))
        parts.append("vertical 9:16 framing, subject inside the safe area")
        return ", ".join(part for part in parts if part.strip())

    def build_negative_prompt(self, scene: Scene) -> str:
        constraints = [*self.styles.style.avoid, *scene.negative_constraints]
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
