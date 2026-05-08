# 항목별 액션 분리 — 설계 문서

작성: 2026-05-08
브랜치: main (작업은 별도 브랜치에서)

## 한 줄 요약

전체 draft는 사이드바 버튼으로 한 번에 생성하되, 그 후 모든 항목별 작업(적용·수정·대화)은 메인 채팅을 거치지 않고 카드 안에서만 일어나도록 흐름·API·상태 모델을 정리한다.

## 배경 / 문제

현재 시스템은 일괄 채우기 후 항목별 액션 4개(`✓적용` / `✏수정` / `🔁다시` / `💬대화`)를 UI에 노출하지만, 실제 동작에 결함이 있다.

1. `🔁 다시`가 메인 채팅에 메시지를 보내고 Router → Generator를 거치는데, Generator는 `state.plans` 전체를 순회해 **모든 항목**을 재생성한다 (`backend/app/graph/nodes/generator.py` `for plan in state.plans:` 루프). 단일 항목만 재생성하는 경로가 코드에 없다.
2. `✓ 적용` 버튼은 streamlit 로컬 플래그(`applied_<item_id>`)만 토글한다. 백엔드와 통신하지 않아 다운로드되는 `.hwpx`는 적용 여부와 무관하게 모든 draft를 포함한다 — "적용"이라는 단어와 실효가 따로 논다.
3. 항목별 액션이 메인 채팅 thread를 오염시킨다 ("{label} 항목을 다시 써줘" 같은 메시지가 채팅에 남음).
4. Verifier가 모든 draft에 `approved=True`를 자동으로 도장 찍어 Renderer 필터(`if draft.approved`)가 사용자 의도를 반영하지 못한다.

이 결함들이 누적되어 사용자는 "내가 손본 항목과 안 한 항목의 구분"을 못 하고, 다운로드 결과는 검토가 끝나지 않은 draft까지 그대로 들어간다.

## 결정된 흐름 (사용자 합의 사항)

다음 8개 결정으로 큰 그림이 잡혔다 (브레인스토밍 결과):

