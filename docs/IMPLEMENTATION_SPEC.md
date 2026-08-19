# Invisible Systems Shorts Factory
## Codex / Claude Code 구현용 상세 설계 보고서

> **문서 목적:** AI를 이용해 “평소에는 볼 수 없는 시스템·사물 내부·행동 뒤의 과정”을 시각화하는 YouTube Shorts 제작 파이프라인의 구현 기준서  
> **대상 개발 도구:** OpenAI Codex / Claude Code  
> **권장 구현 언어:** Python 3.12  
> **문서 상태:** MVP Implementation Spec v0.5  
> **기준일:** 2026-08-18

> **v0.2 개정 (Mock/Production 분리, Content Quality Contract):** 부록 C 참조.  
> **v0.3 개정 (Spoken Narration & Scene-Speech Sync):** 부록 D 참조.  
> **v0.4 개정 (SFX와 자막 강조):** 부록 E 참조.  
> **v0.5 개정 (Veo 3 video provider):** 부록 F 참조.  
> 본문과 부록이 충돌하면 **부록이 우선**한다.

---

# 0. Executive Summary

이 프로젝트의 목적은 단순한 **AI 영상 생성기**를 만드는 것이 아니다.

최종 목표는 다음과 같은 하나의 주제를:

```text
"ATM은 돈을 어떻게 세는 걸까?"
```

가능한 한 적은 수작업으로 아래의 완성 영상으로 변환하는 것이다.

```text
Topic
  ↓
Research / Fact Verification
  ↓
Short-form Script
  ↓
Scene Plan
  ↓
Visual Prompt
  ↓
Video / Image Assets
  ↓
TTS
  ↓
Subtitle
  ↓
FFmpeg Composition
  ↓
final.mp4
```

초기 MVP의 성공 조건은 **완전자동화가 아니다.**

> **실제 업로드할 수 있는 Shorts 10개를 안정적으로 생산할 수 있는가?**

이를 기준으로 개발한다.

## 핵심 원칙

1. **Agent Swarm을 만들지 않는다.**
2. 런타임은 **deterministic pipeline**으로 만든다.
3. LLM은 Research / Writer / Director 등 필요한 판단 단계에만 사용한다.
4. 모든 단계의 입력·출력은 명시적 **Pydantic schema**를 따른다.
5. 영상·이미지·LLM·TTS 공급자는 모두 **Provider Adapter**로 분리한다.
6. 영상 생성 실패를 예외 상황이 아니라 **정상적인 운영 상태**로 가정한다.
7. AI 영상 생성 비용을 시스템 수준에서 제한한다.
8. 실제 구조와 설명용 시각화를 구분한다.
9. 자동 업로드·성과 자동화는 MVP에서 제외한다.
10. 코드의 복잡성보다 **실제 콘텐츠 품질과 채널 성과**가 최종 KPI다.

---

# 1. 제품 정의

## 1.1 한 문장 정의

> **우리가 일상적으로 사용하지만 직접 볼 수 없는 내부 과정과 시스템을 AI 시각화로 설명하는 Shorts 제작 엔진**

## 1.2 핵심 가치

이 프로젝트의 경쟁력은 “AI를 쓴다”가 아니다.

```text
좋은 질문
+
명확한 설명
+
실제로 찍기 어려운 카메라
```

즉:

> **카메라가 들어갈 수 없는 곳에 카메라를 넣는다.**

라는 영상 문법을 일관되게 유지한다.

---

# 2. 콘텐츠 구조: A/B/C 모두 유지

세 컨셉을 서로 다른 파이프라인으로 만들지 않는다.

하나의 상위 엔진 아래 `content_type`으로 구분한다.

```text
Invisible World
│
├── A. Hidden System
│   └── 도시와 사회의 보이지 않는 시스템
│
├── B. Inside Object
│   └── 물건 안에서 실제로 벌어지는 일
│
└── C. Behind Action
    └── 우리가 어떤 행동을 한 뒤 시스템에서 벌어지는 일
```

---

## 2.1 A — Hidden System

### 정의

도시·사회·인프라의 보이지 않는 물리적 시스템을 시각화한다.

### 소재 예시

- 서울 지하철은 운행이 끝나면 어디로 갈까?
- 아파트에서 버린 쓰레기는 그날 밤 어디로 갈까?
- 비가 100mm 오면 서울 지하에서는 무슨 일이 벌어질까?
- 공항에서 캐리어는 어떻게 내 비행기를 찾아갈까?
- 수도꼭지를 틀면 물은 어디서 오는가?
- 하수는 어디로 가는가?
- 택배는 밤새 어디를 이동하는가?

### Visual Grammar

```text
Normal World
  ↓
Reveal Hidden Layer
  ↓
Cross-section / Cutaway
  ↓
Flow
  ↓
Large Infrastructure
  ↓
Destination / Result
```

---

## 2.2 B — Inside Object

### 정의

익숙한 기계나 사물의 내부 구조 및 작동 과정을 보여준다.

### 소재 예시

- ATM은 돈을 어떻게 세는 걸까?
- 자판기에 넣은 동전은 어디로 갈까?
- 에스컬레이터 계단 아래에는 무엇이 있을까?
- 엘리베이터 문은 어떻게 움직일까?
- 자동문은 사람이 오는 것을 어떻게 알까?
- 세차장 바닥 아래에는 무엇이 있을까?
- 복사기는 종이를 어떻게 복사할까?

### Visual Grammar

```text
Familiar Object
  ↓
Camera Approach
  ↓
Cutaway
  ↓
Internal Mechanism
  ↓
Macro Detail
  ↓
Cause → Effect
```

---

## 2.3 C — Behind Action

### 정의

사용자가 어떤 버튼을 누르거나 행동했을 때 뒤에서 발생하는 디지털·사회적·물류적 과정을 설명한다.

### 소재 예시

- 카드를 찍는 1초 동안 무슨 일이 벌어질까?
- 유튜브 영상을 누르면 영상은 어디서 오는가?
- 배달 주문 버튼을 누르면 어떤 일이 시작될까?
- 인터넷 검색을 하면 데이터는 어디로 이동하는가?
- 119에 전화하면 어떤 시스템이 작동하는가?
- 온라인 결제 버튼을 누르면 어떤 기관을 거치는가?

### Visual Grammar

```text
Human Action
  ↓
Trigger
  ↓
Signal / Request
  ↓
Multiple Systems
  ↓
Decision / Processing
  ↓
Response
```

### 중요 주의사항

C형 콘텐츠는 물리적으로 관찰되지 않는 추상적 과정이 많다.

예를 들어 다음과 같은 영상은 설명용 시각화일 뿐 실제 모습이 아니다.

```text
카드 → 빛나는 데이터 → 은행 → 돈
```

따라서 시스템에서 반드시:

```yaml
reality_type: conceptual
```

로 표시한다.

---

# 3. 가장 중요한 Architecture Decision

## 3.1 Development Agent와 Runtime Agent를 구분한다

Codex 또는 Claude Code를 이용해 개발한다고 해서 완성 프로그램 자체를 자율 다중 에이전트 구조로 만들 필요는 없다.

### 권장하지 않는 구조

```text
Research Agent
  ↓
Fact Agent
  ↓
Hook Agent
  ↓
Script Agent
  ↓
Scene Agent
  ↓
Prompt Agent
  ↓
Video Agent
  ↓
QA Agent
  ↓
Editor Agent
```

이 방식은 다음 문제를 만들 가능성이 높다.

- context 증가
- LLM 호출 증가
- 비용 증가
- 역할 중복
- Agent 사이 데이터 불일치
- 디버깅 어려움
- 결과 재현성 저하
- 프롬프트 수정 영향 범위 증가
- 실패 원인 추적 어려움

## 3.2 권장 구조

```text
Pipeline Orchestrator

1. Research
2. Write
3. Direct
4. Generate Assets
5. Narrate
6. Validate
7. Compose
```

각 단계는 독립적인 **서비스 또는 함수**다.

필요한 단계에서만 LLM을 호출한다.

---

# 4. MVP Scope

## 4.1 반드시 구현

```text
Topic
  ↓
Research
  ↓
Script
  ↓
Scene Plan
  ↓
Asset Generation
  ↓
TTS
  ↓
Subtitles
  ↓
Video Composition
  ↓
final.mp4
```

기능 목록:

- 단일 주제 입력
- A/B/C 콘텐츠 타입 지정 또는 분류
- 조사 결과 저장
- 주장별 출처 저장
- 불확실한 주장 분리
- 45~70초 스크립트
- 8~14개 Scene
- Scene별 영상 Prompt 생성
- Video 또는 Image asset 생성
- TTS 생성
- SRT 생성
- FFmpeg 기반 최종 편집
- 실패 Scene retry
- retry 제한
- fallback
- 비용 상한
- 중간 저장
- resume
- 모든 결과를 프로젝트 디렉터리에 저장

---

## 4.2 MVP에서 제외

초기에는 아래 기능을 만들지 않는다.

- YouTube 자동 업로드
- TikTok 자동 업로드
- Instagram 자동 업로드
- 조회수 자동 수집
- 댓글 분석
- 자동 주제 발견
- 성과 기반 자동 주제 선정
- 자동 썸네일
- Web UI
- 사용자 로그인
- SaaS 대시보드
- 결제
- Vector DB
- Redis
- Celery
- Kubernetes
- Microservice architecture
- 복잡한 multi-agent framework
- LangGraph
- CrewAI
- AutoGen

