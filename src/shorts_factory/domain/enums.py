"""Enumerations shared by every stage of the pipeline."""

from __future__ import annotations

from enum import StrEnum


class ContentType(StrEnum):
    """The three Invisible World content concepts (spec section 2)."""

    HIDDEN_SYSTEM = "hidden_system"
    INSIDE_OBJECT = "inside_object"
    BEHIND_ACTION = "behind_action"


class RealityType(StrEnum):
    """How literally a scene should be read (spec section 17)."""

    OBSERVED = "observed"
    RECONSTRUCTED = "reconstructed"
    CONCEPTUAL = "conceptual"


class ScenePriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BeatPurpose(StrEnum):
    """Where a narration beat sits in the 45-70s arc (spec v0.2 section 14)."""

    HOOK = "hook"
    REVEAL = "reveal"
    PROCESS = "process"
    SURPRISE = "surprise"
    CLOSING = "closing"
    TRANSITION = "transition"


#: Beats that may carry no claim id, because they assert no fact.
NON_FACTUAL_PURPOSES = frozenset({BeatPurpose.HOOK, BeatPurpose.CLOSING, BeatPurpose.TRANSITION})


class ClaimConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AssetType(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    IMAGE_MOTION = "image_motion"


class AssetStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineState(StrEnum):
    """Coarse project lifecycle state (spec section 44)."""

    CREATED = "created"
    RESEARCHED = "researched"
    SCRIPTED = "scripted"
    FACT_LOCKED = "fact_locked"
    SPOKEN = "spoken"
    DIRECTED = "directed"
    ASSETS_READY = "assets_ready"
    AUDIO_READY = "audio_ready"
    VALIDATED = "validated"
    COMPOSED = "composed"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    """Named pipeline stages. Order matters: it defines `--until` semantics."""

    RESEARCH = "research"
    WRITE = "write"
    FACT_LOCK = "fact_lock"
    SPEAK = "speak"
    DIRECT = "direct"
    GENERATE = "generate"
    NARRATE = "narrate"
    VALIDATE = "validate"
    COMPOSE = "compose"


#: Canonical execution order of the pipeline.
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.RESEARCH,
    Stage.WRITE,
    Stage.FACT_LOCK,
    Stage.SPEAK,
    Stage.DIRECT,
    Stage.GENERATE,
    Stage.NARRATE,
    Stage.VALIDATE,
    Stage.COMPOSE,
)

#: Pipeline state reached once a stage completes successfully.
STAGE_COMPLETION_STATE: dict[Stage, PipelineState] = {
    Stage.RESEARCH: PipelineState.RESEARCHED,
    Stage.WRITE: PipelineState.SCRIPTED,
    Stage.FACT_LOCK: PipelineState.FACT_LOCKED,
    Stage.SPEAK: PipelineState.SPOKEN,
    Stage.DIRECT: PipelineState.DIRECTED,
    Stage.GENERATE: PipelineState.ASSETS_READY,
    Stage.NARRATE: PipelineState.AUDIO_READY,
    Stage.VALIDATE: PipelineState.VALIDATED,
    Stage.COMPOSE: PipelineState.COMPOSED,
}


def stages_up_to(until: Stage | None) -> tuple[Stage, ...]:
    """Return the stages to run, truncated at and including ``until``."""
    if until is None:
        return STAGE_ORDER
    index = STAGE_ORDER.index(until)
    return STAGE_ORDER[: index + 1]
