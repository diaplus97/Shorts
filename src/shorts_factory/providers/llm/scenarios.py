"""Fixture scenarios for :class:`MockLLMProvider`.

A mock exists to model what a real provider returns. If it returns vague
placeholder text, the content-quality checks can only ever be tested against
material that would fail in production, which is worse than not testing them.

So each scenario here is written the way a good research/writer/director pass
should look: named parts, concrete actions, and a stated visible change per
shot. Everything is still clearly labelled `[MOCK]` upstream, and the research
summary says outright that it is not real reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    """One claim and the shot that shows it."""

    #: Korean claim statement, written register, used by research.
    statement: str
    #: Korean, what the viewer sees while the sentence is spoken.
    visual_payoff: str
    #: Korean, the short on-screen caption.
    caption: str
    #: English fields consumed by image and video models.
    key_object: str
    mechanism: str
    visible_change: str
    camera_path: str
    visual_subject: str
    action: str
    continuity_ids: tuple[str, ...] = ()
    visualizable: bool = True
    #: Korean narration line, spoken register. This is what the writer says;
    #: `statement` stays in written register for the research claim.
    spoken: str = ""
    #: One word in `spoken` to stress on screen. Empty means no highlight.
    emphasis: str = ""
    #: Name from the config SFX vocabulary. "none" leaves the scene silent.
    sfx_cue: str = "none"


@dataclass(frozen=True)
class Scenario:
    """A complete hand-written run for one topic."""

    match: tuple[str, ...]
    resolved_question: str
    scope: str
    excluded: tuple[str, ...]
    summary: str
    hook: str
    #: The obvious answer, and why it fails. Required by the arc: without it
    #: every step that follows is an answer to nothing.
    problem: Step
    reveal: Step
    steps: tuple[Step, ...]
    surprise: Step
    closing: Step
    world_machine_id: str
    world_visual_style: str
    world_environment: str
    continuity: tuple[tuple[str, str], ...] = field(default=())

    def all_steps(self) -> tuple[Step, ...]:
        # In arc order, so research emits one claim per beat and the mock
        # writer can map them back by index.
        return (self.problem, self.reveal, *self.steps, self.surprise, self.closing)

    def spoken_lines(self) -> list[str]:
        return [step.spoken or step.statement for step in self.all_steps()]

    def step_for_spoken(self, spoken: str) -> Step | None:
        """Find the shot behind a narration line the writer emitted."""
        return next(
            (step for step in self.all_steps() if (step.spoken or step.statement) == spoken),
            None,
        )


ATM = Scenario(
    match=("ATM", "atm", "현금인출기", "현금 자동"),
    resolved_question="현금 입금이 가능한 ATM은 들어온 지폐를 어떻게 한 장씩 분리하고 확인할까?",
    scope="현금 입금·환류(recycling)형 ATM의 지폐 수납 경로",
    excluded=(
        "제조사별 비공개 설계",
        "인출 전용 ATM의 방출 경로",
        "위조지폐 판별의 구체적 검증 항목",
    ),
    summary=(
        "입금구에 들어간 지폐 뭉치는 고무 롤러가 한 장씩 떼어내 안쪽 이송로로 보냅니다. "
        "이송로를 지나는 동안 광학 센서와 두께 센서가 지폐의 무늬와 두께를 읽습니다. "
        "읽히지 않거나 겹쳐 들어온 지폐는 되돌림 상자로 따로 빠집니다. "
        "확인을 마친 지폐만 금액별 카세트에 쌓입니다."
    ),
    hook="ATM은 지폐를 어떻게 한 장씩 셀까요?",
    problem=Step(
        statement="지폐 뭉치는 서로 붙어 있어 세는 것만으로는 낱장을 구분할 수 없다.",
        spoken=(
            "뻔한 답은 그냥 세는 겁니다. 그런데 지폐는 서로 달라붙어 있어서, "
            "뭉치 그대로는 몇 장인지 알 수가 없죠."
        ),
        sfx_cue="none",
        visual_payoff="지폐 뭉치가 서로 붙은 채 그대로 놓여 있다",
        caption="뭉치로는 셀 수 없다",
        key_object="a stack of banknotes stuck together",
        mechanism="the notes cling to each other and cannot be told apart",
        visible_change="a loose stack → the same stack, still inseparable",
        camera_path="slow push-in on the edge of the stack",
        visual_subject="a stack of banknotes seen edge on",
        action="the stack sits unmoved, its edges indistinguishable",
        continuity_ids=("NOTE_HERO",),
    ),
    reveal=Step(
        statement="입금구 안쪽은 롤러와 벨트가 이어진 하나의 이송로다.",
        spoken=(
            "그래서 입금구 안쪽은 통로 하나로 이어져 있습니다. "
            "롤러와 벨트, 센서가 한 줄로 놓인 길이고, 지폐는 이 길을 처음부터 끝까지 지나갑니다."
        ),
        sfx_cue="mechanical_reveal",
        visual_payoff="입금구가 단면으로 열리고 롤러와 벨트가 이어진 통로가 드러난다",
        caption="하나로 이어진 길",
        key_object="the deposit slot opening into a single transport path",
        mechanism="the casing peels away to show rollers and belts in one line",
        visible_change="closed deposit slot → sectional view of the whole path",
        camera_path="push in on the slot, then the casing peels away",
        visual_subject="cutaway of the ATM deposit transport path",
        action="the outer panel dissolves into a clean sectional view",
        continuity_ids=("ATM_MAIN",),
    ),
    steps=(
        Step(
            statement="고무 롤러가 맨 앞 지폐 한 장만 마찰로 끌어당겨 분리한다.",
            spoken=(
                "그래서 기계가 가장 먼저 하는 일은 한 장씩 떼어내는 겁니다. "
                "고무 롤러가 맨 앞 지폐만 살짝 끌어당기고, 반대로 도는 롤러가 "
                "뒤따라온 두 번째 장을 붙잡아 되밀어 냅니다."
            ),
            sfx_cue="transport_roller",
            visual_payoff="롤러가 맨 앞 지폐만 끌어당기고 두 번째 장은 밀려 되돌아간다",
            caption="한 장씩 떼어낸다",
            key_object="rubber feed roller separating one banknote from a stack",
            mechanism="a feed roller grips the front note while a reverse roller holds the next",
            visible_change="stack at rest → one note peeled off, the next pushed back",
            camera_path="macro tracking shot alongside the roller",
            visual_subject="rubber feed roller and the leading banknote",
            action="one note slides ahead while the second is pushed back",
            emphasis="한 장씩",
            continuity_ids=("NOTE_HERO", "ATM_MAIN"),
        ),
        Step(
            statement="분리된 지폐는 벨트에 물려 센서 구간을 지나며 무늬와 크기가 확인된다.",
            spoken=(
                "떨어져 나온 한 장은 벨트에 물려 안쪽으로 들어갑니다. "
                "이동하는 동안 센서 앞을 지나가는데, 여기서 무늬와 크기를 읽어 "
                "진짜 지폐가 맞는지 확인합니다."
            ),
            sfx_cue="sensor_scan",
            visual_payoff="지폐가 벨트에 물려 센서 창을 통과한다",
            caption="센서가 읽는다",
            key_object="a banknote passing an optical sensor window",
            mechanism="belts carry the note past a sensor that reads pattern and size",
            visible_change="note entering the channel → note fully swept past the sensor",
            camera_path="tracking shot following the note through the channel",
            visual_subject="a single banknote on the transport belt",
            action="the note travels past the sensor window",
            continuity_ids=("NOTE_HERO", "ATM_MAIN"),
        ),
        Step(
            statement="두께 측정으로 두 장이 겹쳐 들어온 경우를 걸러낸다.",
            spoken=(
                "같은 구간에서 두께도 함께 잽니다. 한 장보다 두꺼우면 "
                "두 장이 겹쳐 들어왔다는 뜻이라, 금액이 어긋나기 전에 여기서 잡아냅니다."
            ),
            sfx_cue="sensor_scan",
            visual_payoff="두께 감지 롤러가 지폐 한 장 두께만큼만 밀린다",
            caption="두께로 겹침을 잡는다",
            key_object="a thickness-sensing roller pressed by the passing note",
            mechanism="a sprung roller measures how far the note pushes it",
            visible_change="roller at rest → roller lifted by exactly one note",
            camera_path="macro push-in on the sensing roller",
            visual_subject="thickness-sensing roller and the note beneath it",
            action="the roller lifts as the note passes",
            continuity_ids=("NOTE_HERO", "ATM_MAIN"),
        ),
        Step(
            statement="기준에 맞지 않는 지폐는 갈림길에서 별도 통로로 빠진다.",
            spoken=(
                "그럼 문제가 있는 지폐는 어떻게 될까요? 갈림길의 판이 젖혀지면서 "
                "그 한 장만 옆 통로로 빠져나갑니다. 나머지는 가던 길을 그대로 갑니다."
            ),
            sfx_cue="reject_click",
            visual_payoff="갈림길 판이 젖혀지고 한 장만 옆으로 빠진다",
            caption="한 장만 빠진다",
            key_object="a hinged diverter gate in the note path",
            mechanism="a gate swings to push one note onto a reject channel",
            visible_change="gate closed, note heading straight → gate open, note diverted",
            camera_path="tracking shot following the diverted note",
            visual_subject="diverter gate and the rejected note",
            action="the gate swings and one note leaves the main path",
            continuity_ids=("NOTE_HERO", "ATM_MAIN"),
        ),
        Step(
            statement="확인을 마친 지폐는 금액별 카세트에 순서대로 쌓인다.",
            spoken=(
                "확인을 마친 지폐만 금액별 카세트에 차곡차곡 쌓입니다. "
                "세는 일과 확인하는 일이 같은 길 위에서 동시에 끝나는 셈이죠."
            ),
            sfx_cue="stack_clunk",
            visual_payoff="지폐가 카세트 안에 한 장씩 눌려 쌓인다",
            caption="카세트에 쌓인다",
            key_object="banknotes stacking inside a denomination cassette",
            mechanism="accepted notes are pressed flat into their cassette in order",
            visible_change="empty cassette slot → a growing stack of notes",
            camera_path="pull back from the cassette as notes accumulate",
            visual_subject="a denomination cassette filling with notes",
            action="notes settle one by one into the stack",
            continuity_ids=("NOTE_HERO", "ATM_MAIN"),
        ),
    ),
    surprise=Step(
        statement="한 장이라도 확인에 실패하면 그 지폐만 따로 빠지고 나머지는 그대로 진행된다.",
        spoken="한 장이 빠져도 뒤따르던 지폐는 멈추지 않는데요.",
        emphasis="멈추지 않는데요",
        visual_payoff="한 장이 옆으로 빠지는 동안 뒤따르던 지폐들은 멈추지 않고 계속 간다",
        caption="한 장만 빠진다",
        key_object="one rejected note among a moving line of notes",
        mechanism="the reject path removes a single note without stopping the queue",
        visible_change="line of notes moving together → one note peeled aside, the rest continuing",
        camera_path="tracking shot holding on the queue as one note leaves the frame sideways",
        visual_subject="a line of banknotes with one being diverted",
        action="one note exits sideways while the others keep moving",
        continuity_ids=("NOTE_HERO",),
    ),
    closing=Step(
        statement="다음에 ATM 앞에 서면, 그 짧은 소리 동안 이 길이 지나간다고 생각해 보세요.",
        spoken="우리가 몇 초 기다리는 동안, 안에서는 이 길이 지나갑니다.",
        visual_payoff="카메라가 이송로에서 빠져나와 다시 ATM 외관 앞에 선다",
        caption="다음에 ATM 앞에서",
        key_object="the ATM seen from outside again",
        mechanism="the camera retreats from the interior back to the machine front",
        visible_change="interior transport path → the closed ATM front panel again",
        camera_path="reverse of the opening move, pulling out through the deposit slot",
        visual_subject="the ATM front panel in its room",
        action="the cutaway closes back into the intact machine",
        continuity_ids=("ATM_MAIN",),
        visualizable=True,
    ),
    world_machine_id="ATM_DEPOSIT_001",
    world_visual_style="documentary CGI cutaway, real metal and plastic surfaces",
    world_environment="a modern Korean indoor ATM booth, cool even lighting",
    continuity=(
        (
            "ATM_MAIN",
            "matte grey freestanding deposit ATM, rounded top edge, one amber "
            "status light beside the deposit slot, no readable text or branding",
        ),
        (
            "NOTE_HERO",
            "a single generic banknote, muted blue-green paper, worn edges, "
            "abstract guilloche pattern and no readable numbers or text",
        ),
    ),
)


def _generic_step(index: int, subject: str) -> Step:
    """Fallback shot for a topic with no hand-written scenario.

    Deliberately mechanical rather than abstract: it names belts, rails and
    gates so the generated narration still satisfies the content contract.
    """
    table = (
        (
            "안쪽에서는 벨트가 돌아가며 들어온 것을 한 줄로 세운다.",
            "들어온 것들은 먼저 한 줄로 정리됩니다.",
            "여러 개가 뒤섞여 있다가 벨트 위에서 한 줄로 정리된다",
            "한 줄로 정렬된다",
            "moving belt carrying items into single file",
            "a belt aligns the incoming items into one line",
            "scattered items → a single ordered line on the belt",
            "tracking shot travelling alongside the belt",
        ),
        (
            "좁아지는 레일이 앞뒤 간격을 일정하게 벌려 놓는다.",
            "레일이 좁아지면서 앞뒤 간격이 벌어지는데요.",
            "레일이 좁아지면서 앞뒤 간격이 고르게 벌어진다",
            "간격이 벌어진다",
            "narrowing rail section",
            "the rail narrows and spaces the items evenly",
            "items packed together → evenly spaced along the rail",
            "low tracking shot following the narrowing rail",
        ),
        (
            "센서 앞을 지나는 동안 크기와 모양이 하나씩 읽힌다.",
            "그 상태로 센서 앞을 지나갑니다. 여기서 크기와 모양을 읽습니다.",
            "물체가 센서 구멍을 지나며 위아래에서 훑린다",
            "센서가 읽는다",
            "sensor window over the rail",
            "a sensor reads each item as it passes",
            "item approaching the sensor → item fully swept past it",
            "macro push-in on the sensor window",
        ),
        (
            "기준에 맞지 않는 것은 갈림길에서 옆 통로로 빠진다.",
            "그럼 맞지 않는 건 어떻게 될까요? 갈림길에서 옆으로 빠집니다.",
            "갈림길에서 판이 젖혀지고 하나가 옆 통로로 빠진다",
            "옆길로 빠진다",
            "hinged diverter gate",
            "a gate swings and pushes one item onto a side channel",
            "gate closed, item heading straight → gate open, item diverted",
            "tracking shot following the diverted item",
        ),
        (
            "남은 것들은 마지막 칸에 순서대로 눌려 차곡차곡 쌓인다.",
            "남은 것들은 마지막 칸에 차곡차곡 쌓입니다.",
            "물체가 마지막 칸에 들어가 앞선 것들 위에 쌓인다",
            "마지막 칸에 쌓인다",
            "the final collection bin",
            "each accepted item is pressed onto the stack",
            "item entering the bin → item settled onto the pile",
            "pull back from the bin mouth to reveal the stack",
        ),
        (
            "위쪽 통로에서는 같은 흐름이 반대 방향으로 지나간다.",
            "위층에는 같은 흐름이 반대로 지나가는 통로가 있습니다.",
            "위층 통로에서 같은 흐름이 반대 방향으로 흘러간다",
            "위층은 반대 방향",
            "the upper channel running the other way",
            "a second channel carries items back in the opposite direction",
            "empty upper channel → items flowing the other way above",
            "tilt up from the lower channel to the upper one",
        ),
        (
            "모서리마다 놓인 작은 바퀴가 방향을 바꿔 준다.",
            "모서리에서는 작은 바퀴가 방향을 꺾어 줍니다.",
            "모서리의 작은 바퀴가 돌며 물체의 방향을 꺾는다",
            "모서리에서 방향이 꺾인다",
            "corner guide wheels",
            "guide wheels turn each item around the corner",
            "item approaching the corner → item turned onto the new heading",
            "orbit around the corner as the item turns",
        ),
        (
            "속도가 빨라지는 곳에서는 앞뒤 간격이 더 벌어진다.",
            "속도가 붙는 곳에서는 간격이 더 벌어지죠.",
            "속도가 붙으면서 앞뒤 간격이 눈에 띄게 벌어진다",
            "속도가 붙는다",
            "the acceleration section of the rail",
            "a faster belt stretches the gap between items",
            "tightly packed items → visibly wider gaps between them",
            "tracking shot pacing the accelerating items",
        ),
        (
            "이 흐름은 앞이 비는 순간에도 멈추지 않고 계속 이어진다.",
            "이 흐름은 앞이 비어도 멈추지 않습니다.",
            "전체 경로가 한 화면에 보이고 물체들이 줄지어 흐른다",
            "흐름은 계속된다",
            "the whole path seen end to end",
            "the stages run continuously one after another",
            "one item in frame → a steady line flowing along the path",
            "wide pull-back revealing the whole path",
        ),
    )
    statement, spoken, payoff, caption, key_object, mechanism, change, camera = table[
        index % len(table)
    ]
    return Step(
        statement=statement,
        spoken=spoken,
        visual_payoff=payoff,
        caption=caption,
        key_object=key_object,
        mechanism=mechanism,
        visible_change=change,
        camera_path=camera,
        visual_subject=f"{subject} — {key_object}",
        action=mechanism,
        continuity_ids=("SUBJECT_MAIN",),
    )


def generic_scenario(topic: str, subject: str) -> Scenario:
    steps = tuple(_generic_step(index, subject) for index in range(9))
    return Scenario(
        match=(),
        resolved_question=f"{topic.rstrip('?')}? (모의 provider가 임의로 좁힌 질문)",
        scope="모의 시나리오. 실제 조사 범위가 아닙니다.",
        excluded=("실제 제조사 설계", "검증되지 않은 세부 수치"),
        summary=(
            f"'{topic}' 주제를 모의 데이터로 채운 결과입니다. 실제 취재 결과가 아닙니다. "
            "들어온 것을 한 줄로 세우고, 간격을 벌리고, 센서로 읽고, 걸러내고, "
            "마지막 칸에 쌓는 순서로 이어집니다."
        ),
        hook=f"{subject} 안에서 무슨 일이 생길까요?",
        problem=Step(
            statement="겉에서 보아서는 안에서 무엇이 일어나는지 알 수 없다.",
            spoken=(
                "뻔한 답은 열어 보는 겁니다. 그런데 이건 모의 데이터라서, "
                "실제로 무엇이 들어 있는지는 여기서 알 수 없습니다."
            ),
            sfx_cue="none",
            visual_payoff="닫힌 겉면만 보인다",
            caption="겉만 보인다",
            key_object=f"the closed outer surface of {subject}",
            mechanism="the casing stays shut and reveals nothing",
            visible_change="the closed surface → the same closed surface",
            camera_path="slow push-in on the closed surface",
            visual_subject=f"{subject} exterior",
            action="the surface stays shut",
            continuity_ids=("SUBJECT_MAIN",),
        ),
        reveal=Step(
            statement="겉면이 열리면 안쪽으로 이어진 통로가 드러난다.",
            spoken="겉에서는 아무것도 보이지 않습니다. 안쪽에는 통로가 이어져 있죠.",
            sfx_cue="mechanical_reveal",
            visual_payoff="겉면이 단면으로 열리고 안쪽 통로가 보인다",
            caption="안쪽이 열린다",
            key_object=f"{subject} outer casing opening into a cutaway",
            mechanism="the casing peels away into a sectional view",
            visible_change="closed outer surface → sectional cutaway of the interior",
            camera_path="push in on the surface, then the casing peels away",
            visual_subject=f"cutaway of {subject}",
            action="the outer surface dissolves into a clean sectional view",
            continuity_ids=("SUBJECT_MAIN",),
        ),
        steps=steps,
        surprise=Step(
            statement="하나가 걸러지는 동안에도 뒤따르는 것들은 멈추지 않는다.",
            spoken="하나가 빠져도 뒤따르던 것들은 그대로 갑니다.",
            visual_payoff="하나가 옆으로 빠지는 동안 뒤따르던 것들은 계속 이동한다",
            caption="흐름은 멈추지 않는다",
            key_object="one rejected item among a moving line",
            mechanism="the reject path removes one item without stopping the queue",
            visible_change="line moving together → one item aside, the rest continuing",
            camera_path="tracking shot holding on the queue as one item leaves sideways",
            visual_subject=f"{subject} — a moving line with one item diverted",
            action="one item exits sideways while the others keep moving",
            continuity_ids=("SUBJECT_MAIN",),
        ),
        closing=Step(
            statement="다음에 이 앞에 서면, 안에서 이 길이 지나가고 있다고 생각해 보세요.",
            spoken="우리가 잠깐 기다리는 동안, 안에서는 이 길이 지나갑니다.",
            visual_payoff="카메라가 안쪽에서 빠져나와 다시 겉면 앞에 선다",
            caption="다음에 이 앞에서",
            key_object=f"{subject} seen from outside again",
            mechanism="the camera retreats from the interior to the exterior",
            visible_change="interior path → the closed outer surface again",
            camera_path="reverse of the opening move, pulling back out",
            visual_subject=f"{subject} exterior",
            action="the cutaway closes back into the intact object",
            continuity_ids=("SUBJECT_MAIN",),
        ),
        world_machine_id="SUBJECT_001",
        world_visual_style="documentary CGI cutaway, real materials",
        world_environment="a neutral indoor setting, cool even lighting",
        continuity=(
            (
                "SUBJECT_MAIN",
                f"the {subject} in this video: matte grey housing, rounded corners, "
                "one small amber status light, no readable text or branding",
            ),
        ),
    )


SCENARIOS: tuple[Scenario, ...] = (ATM,)


def scenario_for(topic: str, subject: str) -> Scenario:
    for scenario in SCENARIOS:
        if any(token in topic for token in scenario.match):
            return scenario
    return generic_scenario(topic, subject)