MVP 목표는:

> **한 컴퓨터에서 CLI로 영상 한 편을 안정적으로 생산하는 것**

이다.

---

# 5. MVP 성공 기준

## 5.1 기술 성공 기준

다음 명령 하나로:

```bash
python -m shorts_factory create \
  --topic "ATM은 돈을 어떻게 세는 걸까?" \
  --type inside_object
```

다음과 같은 프로젝트가 생성된다.

```text
projects/atm-money-counter/
├── project.json
├── research.json
├── research.md
├── script.json
├── script.txt
├── scenes.json
├── prompts/
├── assets/
│   ├── scene_001/
│   ├── scene_002/
│   └── ...
├── audio/
│   └── narration.wav
├── subtitles/
│   └── narration.srt
├── logs/
├── manifest.json
└── output/
    └── final.mp4
```

## 5.2 실제 성공 기준

MVP 완료는 “코드가 실행됨”이 아니다.

최소:

- 실제 Shorts로 업로드할 의향이 있는 영상 **10개**
- 심각한 사실 오류 **0개**
- Scene 누락 **0개**
- 중간 실패 후 resume 가능
- 이미 성공한 비싼 API 작업을 불필요하게 재실행하지 않음
- 편당 비용 확인 가능
- Scene별 비용 확인 가능
- 어느 Scene이 실패했는지 확인 가능

---

# 6. 권장 기술 스택

## Core

```text
Python 3.12
Pydantic 2.x
Typer
httpx
tenacity
python-dotenv
structlog
PyYAML
```

## Media

```text
FFmpeg
ffprobe
Pillow
```

필요하면:

```text
pydub
```

최종 합성은 Python 영상 프레임워크에 과도하게 의존하기보다 **FFmpeg를 직접 호출하는 얇은 wrapper**를 권장한다.

## Development

```text
pytest
pytest-asyncio
ruff
mypy 또는 pyright
pre-commit
```

---

# 7. Repository 구조

```text
invisible-shorts/
│
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── docs/
│   ├── IMPLEMENTATION_SPEC.md
│   └── adr/
│
├── config/
│   ├── settings.yaml
│   ├── content_types.yaml
│   ├── visual_styles.yaml
│   └── budgets.yaml
│
├── prompts/
│   ├── research/
│   │   ├── system.md
│   │   └── user.md
│   ├── writer/
│   │   ├── system.md
│   │   └── user.md
│   ├── director/
│   │   ├── system.md
│   │   └── user.md
│   └── qa/
│       ├── system.md
│       └── user.md
│
├── src/
│   └── shorts_factory/
│       ├── __init__.py
│       ├── cli.py
│       │
│       ├── domain/
│       │   ├── enums.py
│       │   ├── project.py
│       │   ├── research.py
│       │   ├── script.py
│       │   ├── scene.py
│       │   ├── asset.py
│       │   └── manifest.py
│       │
│       ├── pipeline/
│       │   ├── orchestrator.py
│       │   ├── state.py
│       │   └── checkpoint.py
│       │
│       ├── stages/
│       │   ├── research.py
│       │   ├── writing.py
│       │   ├── directing.py
│       │   ├── asset_generation.py
│       │   ├── narration.py
│       │   ├── subtitles.py
│       │   ├── validation.py
│       │   └── composition.py
│       │
│       ├── providers/
│       │   ├── base.py
│       │   ├── llm/
│       │   ├── search/
│       │   ├── image/
│       │   ├── video/
│       │   └── tts/
│       │
│       ├── prompts/
│       │   ├── loader.py
│       │   └── renderer.py
│       │
│       ├── media/
│       │   ├── ffmpeg.py
│       │   ├── ffprobe.py
│       │   ├── normalize.py
│       │   └── subtitles.py
│       │
│       ├── quality/
│       │   ├── fact_check.py
│       │   ├── scene_check.py
│       │   └── technical_check.py
│       │
│       ├── cost/
│       │   ├── tracker.py
│       │   └── budget.py
│       │
│       └── utils/
│           ├── files.py
│           ├── hashing.py
│           └── logging.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── projects/
│   └── .gitkeep
│
└── scripts/
    ├── doctor.py
    └── smoke_test.py
```

---

# 8. Domain Model 원칙

모든 LLM 결과를 자유 텍스트로 다음 단계에 넘기지 않는다.

항상:

```text
LLM output
  ↓
JSON
  ↓
Pydantic Validation
  ↓
Domain Object
```

과정을 거친다.

---

# 9. Enum 설계

```python
from enum import StrEnum


class ContentType(StrEnum):
    HIDDEN_SYSTEM = "hidden_system"
    INSIDE_OBJECT = "inside_object"
    BEHIND_ACTION = "behind_action"


class RealityType(StrEnum):
    OBSERVED = "observed"
    RECONSTRUCTED = "reconstructed"
    CONCEPTUAL = "conceptual"


class ScenePriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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
```

---

# 10. Project Schema

```python
from datetime import datetime
from pydantic import BaseModel, Field


class StageRecord(BaseModel):
    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Project(BaseModel):
    schema_version: str = "1.0"

    project_id: str
    slug: str
    topic: str
    content_type: ContentType

    created_at: datetime
    updated_at: datetime

    stages: dict[str, StageRecord] = Field(default_factory=dict)

    research_path: str | None = None
    script_path: str | None = None
    scenes_path: str | None = None
    manifest_path: str | None = None
    final_video_path: str | None = None

    estimated_cost_usd: float = 0
    actual_cost_usd: float = 0
```

`project.json`은 전체 프로젝트의 **canonical persistent state**다.

---

# 11. Research Schema

Research 단계의 핵심 단위는 문단이 아니라 **Claim**이다.

```python
class SourceRef(BaseModel):
    id: str
    title: str
    url: str
    publisher: str | None = None
    published_at: str | None = None
    accessed_at: str | None = None


class Claim(BaseModel):
    id: str
    statement: str
    confidence: ClaimConfidence
    source_ids: list[str]
    visualizable: bool = False
    notes: str | None = None


class ResearchResult(BaseModel):
    topic: str
    summary: str
    claims: list[Claim]
    sources: list[SourceRef]
    unresolved_questions: list[str] = []
    unsafe_or_uncertain_claims: list[str] = []
```

## 절대 규칙

`source_ids == []`인 factual claim은 최종 스크립트에서 사용하지 않는다.

예외:

- 명시적 의견
- 수사적 질문
- 단순 전환 문장

---

# 12. Research Pipeline

```text
Topic
 ↓
Search Queries
 ↓
Sources
 ↓
Claims
 ↓
Cross-check
 ↓
ResearchResult
```

## 검증 기준이 더 높은 분야

```text
medicine
health
finance
law
electricity
aviation
transport safety
public infrastructure
emergency services
```

향후:

```python
risk_level: Literal["normal", "sensitive", "high"]
```

을 추가할 수 있다.

---

# 13. Writer Stage

Hook Agent와 Script Agent를 따로 만들지 않는다.

Writer 한 단계에서:

```text
Title
Hook
Narration
Story Beats
Closing
```

을 만든다.

## Script Schema

```python
class ScriptBeat(BaseModel):
    id: str
    purpose: str
    text: str


class ScriptResult(BaseModel):
    title: str
    hook: str
    narration: str
    beats: list[ScriptBeat]
    target_duration_sec: float
    referenced_claim_ids: list[str]
    estimated_word_count: int
```

---

# 14. Script 구조

권장:

```text
45~70 seconds
```

초기 target:

```text
55~62 seconds
```

구조:

```text
0~3s
HOOK

3~10s
REVEAL

10~40s
PROCESS

40~52s
SURPRISE / IMPORTANT DETAIL

52~60s
CLOSING
```

## 피해야 할 Script 패턴

### 불필요한 인트로

```text
안녕하세요 여러분.
오늘은 ATM에 대해 알아보겠습니다.
```

금지.

### 근거 없는 과장

```text
여러분은 평생 속고 있었습니다.
충격적인 진실입니다.
```

금지.

---

# 15. Director Stage

이 프로젝트의 가장 중요한 LLM 단계다.

```text
Narration
  ↓
Visual Story
  ↓
Scenes
```

Director는 특정 영상 모델용 prompt 문자열을 직접 저장하지 않는다.

**영상의 의미 구조를 Scene으로 만든다.**

---

# 16. Scene Schema

```python
class ContinuitySpec(BaseModel):
    continuity_id: str | None = None
    fixed_description: str | None = None


class Scene(BaseModel):
    id: str
    order: int

    narration: str
    duration_sec: float
    purpose: str

    visual_subject: str
    environment: str
    action: str

    camera: str
    framing: str | None = None
    lighting: str | None = None

    reality_type: RealityType
    priority: ScenePriority
    asset_type: AssetType

    continuity: list[ContinuitySpec] = []
    claim_ids: list[str] = []

    transition_in: str | None = None
    transition_out: str | None = None

    negative_constraints: list[str] = []
```

---

# 17. Reality Type

모든 Scene은 다음 셋 중 하나다.

## OBSERVED

실제로 존재하며 일반적으로 관찰 가능한 모습.

예:

```text
공항 수하물 컨베이어
```

## RECONSTRUCTED

실제 자료를 기반으로 내부 모습을 재현.

예:

