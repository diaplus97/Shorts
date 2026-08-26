"""Director stage schemas (spec v0.2 sections 15-16).

A Scene describes the *meaning* of a shot. It never stores a provider-specific
prompt string; that is the job of the prompt adapters.

The v0.2 addition is that a scene must justify its own existence: it names the
question it answers, the mechanism it shows, and — most importantly — the
`visible_change` the viewer actually sees happen. A shot with nothing changing
on screen is static exposition, and the contract rejects it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import AssetType, RealityType, ScenePriority


class ContinuitySpec(BaseModel):
    """Identity of a recurring object or location (spec sections 31-32)."""

    model_config = ConfigDict(extra="forbid")

    continuity_id: str
    fixed_description: str


class ColourRole(BaseModel):
    """One part of the machine, always drawn in one colour.

    Colour is the cheapest way to say "this is the same component you saw four
    seconds ago" without the narration having to. It only works if it never
    moves, which is why it is declared once for the whole Short rather than
    described per scene.
    """

    model_config = ConfigDict(extra="forbid")

    #: What is being coloured: "pickup roller", "reject path", "the banknote".
    part: str
    #: A plain colour name a generation model will not misread. Not a hex code.
    colour: str
    #: Why it is that colour, when the reason is load-bearing -- normal path
    #: green against reject path red only reads if they are opposites.
    meaning: str | None = None

    def as_prompt_fragment(self) -> str:
        return f"{self.part} is always {self.colour}"


class WorldSpec(BaseModel):
    """The single physical world every scene in one Short shares.

    Without this, twelve scenes become twelve unrelated clips. With it they are
    twelve shots of one machine (spec v0.2 section 31).

    Prose alone turned out not to be enough. A one-line description of a machine
    lets a generation model rebuild the machine differently for every cut --
    different roller count, different layout, banknotes travelling a different
    way -- and the result is twelve clips of twelve machines that each look
    plausible. The fields below are the parts a viewer uses to recognise that
    two shots are of the same object, so they are declared once and repeated
    into every prompt rather than left to prose.
    """

    model_config = ConfigDict(extra="forbid")

    machine_id: str
    visual_style: str
    environment: str

    #: The one view the whole Short is filmed from -- "vertical cross-section
    #: cut through the deposit module, seen from the left side". Every scene is
    #: a closer or wider look at *this* view, never a different one.
    cross_section: str | None = None

    #: Which way the thing being followed travels through the frame. A banknote
    #: going right in one shot and left in the next reads as two machines.
    travel_direction: (
        Literal["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"] | None
    ) = None

    #: Fixed colours for the parts that recur. Keep it short: past about four,
    #: nothing is distinguishable and the picture turns into a parts catalogue.
    colour_roles: list[ColourRole] = Field(default_factory=list)

    notes: str | None = None

    def as_prompt_fragment(self) -> str:
        parts = [self.environment.strip(), self.visual_style.strip()]
        if self.cross_section:
            parts.append(f"always the same view: {self.cross_section.strip()}")
        if self.travel_direction:
            parts.append(f"movement travels {self.travel_direction.replace('_', ' ')}")
        parts.extend(role.as_prompt_fragment() for role in self.colour_roles)
        if self.notes:
            parts.append(self.notes.strip())
        return ", ".join(part for part in parts if part)


class HighlightSpec(BaseModel):
    """A rectangle drawn over one shot to point at the part being described.

    The reference Short does this constantly: the narration names a component
    and a box appears around it, so the viewer knows which of the twenty things
    on screen is the one being talked about. Without it a wide shot of a machine
    is the viewer's problem to parse, which is the failure mode this pipeline
    kept producing -- a correct picture that explains nothing because nothing in
    it is pointed at.

    Coordinates are fractions of the frame, not pixels, so the same spec
    survives a resolution change. ``x``/``y`` are the top-left corner.
    """

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    #: When the box appears, measured from the start of the shot. A box that is
    #: up before the narration reaches its subject points at nothing.
    start_sec: float = Field(default=0.0, ge=0.0)
    #: How long it stays. None means "until the shot ends".
    duration_sec: float | None = Field(default=None, gt=0.0)

    #: What this box is around, in plain words. Not rendered -- on-screen text
    #: needs ``drawtext``, which common static ffmpeg builds ship without -- but
    #: it is what makes a generated box reviewable without watching the video.
    label: str | None = None

    @model_validator(mode="after")
    def _inside_the_frame(self) -> HighlightSpec:
        if self.x + self.width > 1.0001:
            raise ValueError(f"highlight runs off the right edge: x={self.x} width={self.width}")
        if self.y + self.height > 1.0001:
            raise ValueError(f"highlight runs off the bottom edge: y={self.y} height={self.height}")
        return self


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int = Field(ge=1)

    narration: str = ""
    #: Short on-screen text. Subtitles use this when set, so captions do not
    #: have to be a literal transcript of the narration.
    caption: str | None = None
    subtitle_position: Literal["bottom", "top"] = "bottom"

    duration_sec: float = Field(gt=0)
    purpose: str

    #: What the viewer learns from this shot, phrased as a question.
    question_answered: str
    #: The one thing the camera is actually looking at.
    key_object: str
    #: The physical mechanism at work, in plain descriptive language.
    mechanism: str
    #: What visibly changes between the first and last frame.
    visible_change: str

    visual_subject: str
    environment: str
    action: str

    #: How the camera moves through the world during the shot.
    camera_path: str
    framing: str | None = None
    lighting: str | None = None

    reality_type: RealityType
    priority: ScenePriority
    asset_type: AssetType

    #: The speech units this scene covers, in order. A scene holds whole units,
    #: which is what stops a cut from landing mid-sentence.
    speech_unit_ids: list[str] = Field(default_factory=list)
    #: References into ``ScenePlan.continuity``; descriptions are not repeated.
    continuity_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)

    #: An optional box drawn over this shot to point at what is being named.
    highlight: HighlightSpec | None = None

    transition_in: str | None = None
    transition_out: str | None = None
    #: Name from `config/sfx.yaml` vocabulary, or None for a silent scene.
    sfx_cue: str | None = None

    negative_constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _highlight_fits_the_shot(self) -> Scene:
        """A box cannot start after the shot it is drawn on has ended."""
        box = self.highlight
        if box is None:
            return self
        if box.start_sec >= self.duration_sec:
            raise ValueError(
                f"scene {self.id}: highlight starts at {box.start_sec}s but the shot is "
                f"only {self.duration_sec}s long"
            )
        return self

    @field_validator("duration_sec")
    @classmethod
    def _sane_duration(cls, value: float) -> float:
        if not 0.5 <= value <= 15.0:
            raise ValueError("scene duration_sec must be between 0.5 and 15.0 seconds")
        return value

    @model_validator(mode="after")
    def _required_text_fields(self) -> Scene:
        required = (
            "purpose",
            "question_answered",
            "key_object",
            "mechanism",
            "visible_change",
            "visual_subject",
            "environment",
            "action",
            "camera_path",
        )
        for field in required:
            if not getattr(self, field).strip():
                raise ValueError(f"scene {self.id}: '{field}' must not be empty")
        return self

    @property
    def subtitle_text(self) -> str:
        """What actually goes on screen for this scene."""
        return (self.caption or self.narration).strip()


class ScenePlan(BaseModel):
    """The full ordered set of scenes for one Short, plus the world they share."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.1"

    world: WorldSpec
    scenes: list[Scene] = Field(default_factory=list)
    #: Registry of recurring objects and locations, referenced by id.
    continuity: list[ContinuitySpec] = Field(default_factory=list)
    visual_notes: str | None = None

    prompt_version: str | None = None
    prompt_hash: str | None = None

    @field_validator("scenes")
    @classmethod
    def _ordered_and_unique(cls, scenes: list[Scene]) -> list[Scene]:
        ids = [scene.id for scene in scenes]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"duplicate scene ids: {sorted(duplicates)}")
        orders = [scene.order for scene in scenes]
        if orders != sorted(orders):
            raise ValueError("scenes must be sorted by ascending order")
        if len(set(orders)) != len(orders):
            raise ValueError("scene order values must be unique")
        return scenes

    @field_validator("continuity")
    @classmethod
    def _unique_continuity_ids(cls, specs: list[ContinuitySpec]) -> list[ContinuitySpec]:
        ids = [spec.continuity_id for spec in specs]
        duplicates = {cid for cid in ids if ids.count(cid) > 1}
        if duplicates:
            raise ValueError(f"duplicate continuity ids: {sorted(duplicates)}")
        return specs

    @model_validator(mode="after")
    def _continuity_references_resolve(self) -> ScenePlan:
        known = {spec.continuity_id for spec in self.continuity}
        for scene in self.scenes:
            unknown = [cid for cid in scene.continuity_ids if cid not in known]
            if unknown:
                raise ValueError(f"scene {scene.id} references unknown continuity ids {unknown}")
        return self

    @property
    def total_duration_sec(self) -> float:
        return round(sum(scene.duration_sec for scene in self.scenes), 3)

    def scene_by_id(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def continuity_by_id(self, continuity_id: str) -> ContinuitySpec | None:
        return next((c for c in self.continuity if c.continuity_id == continuity_id), None)

    def continuity_for(self, scene: Scene) -> list[ContinuitySpec]:
        resolved = [self.continuity_by_id(cid) for cid in scene.continuity_ids]
        return [spec for spec in resolved if spec is not None]