1. **C — 채팅과 항목별 액션 완전 분리.** 메인 채팅은 일반 QA·양식·자료 안내만. 항목별 액션은 카드 내에서만.
2. **D — 적용 = 출력 포함 + 잠금.** 적용된 draft만 다운로드 출력에 포함되고, 적용 후엔 다른 액션을 받지 않는다.
3. **B — 명시적 시작 버튼.** 사이드바 `▶ 양식 자동 채우기 시작` 버튼이 일괄 생성을 트리거한다. 채팅으로는 절대 트리거되지 않는다.
4. **A — 미적용은 양식 원본 그대로.** 비파괴적. 사용자가 한컴오피스에서 직접 채울 단서가 살아 있다.
5. **C — 🔁 다시 버튼 제거, 💬 대화로 일원화.** "다시 써줘"는 카드 대화 안에서 처리. 카드 액션은 ✓적용 / ✏수정 / 💬대화 3개.
6. **A — 별도 🔓 해제 버튼.** 적용된 카드는 액션 영역이 🔓 해제만 노출. 의도가 명확하고 실수 방지.
7. **B — 다운로드 시점에 lazy 렌더.** 적용·해제는 가벼운 상태 토글, 무거운 zip은 다운로드 클릭 시점에만.
8. **B — 라우터 단순화 (일반 QA 전용).** Router 의도 분류 Solar 호출 제거. 그래프는 일괄 채우기 한 가지 직선 흐름만.

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│ Sidebar                                                          │
│  · 양식 업로드 (.hwpx)                                            │
│  · 자료 업로드 (PDF/docx/txt/hwpx)                                │
│  · ▶ 양식 자동 채우기 시작   ← POST /fill SSE                       │
│  · 📥 출력 .hwpx 다운로드   ← GET /output.hwpx (lazy)             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────┐  ┌────────────────────────────────────┐
│ Main Chat               │  │ 항목 카드 영역                       │
│  · 일반 QA 전용 (POST   │  │                                    │
│    /api/chat, Solar 직접)│  │  ┌─ 항목 N (미적용) ────────────┐   │
│  · 양식·자료 안내 질문   │  │  │ 라벨   draft text             │   │
│  · 채우기·재시도         │  │  │ ✓적용  ✏수정  💬대화            │   │
│    절대 트리거 안 됨      │  │  └──────────────────────────────┘   │
│                         │  │  ┌─ 항목 M (적용·잠금)──────────┐   │
│                         │  │  │ 라벨   draft text  🔒        │   │
│                         │  │  │ 🔓 해제                       │   │
│                         │  │  └──────────────────────────────┘   │
└─────────────────────────┘  └────────────────────────────────────┘
```

### 핵심 invariants

1. 메인 채팅은 어떤 경우에도 `form_doc` / `drafts` / `plans`를 변경하지 않는다.
2. 항목별 액션은 어떤 경우에도 `state.history`(채팅 기록)를 변경하지 않는다.
3. 적용된 항목(`locked=True`)은 잠겨 있어 실수로 덮어써지지 않는다 — 해제 후에만 변경 가능.
4. PII 항목은 `locked` 상태와 무관하게 항상 `[본인 직접 입력]`으로 렌더된다 (spec § 7 hard rule 그대로).

## API 경계

| 메소드·경로 | 변화 | 역할 |
|---|---|---|
| `POST /api/sessions` | 유지 | 세션 생성 |
| `POST /api/upload` | 유지 | 양식·자료 업로드 |
| `POST /api/sessions/{sid}/fill` | **신규** | 일괄 채우기 트리거. SSE로 진행 상황·preview 스트리밍 |
| `POST /api/sessions/{sid}/items/apply` | **신규** | body: `{item_id}` — `locked=True` |
| `POST /api/sessions/{sid}/items/unlock` | **신규** | body: `{item_id}` — `locked=False` |
| `PUT /api/sessions/{sid}/drafts` | **변경** | body: `{item_id, text}` — 텍스트 교체만, `locked` 안 건드림. 즉시 재렌더 제거. **`locked=True`인 draft를 수정하려 하면 409 Conflict** ("먼저 🔓 해제하세요") |
| `POST /api/sessions/{sid}/item-chat` | 유지 | 카드 내부 대화. body: `{item_id, message, history}`. `locked=True` 항목은 400 (잠금 해제 후 가능) |
| `GET /api/sessions/{sid}/output.hwpx` | **변경** | 호출 시점에 `[d for d in drafts if d.locked]`만 양식에 작성해 즉석 렌더 |
| `POST /api/chat` | **변경** | Router/Graph 우회. Solar 일반 QA 직접 호출. **SSE 폐지 → plain JSON 응답** `{reply: str}`. 단일 응답이라 스트리밍 가치 작음 |
| `GET /api/sessions/_debug/*` | 유지 | 진단용 |

### `item_id` 위치

`item_id`는 `Contents/section0.xml:p2` 같은 슬래시·콜론 포함 문자열이라 path segment에 들어갈 수 없다. 신규 엔드포인트도 모두 body에 `item_id`를 둔다 (`/items/apply`, `/items/unlock`). 기존 `/item-chat`이 같은 이유로 body 사용 중이라 일관성 있다.

### 의미 분리: `PUT /drafts` vs `POST /items/apply`

- `PUT /drafts` — 텍스트 교체만. `locked` 그대로 유지.
- `POST /items/apply` — `locked=True`로 set.
- `💬 대화`의 "🟢 본문만 추출해 적용"은 `PUT /drafts` + `POST /items/apply` 두 번 호출 — 사용자 의도가 명확한 시점이라 한 번에 잠금까지 진행.

### 제거되는 코드 경로

- `Router` 노드의 Solar 의도 분류 호출
- 그래프의 `rewrite_item` / `change_tone` / `add_material` / `start_fill` / `general_qa` / `upload_form` / `upload_material` 분기 — 그래프는 일괄 채우기 한 가지 직선 흐름만 유지
- `chat.py`의 `resume_with_answer` / `pending_question` 채팅 통합 흐름 — 단일 항목 대화는 `/item-chat`이 담당

## 상태 모델

### `DraftItem` 의미 재정의

```python
class DraftItem(BaseModel):
    item_id: str
    text: str
    citations: list[str]
    locked: bool = False        # ← NEW. 사용자가 ✓적용을 누르면 True
    # approved 필드 제거 — Verifier 자동 도장 모델 폐지
```

Renderer 필터 변경:

```diff
- if draft.approved:
+ if draft.locked:
```

Verifier는 의심스러운 draft에 `[검토 필요]` / `[확인 필요]` 마커를 prefix/suffix로 붙이는 일을 계속한다. 다만 더 이상 `approved`(이제는 `locked`)를 set하지 않는다.

### 액션별 상태 전이

| 액션 | 효과 | 잠금 항목에 대한 처리 |
|---|---|---|
| 일괄 채우기 (`POST /fill`) | drafts 새로 만듦. 모두 `locked=False` | — (전부 새로 만듦) |
| 텍스트 교체 (`PUT /drafts`) | `text`만 바꿈. `locked` 그대로 | 409 Conflict — 먼저 해제 |
| 적용 (`POST /items/apply`) | `locked=True`로 set | no-op (이미 True) |
| 해제 (`POST /items/unlock`) | `locked=False`로 set | — |
| 대화 (`POST /item-chat`) | DraftItem에 영향 없음. 응답만 받음 | 400 — 먼저 해제 |
| 다운로드 (`GET /output.hwpx`) | `[d for d in drafts if d.locked]`만 양식에 작성, 미적용은 양식 원본 그대로 | — |

### `GraphState` 정리

```python
class GraphState(BaseModel):
    session_id: Optional[str] = None
    form_doc: Optional[FormDoc] = None
    materials: MaterialBundle = MaterialBundle(docs=[])
    plans: list[ItemPlan] = []
    drafts: list[DraftItem] = []
    history: list[dict[str, str]] = []   # 일반 QA용 채팅 thread
    errors: list[str] = []
    # 제거: intent, user_message, pending_question, pending_answer
```

### Frontend 상태 단순화

- `applied_<item_id>` 로컬 플래그 **삭제** — `draft.locked`를 서버 단일 소스로
- `editing_<item_id>` / `chatting_<item_id>` 같은 순수 UI 플래그는 유지
- 액션 후 응답으로 받은 업데이트 `DraftItem`을 `st.session_state.drafts`의 해당 항목에 그대로 대입

## 그래프 변경

### Before

```
router → form_parser → material_ingestor → planner → generator → ask_question? → verifier → renderer → END
       ↘ general_qa_responder → END
       ↘ form_parser/material_ingestor만 → END
```

### After

```
form_parser → material_ingestor → planner → generator → verifier → END
```

`POST /api/sessions/{sid}/fill`만 이 그래프를 실행. 다른 모든 흐름은 그래프 우회.

### 제거되는 노드·코드

| 대상 | 처리 |
|---|---|
| `router` 노드 (`backend/app/graph/nodes/router.py`) | 삭제 (Solar 의도 분류 호출 사라짐) |
| `general_qa_responder` 인라인 노드 (`graph.py`) | 삭제. 동일 Solar 호출 로직을 `/api/chat` 핸들러로 이동 |
| `ask_question` 노드 (`backend/app/graph/nodes/question.py`) | 삭제 (V1에서 이미 unreachable한 데드 코드) |
| `resume_with_answer` 함수 | 삭제 (채팅으로 답변 이어받기 폐지) |
| 의도 분기 함수들 (`_route_intent`, `_after_form_parser`, ...) | 의도 검사 삭제, 단순 직선 흐름으로 |
| `Intent` Literal | `state.py`에서 삭제 |

### Renderer 노드의 강등

현재 `render_output`은 그래프 노드 + 일반 함수 두 곳에서 호출 가능. 새 흐름에선 그래프에서 빠지고 **순수 모듈 함수로만 존재**:

- 일괄 채우기 그래프의 끝은 `verifier`. Renderer 호출 안 함 (어차피 모든 draft가 `locked=False`라 무의미).
- `GET /output.hwpx`가 호출 시점에 `render_output(state, form_bytes)`를 직접 호출 (lazy).

`render_output` 함수 자체는 유지하되 필터를 `draft.approved` → `draft.locked`로 변경.

### Verifier의 역할

| 흐름 | Verifier 거치는가 |
|---|---|
| 일괄 채우기 (`POST /fill`) | 거침. 의심스러운 draft에 마커 prefix/suffix 부여 |
| ✏ 수정 (`PUT /drafts`) | 안 거침. 사용자 직접 입력 텍스트 |
| 💬 대화 → 적용 | 안 거침. 사용자가 대화에서 명시적으로 OK한 본문 |

### 단순화 효과

- 그래프 노드 9개 → **5개**
- Solar 호출 횟수 (일괄 채우기 1회): `1(Router) + 1(Planner) + N(Generator) + N(Verifier)` → `1(Planner) + N + N` (Router 호출 1회 절감)
- 일반 QA 호출당: `1(Router) + 1(QA)` → `1(QA)`

## 프론트엔드 변경

### 사이드바

```
🆕 새 세션
session: a1b2c3d4...
backend: http://localhost:8000 — ✅ modern
─────────────────
양식 (.hwpx)         [업로드 영역]
자료 (CV/계획서/...) [업로드 영역]
─────────────────
▶ 양식 자동 채우기 시작     ← NEW (양식 + 자료 ≥1 모두 업로드 시 활성화)
📥 출력 .hwpx 다운로드      ← lazy 렌더 (적용된 항목 ≥1일 때 활성화)
```

- `▶ 양식 자동 채우기 시작` → `POST /api/sessions/{sid}/fill` SSE. 진행 중 스피너 + 노드 진행 메시지. 끝나면 모든 draft 카드 등장.
- `📥 다운로드`는 `<a href>` 링크가 아니라 `httpx.get`을 통한 명시적 호출 → 받은 bytes를 `st.download_button`으로 노출.

### 메인 채팅 (역할 축소)

- `st.chat_input` 그대로. 백엔드는 `POST /api/chat` (일반 QA only).
- **삭제**: `_process_stream`에서 `form_parsed` / `preview` / `pending_question` / `intent` 처리.
- **삭제**: `pending_question` UI 박스.
- **추가**: 일반 QA 응답은 단일 텍스트로 받아 채팅에 표시.

### 항목 카드 (핵심 변경)

| 요소 | Before | After |
|---|---|---|
| 버튼 | ✓적용 / ✏수정 / 🔁다시 / 💬대화 (4) | ✓적용 / ✏수정 / 💬대화 (3), 잠기면 🔓해제만 |
| `applied_<item_id>` 로컬 플래그 | 사용 | **삭제** — `draft.locked` 단일 소스 |
| `apply_warn_<item_id>` (`[추가 정보 필요]` 적용 경고) | 유지 | 유지 |
| `editing_<item_id>` / `chatting_<item_id>` | 유지 | 유지 |
| ✏ 저장 (`PUT /drafts`) | `approved=True` 자동 set | 텍스트만 교체, 잠금 안 걸림 |
| 💬 대화 "🟢 본문만 추출해 적용" | `PUT /drafts`만 + 로컬 `applied_` 플래그 | `PUT /drafts` + `POST /items/apply` 두 번 |
| 🔁 다시 버튼 | 채팅 thread에 메시지 전송 | **삭제** (대화에서 "다시 써줘") |

### 액션 응답 처리

서버에서 받은 업데이트 `DraftItem`으로 로컬 `st.session_state.drafts` 항목 갱신:

```python
def _replace_draft(updated: dict) -> None:
    for i, d in enumerate(st.session_state.drafts):
        if d.get("item_id") == updated["item_id"]:
            st.session_state.drafts[i] = updated
            return
```

`POST /items/apply`, `POST /items/unlock`, `PUT /drafts` 모두 업데이트 `DraftItem`을 응답 body로 반환.

### "직접 작성이 필요한 항목" 박스

- **🔒 PII** — 그대로. Renderer가 `[본인 직접 입력]`으로 비움.
- **❓ 자료 부족 항목** — `[추가 정보 필요] ...` prefix가 있는 미적용 draft들.
- **➕ 미적용 항목** — 적용된 항목 수 / 전체 항목 수 진행률 표시.

## 마이그레이션 / 호환성

### 깨지는 변경 (한 번에 적용)

세션이 메모리뿐이고 backend 재시작 시 어차피 새 세션이라 phased 롤아웃 비용이 이득보다 크다. 새 PR 한 번에 전부:

| 항목 | 변화 | 영향 |
|---|---|---|
| `DraftItem.approved` | 제거, `locked` 추가 | SSE preview 소비자(streamlit) 수정 필요 |
| `POST /api/chat` SSE 이벤트 셋 | `intent`/`form_parsed`/`preview`/`pending_question` 제거 | 옛 streamlit이 새 백엔드를 보면 일반 QA만 받음 (정상) |
| `Router` / `ask_question` / `resume_with_answer` | 모듈 삭제 | 외부에서 import 시 ImportError — 프로젝트 내부 사용뿐이라 안전 |
| 그래프 노드 셋 | `general_qa_responder` 삭제, 분기 제거 | `tools/draw_graph.py`로 다이어그램 재생성 필요 |
| `Intent` Literal | 삭제 | `state.py` 동시 수정 |

배포 후 서버 재시작 = 모든 사용자가 새 흐름.

### 작업 순서 (한 PR 안에서)

1. State model 변경 (`DraftItem.locked`, `GraphState` 슬림화, `Intent` 삭제)
2. 그래프 단순화 (`router`/`question`/`general_qa_responder` 삭제, 단일 직선 흐름, conditional edge 제거)
3. 백엔드 API: `/fill`, `/items/apply`, `/items/unlock` 신규, `PUT /drafts` 의미 변경, `/output.hwpx` lazy 렌더, `/api/chat` QA-only로 교체
4. Frontend: 사이드바 시작 버튼, 카드 3버튼+해제, 로컬 `applied_` 플래그 제거, 다운로드 lazy 흐름, 🔁 버튼 삭제
5. `tools/draw_graph.py`로 `docs/graph.mmd` / `docs/graph.png` 재생성

## 테스트

### 삭제

- `tests/unit/test_node_router.py` (Router 사라짐 — 존재한다면)
- `tests/unit/test_node_question.py` (Question 사라짐 — 존재한다면)
- `test_api_chat.py`의 의도 분기 케이스 (`start_fill`/`rewrite_item`/`change_tone`/`add_material`)
- `pending_question` resume 통합 케이스

### 수정

- `test_hwpx_renderer.py` — `approved=True` 픽스처 → `locked=True`
- `test_node_verifier.py` — Verifier가 더 이상 `approved`(이제는 `locked`)를 set하지 않음 검증
- `test_api_chat.py` — `/api/chat`이 일반 QA SSE만 반환 검증

### 신규

- `test_api_fill.py` — `POST /fill` SSE 이벤트(`node_started`, `form_parsed`, `preview`, `done`) 검증, 모든 draft가 `locked=False`로 끝남
- `test_api_items_apply.py` — apply→unlock 토글, PII 항목 차단(400), 존재하지 않는 item_id(404)
- `test_api_drafts.py` — `PUT /drafts`가 `text`만 바꾸고 `locked`는 안 건드림
- `test_api_output.py` — `GET /output.hwpx`가 호출 시점에 lazy 렌더, 미적용 항목은 양식 원본 그대로

## KPI 영향 (spec § 8)

| KPI | 영향 |
|---|---|
| K1 form-blank F1 ≥ 0.85 | 변경 없음 (FormParser/Planner 그대로) |
| **K2 Router intent accuracy ≥ 0.90** | **의미 소실** — Router 자체가 사라짐. Open Issue |
| K3 auto-fill rate ≥ 0.60 | 재해석 필요: "Generator가 텍스트 생성한 비율" → "사용자가 ✓적용까지 누른 비율" |
| K4 Verifier first-pass ≥ 0.75 | 변경 없음 |
| K5 PII leak count = 0 | 변경 없음. 강화됨 — 적용 전 검토 흐름 추가 |
| K6 first-preview latency ≤ 30s p50 | 약간 빨라짐 (Router Solar 호출 1회 절감) |

## Open Issues

1. **K2 KPI 정의 변경** — 스펙 §8과 충돌. PM/스펙 owner와 논의 필요.
2. **K3 KPI 재해석** — "auto-fill rate" 분모를 "Generator 도달 항목" / 분자를 "사용자 ✓적용 항목" 으로 바꿀지 결정 필요.
3. **일괄 채우기 진행률 스트리밍** — 현재 Generator는 모든 항목을 한 번에 만든 뒤 반환. 항목별 카드가 점진적으로 채워지는 UX는 더 좋지만, Generator를 itemwise yield로 바꿔야 해서 V1 스코프 밖일 수 있음. 일단 "노드 진행 메시지 + 끝나면 한꺼번에 표시"로 시작.
4. **Verifier 마커가 prefix로 붙은 draft를 사용자가 ✓적용했을 때** — 마커가 그대로 출력에 들어가는데 OK인가? (일관성상 그대로 두는 게 자연스러움 — 사용자가 "괜찮다"고 본 셈)
5. **마이그레이션 시점 인-플라이트 세션** — 기존 세션이 메모리에 있는데 backend가 새 코드로 재시작되면 그 세션은 자연 폐기됨. 사용자에게 "새 세션 시작" 안내 필요할 수 있음 (sidebar 캡션에 이미 "백엔드 재시작 시 세션 초기화" 문구 있어 별도 작업 불필요).