```text
도시 지하 하수관 단면
```

## CONCEPTUAL

눈으로 볼 수 없는 과정을 설명하기 위한 시각화.

예:

```text
인터넷 요청이 여러 시스템을 거쳐 이동하는 과정
```

중요:

```text
CONCEPTUAL ≠ 실제 내부 모습
```

---

# 18. Scene 수 제한

MVP:

```python
MIN_SCENES = 8
MAX_SCENES = 14
```

권장:

```text
10~12 scenes
```

너무 많은 Scene은:

- API 비용 증가
- 생성 실패 증가
- continuity 저하
- 편집 복잡도 증가
- 영상 산만함

을 유발한다.

---

# 19. Visual Grammar Config

`config/content_types.yaml`

```yaml
hidden_system:
  reveal_pattern:
    - normal_world
    - hidden_layer
    - flow
    - infrastructure
    - destination

  preferred_camera:
    - drone_push
    - underground_dive
    - tracking
    - cutaway

  preferred_visuals:
    - cross_section
    - cutaway
    - infrastructure
    - flow


inside_object:
  reveal_pattern:
    - familiar_object
    - approach
    - cutaway
    - mechanism
    - macro_detail

  preferred_camera:
    - macro
    - dolly_in
    - orbit
    - cutaway_transition


behind_action:
  reveal_pattern:
    - human_action
    - trigger
    - network
    - processing
    - response

  preferred_visuals:
    - conceptual_flow
    - system_nodes
    - server_infrastructure
    - signal_visualization
```

A/B/C 차이는 별도 Pipeline이 아니라 이와 같은 **Visual Grammar**에서 처리한다.

---

# 20. Scene과 Prompt 분리

나쁜 구조:

```python
scene.prompt = "cinematic hyper realistic..."
```

좋은 구조:

```text
Scene
  ↓
Provider-specific Prompt Adapter
  ↓
Provider Prompt
```

예:

```python
class VideoPromptAdapter(Protocol):
    def build_prompt(self, scene: Scene) -> str: ...
```

이렇게 해야 Veo/Kling/기타 모델을 바꾸더라도 Director를 다시 설계할 필요가 없다.

---

# 21. Provider Interface

외부 API는 Domain layer에서 직접 호출하지 않는다.

```python
from typing import Protocol


class LLMProvider(Protocol):
    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type,
    ): ...


class VideoProvider(Protocol):
    async def submit(
        self,
        *,
        prompt: str,
        duration_sec: float,
        aspect_ratio: str,
    ) -> str: ...

    async def status(self, job_id: str): ...

    async def download(self, job_id: str, destination: str): ...


class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        destination: str,
    ) -> None: ...
```

---

# 22. Provider 선택 방식

```yaml
providers:
  llm: openai
  search: default_search
  image: provider_a
  video: provider_b
  tts: provider_c
```

MVP에서는 각 종류당 **실제 Provider 하나만 구현**한다.

interface는 처음부터 분리하되, 실제 Provider를 여러 개 동시에 구현하지 않는다.

---

# 23. 영상 생성 API는 비동기로 가정

```text
SUBMIT
 ↓
JOB ID
 ↓
POLL
 ↓
PROCESSING
 ↓
COMPLETED
 ↓
DOWNLOAD
```

따라서 asset 상태를 기록한다.

```python
class AssetRecord(BaseModel):
    scene_id: str
    provider: str
    provider_job_id: str | None = None
    status: str
    attempt: int
    prompt_hash: str
    local_path: str | None = None
    cost_usd: float | None = None
    error: str | None = None
```

---

# 24. Idempotency

같은 Scene을 다시 실행했다고 무조건 API를 재호출하면 안 된다.

다음 정보로 hash를 만든다.

```text
provider
+ model
+ prompt
+ duration
+ aspect_ratio
```

성공한 동일 hash asset이 있다면 재사용한다.

---

# 25. Resume

상태:

```text
Scene 1 PASS
Scene 2 PASS
Scene 3 FAIL
Scene 4 PENDING
```

프로그램이 종료된 뒤 다시 실행하면:

```text
Scene 1 SKIP
Scene 2 SKIP
Scene 3 RETRY
Scene 4 RUN
```

해야 한다.

CLI:

```bash
python -m shorts_factory resume projects/my-project
```

---

# 26. Retry

## Network/API Retry

대상:

```text
429
5xx
timeout
connection reset
```

`tenacity` exponential backoff를 사용한다.

## Content Retry

영상 자체가 사용할 수 없는 경우:

```python
MAX_RENDER_ATTEMPTS = 3
```

3회를 넘겨 자동 재생성하지 않는다.

---

# 27. Fallback

모든 Scene을 Video AI로 만들 필요가 없다.

```text
Video generation
    │
    ├── PASS → video
    │
    └── FAIL x3
           ↓
      image generation
           ↓
      camera motion
           ↓
      usable scene
```

Fallback:

```text
AI Image
+
Ken Burns / Pan / Zoom
+
SFX
```

비용 절감에도 유용하다.

---

# 28. Scene Priority

각 Scene:

```text
HIGH
MEDIUM
LOW
```

## HIGH

- Hook
- 핵심 Reveal
- Wow Scene
- 가장 중요한 시각적 장면

최고 품질 영상 생성 우선.

## MEDIUM

과정 설명.

일반 Video.

## LOW

전환·연결.

Image + Motion 허용.

---

# 29. Budget Guard

유료 API를 호출하기 전에 비용을 확인한다.

`config/budgets.yaml`

```yaml
project:
  max_total_usd: 12.00

video:
  max_scene_attempts: 3
  max_high_priority_scenes: 4

llm:
  max_calls: 15
```

숫자는 예시다.

실제 가격은 사용하는 Provider의 최신 공식 가격을 확인하여 config에서 수정한다.

**하드코딩하지 않는다.**

---

# 30. Cost Tracker

각 API 요청:

```json
{
  "provider": "video_provider",
  "operation": "generate_video",
  "scene_id": "S04",
  "estimated_cost_usd": 0.8,
  "actual_cost_usd": 0.8
}
```

최종:

```text
PROJECT COST
LLM        $0.xx
SEARCH     $0.xx
IMAGE      $x.xx
VIDEO      $x.xx
TTS        $0.xx
----------------
TOTAL      $x.xx
```

---

# 31. Continuity

AI 영상은 다음과 같은 불일치를 쉽게 만들 수 있다.

```text
Scene 1: 빨간 캐리어
Scene 2: 검은 캐리어
Scene 3: 전혀 다른 캐리어
```

중요 object에 identity를 부여한다.

```yaml
continuity:
  - continuity_id: BAG_MAIN
    fixed_description: >
      red hard-shell carry-on suitcase,
      rectangular shape,
      black telescopic handle,
      small white baggage tag
```

관련 Scene Prompt에 동일 description을 삽입한다.

---

# 32. 장소 Continuity

필요할 경우:

```yaml
continuity_id: AIRPORT_SORTING_CENTER
```

같은 방식도 사용한다.

단, continuity 정보를 모든 Scene에 과도하게 넣지 않는다.

---

# 33. Negative Constraints

Scene마다 별도 저장한다.

```yaml
negative_constraints:
  - visible text
  - logos
  - impossible conveyor geometry
  - duplicated luggage
  - human hands
```

Provider Adapter가 서비스 특성에 맞게 처리한다.

---

# 34. Fact Traceability

Research → Script → Scene 관계를 추적한다.

```text
Claim C03
 ↓
Script Beat B02
 ↓
Scene S04
```

Scene:

```yaml
scene_id: S04
claim_ids:
  - C03
  - C04
```

사실 오류가 발견되었을 때 영향을 받는 Scene을 추적할 수 있다.

---

# 35. Fact Lock

Video API 호출 전에:

```text
Research complete
      ↓
Every factual sentence has Claim
      ↓
Every Claim has Source
      ↓
Unsupported low-confidence claim removed
      ↓
SCRIPT_LOCKED
```

`SCRIPT_LOCKED` 전에는 유료 영상 생성 금지.

---

# 36. Quality Gate

거대한 QA Agent 하나를 만들지 않는다.

## 36.1 Structural QA

코드로 검사:

```text
Scene count 8~14
Duration 45~70
Narration exists
Every scene has reality_type
Factual scenes have claim_ids
```

LLM 불필요.

## 36.2 Factual QA

Research와 Script 비교.

필요하면 LLM 사용:

```text
Is any factual sentence unsupported
by the provided verified claims?
```

## 36.3 Technical Media QA

`ffprobe`:

```text
video exists
duration > 0
resolution valid
audio stream valid
frame rate valid
aspect ratio valid
```

---

# 37. Visual QA

MVP에서는 영상 내용을 완전 자동 평가하지 않는다.

이유:

- vision 평가도 비용 발생
- 미세 오류 판별이 완벽하지 않음
- QA가 생성 시스템보다 커질 위험

초기:

```text
Automated Technical QA
+
Human Final Review
```

Phase 2 이후 선택적으로:

```text
sample frames
 ↓
vision model
 ↓
scene-description consistency
```

추가.

---

# 38. Human Review

최종 Render 전:

```bash
shorts inspect PROJECT
```

출력:

```text
Project
Script
Claims
Scenes
Asset Status
Estimated Cost
Warnings
```

확인 후:

```bash
shorts render PROJECT
```

---

# 39. TTS

