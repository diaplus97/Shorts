"""Builders for domain objects used across the test suite.

Kept in one place so a schema change lands here once instead of in every test.
"""

from __future__ import annotations

from typing import Any

from shorts_factory.domain import (
    AssetType,
    BeatPurpose,
    Claim,
    ClaimConfidence,
    ContinuitySpec,
    DeliveryMode,
    QuestionSpec,
    RealityType,
    ResearchResult,
    Scene,
    ScenePlan,
    ScenePriority,
    ScriptBeat,
    ScriptResult,
    SourceRef,
    SpeechPlan,
    SpeechTimeline,
    SpeechTimingEntry,
    SpeechUnit,
    ToneProfile,
    WorldSpec,
)

TOPIC = "ATM은 돈을 어떻게 세는 걸까?"
RESOLVED = "현금 입금이 가능한 ATM은 들어온 지폐를 어떻게 한 장씩 분리할까?"


def make_world(**overrides: Any) -> WorldSpec:
    base = {
        "machine_id": "ATM_DEPOSIT_001",
        "visual_style": "documentary CGI cutaway",
        "environment": "a modern Korean indoor ATM booth",
    }
    return WorldSpec(**(base | overrides))


def make_scene(**overrides: Any) -> Scene:
    base: dict[str, Any] = {
        "id": "S01",
        "order": 1,
        "narration": "고무 롤러가 지폐를 한 장씩 끌어당깁니다.",
        "duration_sec": 4.0,
        "purpose": "process",
        "question_answered": "How does one note leave the stack?",
        "key_object": "a single banknote",
        "mechanism": "a rubber feed roller grips the front note",
        "visible_change": "stack at rest → one note moving inward",
        "visual_subject": "ATM feed roller and a banknote",
        "environment": "inside the deposit path",
        "action": "the roller turns and one note slides ahead",
        "camera_path": "macro tracking shot following the note",
        "reality_type": RealityType.RECONSTRUCTED,
        "priority": ScenePriority.MEDIUM,
        "asset_type": AssetType.VIDEO,
    }
    return Scene(**(base | overrides))


def make_plan(scenes: list[Scene] | None = None, **overrides: Any) -> ScenePlan:
    base: dict[str, Any] = {
        "world": make_world(),
        "scenes": scenes if scenes is not None else [make_scene()],
        "continuity": [
            ContinuitySpec(continuity_id="NOTE_HERO", fixed_description="one worn banknote")
        ],
    }
    return ScenePlan(**(base | overrides))


def make_tone(**overrides: Any) -> ToneProfile:
    base = {
        "persona": "calm_curiosity_documentary",
        "formality": "polite_conversational",
        "energy": "moderate",
        "sentence_style": "spoken, concrete, visual, concise",
    }
    return ToneProfile(**(base | overrides))


def make_unit(
    unit_id: str = "U01", text: str = "고무 롤러가 한 장씩 떼어냅니다.", **overrides: Any
) -> SpeechUnit:
    base: dict[str, Any] = {
        "id": unit_id,
        "text": text,
        "pause_after_ms": 320,
        "delivery": DeliveryMode.NEUTRAL,
        "referenced_claim_ids": ["C01"],
    }
    return SpeechUnit(**(base | overrides))


def make_speech_plan(units: list[SpeechUnit] | None = None, **overrides: Any) -> SpeechPlan:
    base: dict[str, Any] = {
        "tone_profile": make_tone(),
        "units": units if units is not None else [make_unit()],
        "target_duration_sec": 58.0,
    }
    return SpeechPlan(**(base | overrides))