가능하면 전체 Narration을 한 번에 생성한다.

장점:

- voice consistency
- 억양 consistency
- API call 감소

이후 alignment를 이용해 subtitle 및 Scene timing을 맞춘다.

---

# 40. Subtitle

MVP:

```text
SRT
```

향후:

```text
ASS
```

지원 가능.

최종 Shorts에서는 Burn-in subtitle을 기본값으로 고려한다.

## 기본 규칙

- 모바일 우선
- 최대 2줄
- 영상 핵심 대상을 가리지 않음
- 지나치게 긴 한 문장 금지
- 과도한 kinetic typography는 MVP에서 제외

---

# 41. FFmpeg Composition

레이어:

```text
VIDEO
+
VOICE
+
BGM
+
SFX
+
SUBTITLE
```

Pipeline:

```text
normalize scenes
 ↓
concat
 ↓
voiceover
 ↓
bgm ducking
 ↓
subtitle
 ↓
encode
```

---

# 42. Output Spec

```text
Aspect Ratio: 9:16
Resolution: 1080x1920
Container: MP4
Video: H.264
Audio: AAC
```

encoding 상세값은 config로 관리한다.

---

# 43. Manifest

```json
{
  "resolution": [1080, 1920],
  "fps": 30,
  "scenes": [
    {
      "scene_id": "S01",
      "asset": "assets/S01/final.mp4",
      "start": 0.0,
      "duration": 4.2
    }
  ],
  "voice": "audio/narration.wav",
  "subtitle": "subtitles/narration.srt"
}
```

---

# 44. Pipeline State Machine

```text
CREATED
 ↓
RESEARCHED
 ↓
SCRIPTED
 ↓
FACT_LOCKED
 ↓
DIRECTED
 ↓
ASSETS_READY
 ↓
AUDIO_READY
 ↓
VALIDATED
 ↓
COMPOSED
 ↓
DONE
```

실패 시:

```text
ANY STATE
 ↓
FAILED
```

이전 완료 데이터는 유지한다.

---

# 45. CLI

MVP:

```bash
shorts create
shorts research
shorts write
shorts direct
shorts generate
shorts narrate
shorts inspect
shorts render
shorts resume
shorts status
shorts doctor
```

예:

```bash
shorts create \
  --topic "공항에서 캐리어는 어떻게 내 비행기를 찾아갈까?" \
  --type hidden_system
```

특정 단계까지만:

```bash
shorts create \
  --topic "ATM은 돈을 어떻게 세는 걸까?" \
  --until direct
```

이는 개발 중 영상 API 비용 없이 Research/Script/Scene을 반복 테스트하기 위해 중요하다.

---

# 46. Dry Run

반드시:

```bash
--dry-run
```

지원.

Dry Run에서는 유료 API를 호출하지 않는다.

대신:

- project 생성 계획
- prompt
- 예상 API call
- 예상 비용

만 출력한다.

---

# 47. Mock Provider

개발 초기에 구현:

```text
MockLLMProvider
MockSearchProvider
MockVideoProvider
MockTTSProvider
```

Mock 없이 유료 API부터 연결하지 않는다.

---

# 48. Prompt 관리

긴 프롬프트를 Python source에 넣지 않는다.

```text
prompts/
```

에서 관리한다.

각 결과에:

```yaml
prompt_version: director-v1
```

을 기록한다.

Prompt 파일 hash도 저장한다.

이를 통해 Prompt 변경 전후 결과 비교가 가능하다.

---

# 49. Logging

콘솔 + JSON logging.

예:

```text
INFO project_created project=airport-baggage
INFO research_completed claims=12 sources=7
INFO script_completed duration=58.4
INFO scene_generation_completed scenes=11
INFO render_submitted scene=S01 attempt=1
```

API key는 절대 로그에 남기지 않는다.

---

# 50. Error 설계

```python
class ShortsFactoryError(Exception):
    pass


class ProviderError(ShortsFactoryError):
    pass


class BudgetExceededError(ShortsFactoryError):
    pass


class PipelineValidationError(ShortsFactoryError):
    pass


class FactCheckError(ShortsFactoryError):
    pass


class MediaError(ShortsFactoryError):
    pass
```

---

# 51. Config와 Secret 분리

`.env`에는 secret만:

```bash
OPENAI_API_KEY=
SEARCH_API_KEY=
IMAGE_API_KEY=
VIDEO_API_KEY=
TTS_API_KEY=
```

일반 설정은:

```text
config/settings.yaml
```

에 둔다.

---

# 52. Security

`.gitignore` 예:

```gitignore
.env
projects/
output/
*.mp4
*.wav
*.mp3
```

테스트 fixture만 필요에 따라 예외 처리한다.

---

# 53. Asset Provenance

향후 외부 asset도 사용할 수 있으므로 출처 정보를 저장한다.

```python
class Provenance(BaseModel):
    source_type: str
    source_url: str | None = None
    license: str | None = None
    generated_by_ai: bool = False
```

예상 source:

```text
ai_generated
user_owned
public_domain
commercial_stock
seller_provided
```

라이선스가 확인되지 않은 외부 미디어는 자동 사용하지 않는다.

---

# 54. AI 생성 Metadata

```yaml
contains_ai_generated_visuals: true
```

를 project에 저장한다.

실제 플랫폼 업로드 시 필요한 합성 콘텐츠 표시 정책은 **업로드 기능을 구현하는 시점의 최신 YouTube 정책을 별도로 확인**한다.

---

# 55. Test Strategy

## Unit Tests

```text
schema validation
slug generation
budget calculation
prompt rendering
scene count validation
fact traceability
manifest generation
resume logic
```

## Integration Tests

Mock 기반:

```text
research → script → scene
video submit → poll → complete
failure → retry
failure x3 → fallback
```

## Media Tests

짧은 local fixture로:

```text
concat
audio mix
subtitle burn
1080x1920 output
```

테스트.

---

# 56. Live API Test 보호

기본 test suite는 실제 API 호출 금지.

```python
if os.getenv("ALLOW_LIVE_API_TESTS") != "1":
    block_live_api()
```

Live test:

```bash
pytest -m live
```

로만 실행.

---

# 57. CI

초기 CI:

```text
ruff
type check
pytest unit
pytest integration(mock)
```

Video API live 테스트는 기본 CI에서 실행하지 않는다.

---

# 58. AGENTS.md — Codex용 Project Instruction

Codex는 프로젝트 작업 지침에 `AGENTS.md`를 사용할 수 있으므로 핵심 개발 규칙을 여기에 둔다.

권장 예시:

```markdown
# AGENTS.md

## Project

This repository implements a CLI-first AI Shorts production pipeline.

The MVP converts a topic into a locally rendered 9:16 MP4.

## Architecture Rules

- Use Python 3.12.
- Keep the runtime deterministic.
- Do not introduce multi-agent frameworks.
- All LLM outputs must be validated by Pydantic.
- External APIs must be accessed through provider interfaces.
- Do not call paid APIs in normal tests.
- Do not implement upload automation during MVP.
- project.json is the canonical project state.
- Every expensive pipeline stage must be resumable.
- Video generation must respect the budget guard.
- Do not silently discard failed scenes.
- Do not expand the scope without an explicit requirement.

## Verification Commands

- `ruff check .`
- `pytest`
- `python -m shorts_factory doctor`

## Definition of Done

A task is not complete until:

1. relevant tests pass,
2. lint passes,
3. documentation is updated when behavior changes,
4. no secrets are committed.
```

---

# 59. CLAUDE.md — Claude Code용 Context

Claude Code의 `CLAUDE.md`는 짧게 유지한다.

```markdown
# CLAUDE.md

Read `AGENTS.md` before making implementation changes.

`AGENTS.md` is the canonical engineering policy for this repository.

Read the implementation specification before architecture-level changes:

`docs/IMPLEMENTATION_SPEC.md`

Important constraints:

- MVP is CLI-first.
- Do not add a web application.
- Do not add a multi-agent runtime.
- Do not add infrastructure not required by current acceptance criteria.
- Prefer small, testable modules.
- Run tests and lint after implementation changes.
```

중요한 규칙을 단순히 `CLAUDE.md` 지시만으로 보호하지 않는다.

반드시 지켜야 하는 제약은:

```text
tests
validation
CI
hooks
```

등 deterministic mechanism으로 강제한다.

---

# 60. Codex / Claude Code 작업 방식

처음부터:

```text
"전체 시스템을 다 구현해"
```

라고 시키지 않는다.

다음 단위로 진행한다.

```text
Architecture
 ↓
Schemas
 ↓
Project State
 ↓
Mock Pipeline
 ↓
One Real Provider
 ↓
Media Pipeline
 ↓
End-to-End
```

각 단계:

```text
IMPLEMENT
 ↓
TEST
 ↓
REVIEW
 ↓
COMMIT
```

---

# 61. 구현 Phase 0 — Bootstrap

목표:

```text
repository can install and test
```

구현:

- `pyproject.toml`
- src layout
- Typer CLI
- logging
- config
- `.env.example`
- AGENTS.md
- CLAUDE.md
- pytest
- ruff
- doctor command

완료 조건:

```bash
pytest
ruff check .
python -m shorts_factory doctor
```

성공.

---

# 62. Phase 1 — Domain Schema

구현:

- enums
- Project
- ResearchResult
- ScriptResult
- Scene
- AssetRecord
- Manifest
- JSON serialization

완료:

- schema test
- sample JSON round trip

---

# 63. Phase 2 — Project State

구현:

- project creation
- slug
- directory layout
- checkpoint
- state
- resume
- atomic JSON write

완료:

프로세스가 강제 종료된 뒤 다시 실행해도 이미 완료된 작업을 반복하지 않는다.

---

# 64. Phase 3 — Mock End-to-End

실제 AI API 없이:

```text
Topic
 ↓
Fake Research
 ↓
Fake Script
 ↓
Fake Scenes
 ↓
Fixture Video
 ↓
Fixture Audio
 ↓
FFmpeg
 ↓
final.mp4
```

완성.

> **실제 API 연결보다 이 단계가 먼저다.**

---

# 65. Phase 4 — LLM

실제 LLM 연결.

```text
Research structured output
Writer structured output
Director structured output
```

각 결과 Pydantic validation.

잘못된 structured output:

```text
invalid
 ↓
validation error 포함하여 retry 1회
 ↓
fail
```

무한 retry 금지.

---

# 66. Phase 5 — Search / Research

실제 source acquisition.

목표:

```text
Topic → Source-backed Claims
```

최소 저장:

- URL
- Title
- Publisher
- Claim mapping

---

# 67. Phase 6 — TTS

전체 Narration → audio.

완료:

- audio 생성
- duration 측정
- manifest 반영

---

# 68. Phase 7 — Video Provider

처음에는 **Provider 하나만** 구현한다.

```text
Scene
 ↓
Prompt Adapter
 ↓
Submit
 ↓
Poll
 ↓
Download
```

처음부터 Veo/Kling/다른 서비스 여러 개를 동시에 구현하지 않는다.

---

# 69. Phase 8 — Render

```text
Scenes
+ Voice
+ Subtitle
+ BGM(optional)
 ↓
FFmpeg
 ↓
final.mp4
```

---

# 70. Phase 9 — Hardening

- budget guard
- retry
- fallback
- resume
- technical QA
- structured logs
- error normalization

---

# 71. Phase 10 — 실제 10개 제작

이 단계에서는 기능 개발을 일단 멈춘다.

테스트 구성 예:

```text
A: 4편
B: 3편
C: 3편
```

총 10개.

---

# 72. 수동 콘텐츠 평가

각 영상:

```yaml
hook: 1-5
script_clarity: 1-5
visual_quality: 1-5
scene_continuity: 1-5
factual_confidence: 1-5
upload_worthy: true

notes:
  - ...
```

---

# 73. 자동화 확장 기준

새 기능을 자동화하기 전에 묻는다.

> 이 작업을 영상 10개를 만드는 동안 실제로 여러 번 반복했는가?

NO라면 MVP에서는 만들지 않는다.

---

# 74. 이후 후보 기능

10편 테스트 이후에만 검토:

- Topic discovery
- Topic scoring
- 자동 Visual QA
- BGM 선택
- Title variants
- YouTube upload
- 예약 발행
- 성과 수집
- Retention 분석
- Topic feedback loop

---

# 75. 향후 Topic Score

```python
class TopicCandidate(BaseModel):
    topic: str
    content_type: ContentType

    familiarity_score: float
    curiosity_score: float
    visualizability_score: float
    factability_score: float
    novelty_score: float

    total_score: float
```

MVP에는 구현하지 않는다.

---

# 76. 좋은 소재의 기준

## Familiarity

시청자가 경험해본 대상인가?

## Knowledge Gap

익숙하지만 내부를 모르는가?

## Visualizability

AI 영상으로 설명하기 좋은가?

## Hiddenness

실제 카메라로 보기 어려운가?

## Transformation

장면 변화가 존재하는가?

## Factability

신뢰 가능한 공개 자료를 확보할 수 있는가?

---

# 77. 피해야 하는 소재

- 신뢰할 만한 자료가 거의 없는 것
- 보안상 실제 내부 구조 확인이 어려운 것
- 의학적 오해 위험이 높은 주제
- 특정 기업의 비공개 내부 시스템으로 오해될 수 있는 것
- 범죄 방법으로 전용 가능한 민감한 세부 설명
- 과장된 Hook 외에는 정보적 가치가 없는 소재

---

# 78. 초기 콘텐츠 10개 예시

## A — Hidden System

1. 비가 많이 오면 서울 지하에서는 무슨 일이 벌어질까?
2. 공항에서 캐리어는 어떻게 내 비행기를 찾아갈까?
3. 아파트에서 버린 쓰레기는 그날 밤 어디로 갈까?
4. 수도꼭지를 틀기 전 물은 어디에 있었을까?

## B — Inside Object

5. ATM은 지폐를 어떻게 한 장씩 세는 걸까?
6. 에스컬레이터 계단은 끝에서 어디로 사라질까?
7. 자동문은 사람이 오는 것을 어떻게 알까?

## C — Behind Action

8. 카드를 찍는 1초 동안 어떤 일이 일어날까?
9. 인터넷 검색 버튼을 누르면 데이터는 어디로 갈까?
10. 배달 주문을 누른 순간 어떤 시스템이 움직이기 시작할까?

---

# 79. Coding Agent용 Master Prompt

아래를 Codex 또는 Claude Code에 초기 구현 지시로 사용할 수 있다.

```text
You are the lead implementation engineer for this repository.

First read:
1. AGENTS.md
2. CLAUDE.md if present
3. docs/IMPLEMENTATION_SPEC.md

The product is a CLI-first AI Shorts production pipeline.

The core input is a topic.
The final MVP output is a locally rendered vertical MP4.

Critical architecture constraints:

- Python 3.12.
- Do not build a web UI.
- Do not introduce a multi-agent runtime.
- Do not introduce LangGraph, CrewAI, AutoGen, or equivalent orchestration frameworks.
- Use a deterministic pipeline with explicit stages.
- All model-generated structured data must be validated through Pydantic models.
- External services must be behind provider interfaces.
- project.json is the canonical persistent project state.
- Every expensive stage must be resumable and idempotent.
- Paid provider calls must never run from normal unit/integration tests.
- Video generation must have configurable cost limits and maximum retry counts.
- Preserve provenance and source references for factual claims.
- Separate observed/reconstructed/conceptual visuals.
- Do not implement social upload automation during MVP.
- Do not add infrastructure unless required by current acceptance criteria.

Implementation procedure:

1. Inspect the current repository before editing.
2. Compare current state with the implementation spec.
3. Implement only the current requested phase.
4. Add or update tests.
5. Run lint and tests.
6. Fix regressions.
7. Summarize:
   - files changed
   - architecture decisions
   - tests run
   - remaining risks
   - next recommended phase

Never silently expand scope.

If the specification and existing code conflict, document the conflict before making a large architecture change.

Start with Phase 0 only unless the repository has already completed it.
```

---

# 80. Phase 0 Agent Prompt

```text
Implement Phase 0 from docs/IMPLEMENTATION_SPEC.md.

Goal:
Create a clean Python 3.12 repository bootstrap for the Shorts Factory.

Required:
- src layout
- pyproject.toml
- Typer CLI
- settings loader
- structured logging
- .env.example
- pytest
- ruff
- doctor command
- AGENTS.md
- CLAUDE.md
- minimal README

Do not:
- implement LLM APIs
- implement video generation
- implement TTS
- implement web UI
- add a database
- add agent frameworks

Acceptance:
- package installs
- CLI help works
- doctor command works
- pytest passes
- ruff passes

Finish by showing the exact commands used to verify the implementation.
```

---

# 81. Phase 1 Agent Prompt

```text
Implement Phase 1: domain schemas.

Read the implementation specification.

Create typed Pydantic models for:

- enums
- Project
- StageRecord
- ResearchResult
- Claim
- SourceRef
- ScriptResult
- ScriptBeat
- Scene
- ContinuitySpec
- AssetRecord
- Manifest

Requirements:

- JSON round-trip serialization
- explicit schema version
- strong enum usage
- useful validation errors
- no API calls
- no business logic in provider modules

Tests must include:
- valid fixtures
- invalid enum
- invalid scene duration
- invalid traceability where applicable
- project round trip

Do not proceed to later phases.
```

---

# 82. Phase 2 Agent Prompt

```text
Implement persistent project state and checkpoint/resume behavior.

Requirements:

- create project directory
- project.json canonical state
- atomic JSON writes
- stage state transitions
- resume completed projects safely
- mark failures without losing prior results
- support idempotent stage execution
- CLI status command

Simulate abrupt termination in tests and verify that completed work is not repeated.

Do not connect external APIs.
```

---

# 83. Phase 3 Agent Prompt

```text
Implement a complete mock end-to-end pipeline.

Use only mock providers and local fixtures.

Input:
topic

Output:
final vertical MP4

The pipeline must exercise:

topic
→ mock research
→ mock script
→ mock scenes
→ mock assets
→ mock narration
→ subtitles
→ manifest
→ FFmpeg composition
→ final.mp4

No paid API may be called.

This phase is complete only if an end-to-end integration test produces a valid video file and ffprobe validates the output.
```

---

# 84. Coding Agent 금지 지침

```text
Do not refactor unrelated modules.
Do not replace working dependencies without a concrete reason.
Do not create abstraction layers before a second implementation requires them.
Do not create an internal event bus.
Do not introduce a database during MVP.
Do not create background workers during MVP.
Do not implement upload automation.
Do not add multiple providers at once.
Do not silently change schemas.
Do not skip tests because external APIs are unavailable.
Do not expand scope to "improve future scalability" without a present requirement.
```