def make_timeline(plan: SpeechPlan, unit_duration: float = 2.0) -> SpeechTimeline:
    """A timeline as if every unit took `unit_duration` seconds to say."""
    entries: list[SpeechTimingEntry] = []
    cursor = 0.0
    for index, unit in enumerate(plan.units):
        gap = unit.pause_after_ms / 1000 if index < len(plan.units) - 1 else 0.0
        entries.append(
            SpeechTimingEntry(
                unit_id=unit.id, start=round(cursor, 3), duration=unit_duration, gap_after=gap
            )
        )
        cursor = round(cursor + unit_duration + gap, 3)
    return SpeechTimeline(entries=entries, total_duration_sec=round(cursor, 3))


def make_scenes(
    count: int,
    narration: str,
    total: float = 58.0,
    *,
    claim_ids: list[str] | None = None,
) -> ScenePlan:
    """`count` scenes whose narration concatenates back to `narration`."""
    per = total / count
    chunk = len(narration) // count
    scenes = []
    for index in range(count):
        start = index * chunk
        end = len(narration) if index == count - 1 else (index + 1) * chunk
        scenes.append(
            make_scene(
                id=f"S{index + 1:02d}",
                order=index + 1,
                narration=narration[start:end],
                duration_sec=round(per, 3),
                claim_ids=claim_ids if claim_ids is not None else ["C01"],
                continuity_ids=["NOTE_HERO"],
            )
        )
    return make_plan(scenes)


def make_question(**overrides: Any) -> QuestionSpec:
    base = {
        "original_topic": TOPIC,
        "resolved_question": RESOLVED,
        "scope": "현금 입금형 ATM의 지폐 수납 경로",
        "excluded": ["제조사별 비공개 설계"],
    }
    return QuestionSpec(**(base | overrides))


def make_source(source_id: str = "S01") -> SourceRef:
    return SourceRef(id=source_id, title="mock", url=f"https://example.invalid/{source_id}")


def make_claim(claim_id: str = "C01", **overrides: Any) -> Claim:
    base: dict[str, Any] = {
        "id": claim_id,
        "statement": "고무 롤러가 지폐를 한 장씩 떼어낸다.",
        "confidence": ClaimConfidence.HIGH,
        "source_ids": ["S01"],
        "visualizable": True,
    }
    return Claim(**(base | overrides))


def make_research(
    claims: list[Claim] | None = None,
    sources: list[SourceRef] | None = None,
    **overrides: Any,
) -> ResearchResult:
    base: dict[str, Any] = {
        "topic": TOPIC,
        "question": make_question(),
        "summary": "고무 롤러가 지폐를 한 장씩 떼어내 이송로로 보냅니다.",
        "claims": claims if claims is not None else [make_claim()],
        "sources": sources if sources is not None else [make_source()],
    }
    return ResearchResult(**(base | overrides))


def make_beat(beat_id: str = "B01", **overrides: Any) -> ScriptBeat:
    base: dict[str, Any] = {
        "id": beat_id,
        "purpose": BeatPurpose.PROCESS,
        "text": "고무 롤러가 지폐를 한 장씩 떼어낸다.",
        "claim_ids": ["C01"],
        "visualizable": True,
        "visual_payoff": "롤러가 돌며 맨 앞 지폐 한 장이 밀려 나간다",
    }
    return ScriptBeat(**(base | overrides))


def make_script(narration_chars: int = 360, **overrides: Any) -> ScriptResult:
    """A contract-satisfying script whose narration is `narration_chars` long."""
    hook = "ATM 속 지폐는 어떻게 한 장이 될까?"
    body = "가" * max(narration_chars - len(hook.replace(" ", "")), 1)
    beats = [
        make_beat(
            "B01",
            purpose=BeatPurpose.HOOK,
            text=hook,
            claim_ids=[],
            visual_payoff="카메라가 다가간다",
        ),
        make_beat("B02", text=body),
    ]
    base: dict[str, Any] = {
        "title": "ATM 지폐 분리",
        "hook": hook,
        "narration": f"{hook} {body}",
        "beats": beats,
        "target_duration_sec": 58,
        "resolved_question": RESOLVED,
        "referenced_claim_ids": ["C01"],
    }
    return ScriptResult(**(base | overrides))