---

# 85. Git 전략

Phase별 branch 권장:

```text
feat/bootstrap
feat/domain-model
feat/project-state
feat/mock-e2e
feat/llm
feat/research
feat/tts
feat/video-provider
feat/render
```

Commit 예:

```text
feat(domain): add scene and research schemas
test(state): verify pipeline resume
feat(media): add ffmpeg compositor
```

---

# 86. Architecture Decision Record

큰 결정만:

```text
docs/adr/
```

예:

```text
0001-deterministic-pipeline.md
0002-project-json-state.md
0003-ffmpeg-composition.md
0004-provider-adapters.md
```

ADR 자체를 새로운 관리 업무로 만들지 않는다.

---

# 87. 코드 품질 원칙

좋은 예:

```python
async def direct_script(
    script: ScriptResult,
    research: ResearchResult,
    config: DirectorConfig,
) -> list[Scene]: ...
```

피해야 할 예:

```python
async def agent_do_everything(context): ...
```

---

# 88. Side Effect 분리

```text
Domain Logic
≠
File I/O
≠
Network I/O
≠
Media Processing
```

이를 지키면 테스트와 provider 교체가 쉬워진다.

---

# 89. 실제 API 연결 전 Checklist

- [ ] Mock E2E 통과
- [ ] Resume 통과
- [ ] Budget Guard 존재
- [ ] API key 로그 방지
- [ ] `.env` gitignore
- [ ] paid API test 차단
- [ ] retry 제한
- [ ] timeout 존재
- [ ] provider error normalization
- [ ] project state atomic write
- [ ] dry-run 지원

---

# 90. 영상 1편 생성 전 Checklist

- [ ] Topic 확정
- [ ] Content Type 확정
- [ ] Research source 확보
- [ ] unsupported factual claim 없음
- [ ] Script 45~70초
- [ ] Scene 8~14
- [ ] 모든 Scene에 `reality_type`
- [ ] HIGH priority Scene이 budget 제한 이하
- [ ] 예상 비용 ≤ project budget
- [ ] continuity 필요 대상 확인
- [ ] conceptual visualization 오해 가능성 확인

---

# 91. Final Video Checklist

- [ ] 첫 3초에 질문 또는 시각적 Hook이 존재
- [ ] Narration과 Visual이 대응
- [ ] Scene 간 핵심 대상 consistency
- [ ] 생성된 이상한 글자·로고 없음
- [ ] 설명용 시각화를 실제 구조처럼 단정하지 않음
- [ ] 자막 safe area
- [ ] 음성 clipping 없음
- [ ] BGM이 Narration을 덮지 않음
- [ ] 길이가 목표 범위
- [ ] 심각한 사실 오류 없음
- [ ] 실제 업로드할 의향이 있음

---

# 92. KPI

## Development KPI

```text
Pipeline success rate
Resume success rate
Average cost/video
Failed generations/video
Manual interventions/video
```

## Content KPI

향후 실제 업로드 후:

```text
Viewed vs Swiped Away
Audience Retention
Average Percentage Viewed
Rewatch behavior
Likes / views
Comments / views
Subscribers gained/video
```

성과 API 연결은 MVP 이후다.

---

# 93. 실패 유형을 구분

## Development Failure

매 영상마다 시스템을 고치는 시간이 과도하다.

→ Architecture 또는 안정성 문제.

## Generation Failure

특정 Scene이 반복해서 깨진다.

→ Prompt Adapter / Provider / Fallback 문제.

## Content Failure

영상은 잘 생성되지만 조회가 나오지 않는다.

→ **코드를 추가하지 말고 Topic / Hook / Story를 수정한다.**

이 구분이 매우 중요하다.

---

# 94. Scope Creep 방지 원칙

이 프로젝트에서 가장 위험한 상황:

> **쇼츠 채널을 만들려다가 영상 생성 플랫폼 자체를 개발하는 것**

새 기능을 만들기 전에 묻는다.

```text
이 기능이 다음 10개의 영상을
더 빠르게 또는 더 좋게 만드는가?
```

아니라면 MVP에서는 만들지 않는다.

---

# 95. 권장 개발 순서 최종 요약

```text
0. Repo Bootstrap
1. Domain Schema
2. Project State
3. Mock E2E
4. LLM
5. Research/Search
6. TTS
7. ONE Video Provider
8. FFmpeg Render
9. Retry / Cost / Fallback
10. 실제 영상 10개 제작
11. 실제 성과 평가
12. 그 이후 자동화 결정
```

---

# 96. 최종 Architecture

```text
                    ┌──────────────┐
                    │    Topic     │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   Research   │
                    └──────┬───────┘
                           │
                   source-backed claims
                           │
                           ▼
                    ┌──────────────┐
                    │    Writer    │
                    └──────┬───────┘
                           │
                         Script
                           │
                           ▼
                    ┌──────────────┐
                    │   Director   │
                    └──────┬───────┘
                           │
                         Scenes
                           │
                           ▼
               ┌───────────────────────┐
               │  Prompt Adapter       │
               └───────────┬───────────┘
                           │
                 ┌─────────┴──────────┐
                 ▼                    ▼
          ┌────────────┐       ┌────────────┐
          │   Video    │       │   Image    │
          │  Provider  │       │  Provider  │
          └──────┬─────┘       └──────┬─────┘
                 │                    │
                 └──────────┬─────────┘
                            │
                          Assets
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
      ┌────────────┐                ┌────────────┐
      │    TTS     │                │ Subtitle   │
      └──────┬─────┘                └─────┬──────┘
             │                            │
             └──────────────┬─────────────┘
                            ▼
                     ┌────────────┐
                     │  Manifest  │
                     └──────┬─────┘
                            ▼
                     ┌────────────┐
                     │   FFmpeg   │
                     └──────┬─────┘
                            ▼
                    ┌──────────────┐
                    │  final.mp4   │
                    └──────────────┘
```

---

# 97. 결론

첫 버전에서 가장 중요한 것은 특정 영상 AI 모델이 아니다.

## 1순위 — 안정적인 데이터 구조

```text
Research → Script → Scene
```

이 구조가 명확해야 한다.

## 2순위 — Resume 가능한 Pipeline

비싼 API를 사용하는 만큼 중간 결과를 잃지 않는다.

## 3순위 — 사실성

AI 영상은 잘못된 구조도 실제처럼 보이게 만들 수 있다.

따라서:

```text
OBSERVED
RECONSTRUCTED
CONCEPTUAL
```

구분을 시스템 수준에서 유지한다.

## 4순위 — 비용

영상 모델 호출 횟수와 retry를 제한한다.

## 5순위 — 실제 콘텐츠 검증

영상 10개를 제작하기 전에는 복잡한 자동화나 플랫폼화를 하지 않는다.

---

# 98. 답변 가능성 여부 판단

**답변 가능.**

이 문서는 소프트웨어 및 콘텐츠 파이프라인 설계 제안이다.

단, 실제 사용하는 영상 생성/TTS/Search API에 따라 Provider 구현, 모델명, 가격, 해상도, generation length, asynchronous job 방식은 달라질 수 있다.

따라서 각 Provider를 실제 연결하는 시점에는 해당 서비스의 **최신 공식 문서**를 다시 확인해야 한다.

---

# 99. 출처 및 Codex / Claude Code 운영 참고

본 보고서 중 Codex/Claude Code 저장소 운용 방식은 다음 공식 문서를 참고했다.

- OpenAI Codex Documentation  
  https://developers.openai.com/codex

- OpenAI — Custom instructions with AGENTS.md  
  https://developers.openai.com/codex/agent-configuration/agents-md

- OpenAI — Codex CLI  
  https://developers.openai.com/codex/cli

- Anthropic — Claude Code Overview  
  https://docs.anthropic.com/en/docs/claude-code/overview

- Anthropic — Claude Code Memory / CLAUDE.md  
  https://docs.anthropic.com/en/docs/claude-code/memory

- Anthropic — Claude Code Hooks  
  https://docs.anthropic.com/en/docs/claude-code/hooks

Codex 공식 문서는 `AGENTS.md`를 프로젝트 지침에 사용할 수 있음을 설명한다.

Claude Code 공식 문서는 `CLAUDE.md`를 프로젝트 컨텍스트로 사용하는 방식을 제공한다. 또한 `CLAUDE.md`는 강제 정책이라기보다 세션 컨텍스트이므로, 절대로 어겨서는 안 되는 규칙은 테스트·CI·hook 같은 deterministic mechanism으로 보강하는 것이 적절하다.

---

# Appendix A — 최초 실행 목표

```bash
git clone ...
cd invisible-shorts

cp .env.example .env

pip install -e ".[dev]"

shorts doctor

shorts create \
  --topic "ATM은 돈을 어떻게 세는 걸까?" \
  --type inside_object \
  --until direct

shorts inspect projects/atm-money-counter

shorts generate projects/atm-money-counter

shorts render projects/atm-money-counter

shorts status projects/atm-money-counter
```

결과:

```text
projects/atm-money-counter/output/final.mp4
```

---

# Appendix B — MVP Definition of Done

- [ ] Python 3.12 기반 CLI
- [ ] A/B/C 콘텐츠 타입
- [ ] ResearchResult 저장
- [ ] Claim별 source traceability
- [ ] ScriptResult 저장
- [ ] 8~14 Scene
- [ ] Scene reality type
- [ ] Prompt Adapter
- [ ] 1개의 실제 Video Provider
- [ ] 1개의 실제 TTS Provider
- [ ] generation retry 제한
- [ ] fallback
- [ ] project budget
- [ ] checkpoint / resume
- [ ] dry-run
- [ ] SRT
- [ ] FFmpeg composition
- [ ] 1080x1920 MP4
- [ ] unit tests
- [ ] mock integration tests
- [ ] secrets 보호
- [ ] 실제 영상 10편
- [ ] 수동 품질 평가
- [ ] 심각한 사실 오류 0건

MVP 완료 후에만 자동 업로드와 성과 피드백 루프를 검토한다.


---

# 부록 C — v0.2 개정 (Mock/Production 분리와 Content Quality Contract)

첫 구현의 결과물을 실제로 재생해 본 뒤 드러난 문제를 반영한다. 본문과 충돌하면
이 부록을 따른다.

## C.1 Mock 산출물을 final.mp4라고 부르지 않는다

provider 중 하나라도 mock이면 그 실행은 production이 아니다.

```text
production_ready = 모든 provider가 real
```

- production 실행만 `output/final.mp4`를 쓴다.
- 그 외에는 `output/mock_preview.mp4`를 쓰고, 좌측 상단에 `MOCK PIPELINE`
  워터마크를 강제로 굽는다.
- CLI를 명시적으로 분리한다: `shorts render`(real 전용)와 `shorts mock-render`.
  각 명령은 반대 상황에서 거부하고, 어느 쪽을 써야 하는지 알려 준다.
- 인코딩은 staging 경로에 하고, 게이트를 통과한 뒤에만 출력 디렉터리로 옮긴다.
  `final.mp4`가 잘못된 상태로 존재하는 순간이 없어야 한다.
- 둘 중 하나를 게시하면 반대쪽 산출물은 삭제한다.

## C.2 Technical QA 강화

오디오 스트림의 존재는 소리의 존재가 아니다. ffprobe로는 구분되지 않는다.

```text
VIDEO   stream 존재 / 1080x1920 / duration > 0
AUDIO   stream 존재 / mean volume ≥ floor / silence ratio ≤ max
CONTENT mock provider 미사용 / scene asset 전부 존재
```

`ProductionReadinessResult.ready == False`면 `final.mp4`를 만들지 않는다.
video·audio가 무효면 mock 실행이라도 **아무것도 게시하지 않는다.**

임계값은 `config/settings.yaml`의 `quality.audio`에 둔다.

## C.3 Research가 질문을 먼저 정규화한다

주제 문장은 대개 모호하다. Research는 조사 전에 다음을 확정한다.

```yaml
original_topic:   "ATM은 돈을 어떻게 세는 걸까?"
resolved_question: "현금 입금이 가능한 ATM은 들어온 지폐를 어떻게 한 장씩 분리하고 확인하는가?"
scope:            "현금 입금·환류형 ATM의 지폐 수납 경로"
excluded:         ["제조사별 비공개 설계", "인출 전용 ATM의 방출 경로"]
```

Writer와 Director는 `topic`이 아니라 `resolved_question`을 받는다.

## C.4 Director는 각 Scene이 존재할 이유를 적는다

```yaml
question_answered: "여러 장의 지폐가 어떻게 한 장이 되는가?"
key_object:        "a single banknote at the front of the stack"
mechanism:         "a rubber feed roller grips the front note"
visible_change:    "stack of notes at rest → one note peeled off and moving inward"
camera_path:       "macro tracking shot alongside the roller"
```

`visible_change`를 전환(→)으로 쓸 수 없다면 그 Scene은 static exposition이다.
이웃 Scene과 합치거나 버린다.

## C.5 하나의 World를 공유한다

12개의 독립 클립이 아니라 하나의 기계를 12번 찍은 것이어야 한다.

```yaml
world:
  machine_id:   ATM_DEPOSIT_001
  visual_style: documentary CGI cutaway
  environment:  a modern Korean indoor ATM booth
continuity:
  - continuity_id: NOTE_HERO
    fixed_description: "a single generic banknote, muted blue-green paper, ..."
```

Scene은 `continuity_ids`로 참조만 한다. 설명을 복제하지 않는다. Prompt Adapter가
world와 참조된 description을 **모든** prompt에 주입한다.

## C.6 Style Bible

`config/visual_styles.yaml`은 look과 함께 **금지 목록**을 갖는다. 영상 모델은
"기술 설명"이라는 말을 들으면 홀로그램과 공중 UI를 만든다. `avoid` 목록은
director가 무엇을 썼든 모든 negative prompt에 들어간다.

## C.7 Content Quality Contract

`config/content_contract.yaml`. 코드가 강제하는 조항이며, 끄면 검사도 꺼진다.

```yaml
hook:   { must_create_question: true, max_seconds: 3 }
script: { ban_generic_nouns: true, max_generic_nouns: 3, concrete_mechanism_required: true }
scene:  { visible_change_required: true, question_answered_required: true,
          static_exposition_forbidden: true, shared_world_required: true }
final:  { mock_assets_allowed: false, silent_audio_allowed: false }
```

---

# 부록 D — v0.3 개정 (Spoken Narration & Scene-Speech Sync)

## D.1 문제

`Writer → narration 문자열 → TTS` 구조에서는 한 호흡이 길어지고, 한 문장에 여러
사건이 들어가며, Scene 경계가 음성 의미 단위와 무관하게 정해진다.

## D.2 새 데이터 흐름

```text
ResearchResult → ScriptResult → SpeechPlan → Scene[] → TTS → Timeline → Caption
```

`ScriptResult`는 **무엇을 어떤 순서로** 말할지, `SpeechPlan`은 **어떻게 끊어
읽을지**를 담는다. 둘 다 유지한다.

## D.3 SpeechUnit / SpeechPlan

```python
class SpeechUnit(BaseModel):
    id: str
    text: str
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    delivery: DeliveryMode = DeliveryMode.NEUTRAL
    emphasis_words: list[str] = []
    referenced_claim_ids: list[str] = []
    beat_id: str | None = None
    preferred_scene_id: str | None = None
```

`SpeechPlan`은 `tone_profile`, `units`, `target_duration_sec`,
`estimated_duration_sec`를 갖는다. 인접한 `pause_after`/`pause_before`는
더해지지 않고 **큰 쪽이 이긴다**.

## D.4 Speech Planner는 Agent가 아니다

`speak` 스테이지는 **LLM을 호출하지 않는다.** 이미 쓰인 한국어를 호흡으로 나누는
일은 규칙으로 충분하고, 모델을 부르면 비용·지연·비결정성만 늘어난다.
리듬(문장 길이 변화)은 분절기가 만들 수 없으므로 Writer 프롬프트가 담당하고,
결과는 contract가 검사한다.

분절 규칙:

```text
≤ 30자   그대로 둔다
31~40자  경고, 분할은 하지 않는다
> 40자   쉼표 → 연결어미(면서/는데/지만/니까/…) 순으로 분할
```

고유명사·숫자·조사가 잘려 나가지 않도록 `min_unit_chars` 미만 조각은 이웃에
다시 붙인다.

## D.5 Pause는 이유가 있어야 한다

`config/voice.yaml`의 표에서 온다. 코드에 매직 넘버를 두지 않는다.

```text
clause 150 / shift 250 / sentence 320 / question 380 / reveal 450 / section 550 (ms)
```

## D.6 Scene은 완결된 unit만 갖는다

Scene은 `speech_unit_ids`를 갖고, `narration`은 **그 unit들을 이어 붙여 다시
생성한다.** 문장 중간에서 컷이 나는 것이 구조적으로 불가능해진다.
모든 unit은 순서대로 정확히 한 번씩 사용된다.

## D.7 TTS는 unit 단위로 합성한다

unit별 합성 후 계획된 pause만큼 무음을 삽입해 이어 붙인다.

- 문자당 과금 provider에서는 1회 호출과 **총 비용이 같다.**
- 대가는 요청 수 증가, 얻는 것은 unit별 **실측 타이밍**이다. Scene 길이와 자막
  타이밍이 추정이 아니라 측정값이 된다.
- provider 문법은 Domain에 넣지 않는다. `SpeechPlan → TTS Adapter → provider`.
  Adapter는 unit 분할 방식과 단일 문자열(문장부호·단락) 방식을 모두 제공한다.

## D.8 Subtitle은 SpeechUnit에서 만든다

narration 문자열을 다시 자르지 않는다. unit 하나가 cue 하나이고, cue는 뒤따르는
pause 동안 유지된다. 길면 2줄까지 wrap하되 의미 단위는 쪼개지 않는다.

## D.9 Speech Contract

`config/voice.yaml`. `max_preferred_unit_chars`, `hard_split_review_chars`,
`max_information_events`, `max_consecutive_same_ending`,
`min_length_variation_ratio`, `pauses_ms`.

검사 항목: unit 길이, 한 호흡 다중 사건, 어미 반복, 리듬 평탄화, pause 부재,
Scene-Speech 정합.

## D.10 Narrator Persona

`config/voice.yaml`의 `tone_profile`. 코드나 프롬프트에 하드코딩하지 않는다.

```yaml
persona: calm_curiosity_documentary
formality: polite_conversational
energy: moderate
```

`~합니다/~됩니다`가 기본이되 전부 같은 어미로 끝내지 않는다. 전환·부연에 `~죠`,
`~는데요`, 질문에 `~까요?`를 **기능에 따라** 쓴다.


---

# 부록 E — v0.4 개정 (남은 P1: 소리 설계와 자막 강조)

실제 Video Provider를 붙이기 전에 남아 있던 P1을 정리한다.

## E.1 Scene SFX

BGM보다 Scene에 맞는 작은 효과음이 이 포맷에서는 더 중요하다.

```text
Scene.sfx_cue → config/sfx.yaml library → 파일 → manifest의 scene start에 배치
```

- `config/sfx.yaml`의 `vocabulary`가 Director가 고를 수 있는 이름의 전부다.
  짧게 유지한다. 55초 안에 열두 가지 소리가 나면 그건 소음이다.
- `library`는 그 이름을 로컬 파일에 연결한다. **저장소에 오디오를 포함하지
  않는다.** 파일이 없는 cue는 경고 후 건너뛴다. 렌더를 실패시키지 않는다.
- 기본값은 `enabled: false`다. 사용자가 소리를 넣기 전까지 동작이 바뀌지 않는다.
- 믹싱은 `amix ... normalize=0`이다. 조용한 효과음 하나가 내레이션 레벨을 같이
  끌어내리지 않게 한다. 뒤의 limiter가 피크를 잡는다.
- BGM ducking과 공존한다: 음악은 목소리에 sidechain으로 눌리고, SFX는 그 위에
  얹힌다.

## E.2 자막 핵심 단어 강조

- Writer가 beat당 `emphasis` 한 단어를 선택할 수 있다(선택 사항).
- Speech Planner가 그 단어를 **실제로 포함한 unit**에만 전달한다.
- 굽는 ASS에서만 색을 입힌다. cue당 하나뿐이다. 두 개면 강조가 아니다.
- 납품물인 SRT는 평문을 유지한다. SRT 스타일링은 플레이어마다 다르다.
- 색은 `config/settings.yaml`의 `subtitles.emphasis_colour`(ASS는 `&HBBGGRR`).

## E.3 제거한 필드

`SpeechUnit.preferred_scene_id`를 제거했다. 현재 스테이지 순서에서는 SpeechPlan이
Scene보다 먼저 만들어지므로 이 필드를 채울 수 있는 코드가 존재하지 않는다.
항상 null인 필드는 읽는 사람을 오도한다. Scene이 `speech_unit_ids`로 unit을
가져가는 방향만 남긴다.


---

# 부록 F — v0.5 개정 (Phase 7: Veo 3 연결)

스펙 §68이 요구한 "실제 Video Provider 하나"를 Google Veo 3로 채운다.
Gemini API 경로를 쓴다(`VIDEO_API_KEY`, 헤더 `x-goog-api-key`).

```text
POST models/{model}:predictLongRunning  → operation name
GET  {operation name}                   → done / error / 진행 중
GET  {video uri}                        → mp4
```

## F.1 클립 길이는 이산값이다

Veo는 고정 길이 클립을 돌려준다. 3.3초를 요청하는 개념이 없다.

`VideoProvider.snap_duration()`을 프로토콜에 추가했다. 길이 규칙은 설정이 아니라
**provider의 사실**이므로 provider가 소유한다. 파이프라인이 hash와 비용 추정
**전에** 호출하므로 요청·캐시 키·가격이 항상 일치한다.

올림한다. 짧게 온 클립은 늘릴 수 없지만 긴 클립은 잘라낼 수 있다.

```text
3.29s 요청 → 4s 청구 → normalize가 3.29s로 트림
```

## F.2 Veo 3.1은 `generateAudio`를 아예 받지 않는다

2026-08-19 실제 호출로 확인:

```text
HTTP 400 INVALID_ARGUMENT
`generateAudio` isn't supported by this model. Please remove it or refer to
the Gemini API documentation for supported usage.
```

Veo 3.1은 오디오 생성이 네이티브라 켜고 끄는 파라미터가 아니다. `false`를 보내도
400이다. 따라서 `video.generate_audio`는 3항 값이다:

| 값 | 요청 |
|---|---|
| 비움(`None`) | 필드를 **보내지 않음** — Veo 3.1이 받는 유일한 형태. 기본값 |
| `false` / `true` | 필드를 그대로 전송 — 파라미터를 문서화한 모델 전용 |

우리 내레이션과 충돌할 걱정은 없다. 정규화 단계가 `-an`으로 클립 오디오를 버린다.

**비용과도 무관하다.** Google 단가는 오디오 포함 가격이라 어느 쪽이든 같다.

## F.2b 거절된 파라미터는 떨어뜨리고 재시도한다

preview 모델은 받는 파라미터 집합이 리비전마다 바뀐다. 실제로 한 번에 하나씩
400을 맞았다:

```text
`generateAudio` isn't supported by this model.
allow_adult for personGeneration is currently not supported.
```

에러 메시지가 **필드 이름을 알려주므로**, 그 필드를 빼고 다시 보낸다. 400은
생성 전 거절이라 과금이 없고, 어차피 선택적 파라미터였다.

떨어뜨릴 수 있는 것은 `DROPPABLE_PARAMETERS`에 한정한다:

| 파라미터 | 거절 시 |
|---|---|
| `generateAudio`, `personGeneration`, `resolution`, `sampleCount`, `negativePrompt` | 빼고 재시도 |
| `aspectRatio`, `durationSeconds` | **에러.** 빼면 우리가 못 쓰는 클립이 돌아온다 |

우리가 **보낸 적 없는** 필드를 언급하는 메시지는 다른 문제이므로 삼키지 않는다.
`ContentBlockedError`도 이 경로를 타지 않는다.

## F.3 정책 거부는 일시적 실패가 아니다

거부된 프롬프트를 3회 재시도하면 돈만 세 번 나가고 세 번 다 실패한다.

`ContentBlockedError(ProviderError)`를 추가하고, `VideoJobState.blocked`로
전달한다. asset 스테이지는 이 예외를 만나면 **재시도 없이** 즉시 스틸 이미지
fallback으로 넘어간다.

## F.4 모델 id와 요금 (2026-08-19 확인)

**Veo 3는 종료됐다.** `veo-3.0-generate-001`, `veo-3.0-fast-generate-001`,
`veo-2.0-generate-001`은 2026-06-30에 셧다운됐다. registry가 이 id들을 거부한다.
유료 실행 도중 404를 만나는 것보다 시작 전에 막는 게 낫다.

Veo 3.1을 쓴다. 초당 과금이며 오디오 포함 가격이다.

```text
veo-3.1-generate-preview        Standard   $0.40/s   (720p·1080p)
veo-3.1-fast-generate-preview   Fast       $0.15/s   (720p·1080p)
```

요금이 모델별로 2.7배 차이 나므로 `BudgetGuard.estimate_video_usd`는 **모델 id로
먼저 조회**하고 provider 이름은 fallback으로만 쓴다. provider당 단일 단가였다면
둘 중 하나는 반드시 틀린 값이 된다.

산수를 먼저 하라. 11개 씬을 4/6/8초로 스냅하면 약 60초가 청구된다.

```text
Standard  60s x $0.40 = 약 $24 / 편
Fast      60s x $0.15 = 약 $9  / 편
```

기본 상한 $12는 Fast는 통과시키고 Standard는 도중에 멈춘다. 의도한 것이다.
`--dry-run`으로 금액을 먼저 보고 `project.max_total_usd`를 의식적으로 올린다.

요금과 모델 id는 계속 바뀐다. 유료 실행 전에 다시 확인한다.

```bash
shorts resume projects/<slug> --dry-run   # 씬별 초와 금액을 먼저 출력
```

`project.max_total_usd`를 의식적으로 올리거나 `max_scene_attempts`를 낮춘다.

## F.5 검증되지 않은 부분

이 어댑터는 **라이브 API로 실행된 적이 없다.** 문서화된 요청·응답 형태를 보고
작성했다. 따라서:

- 응답 파싱은 한 경로를 하드코딩하지 않고 트리를 탐색한다. 형태가 바뀌면
  `KeyError`가 아니라 명확한 에러로 떨어진다.
- 흔들릴 수 있는 값은 전부 `config/settings.yaml`에 있다.
  `base_url`, `model`, `allowed_durations`, `resolution`, `person_generation`,
  그리고 이 코드가 모르는 필드를 위한 `extra_parameters`.
- 요청 형태와 응답 처리는 `httpx.MockTransport`로 테스트한다. 실제 API가 이
  형태와 맞는지는 `pytest -m live`만 답할 수 있다.

첫 유료 실행 전에 Google의 현재 Veo 문서를 다시 확인한다. 2026-01 업데이트로 Veo 3.1은 `aspectRatio: "9:16"`을
네이티브로 지원한다(그 전에는 API가 16:9로 강제한다는 보고가 있었다).
`durationSeconds` 4/6/8, `resolution` 720p/1080p/4K도 확인했다. 9:16 · 1080p면
1080x1920이 나오고 이는 우리 출력 규격과 정확히 일치한다.

단, 레퍼런스 이미지를 쓰는 경로에는 16:9 제약이 있다는 보고가 있다. 우리는
text-to-video만 쓰므로 해당되지 않는다.
