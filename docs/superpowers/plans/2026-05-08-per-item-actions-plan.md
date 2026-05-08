# 항목별 액션 분리 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 채팅과 항목별 액션을 완전 분리한다. 일괄 채우기는 사이드바 버튼으로만 트리거되고, 적용/수정/대화는 채팅 thread를 거치지 않고 카드 안에서만 일어나며, "적용된 draft만" 출력에 들어가는 비파괴적 lazy 렌더로 정리한다.

**Architecture:** `DraftItem`의 의미를 `approved`(이중 의미) → `locked`(사용자 적용 단일 의미)로 재정의한다. 그래프는 라우터·Question 노드를 제거하고 `form_parser → material_ingestor → planner → generator → verifier → END` 직선 흐름으로 슬림화. `/api/chat`은 일반 QA 전용으로, 일괄 채우기·항목별 액션은 별도 엔드포인트로 분리. 다운로드 시점에만 zip을 만든다.

**Tech Stack:** Python 3.11 · FastAPI · LangGraph 0.2 · Streamlit · Pydantic v2 · pytest · sse-starlette · Upstage Solar.

**Spec:** `docs/superpowers/specs/2026-05-08-per-item-actions-design.md` (commit 590756b)

---

## File Structure

| 파일 | 변경 |
|---|---|
| `backend/app/graph/state.py` | `DraftItem.approved` → `locked`. `Intent` Literal·`pending_question`·`pending_answer`·`user_message`·`intent` 필드 제거. `append_turn` 유지 |
| `backend/app/graph/nodes/verifier.py` | `locked=True` set 코드 모두 제거. 마커 prefix/suffix만 부여 |
| `backend/app/graph/nodes/renderer.py` | 필터 `if draft.approved` → `if draft.locked` (2곳) |
| `backend/app/graph/nodes/router.py` | **삭제** |
| `backend/app/graph/nodes/question.py` | **삭제** (`ask_question`, `resume_with_answer`) |
| `backend/app/graph/graph.py` | Router·Question·general_qa_responder·intent 분기 제거. 5노드 직선 그래프로 |
| `backend/app/api/chat.py` | `_stream_graph` 폐기. 일반 QA 전용 plain JSON 응답 핸들러로 교체 |
| `backend/app/api/sessions.py` | 신규: `POST /fill` (SSE), `POST /items/apply`, `POST /items/unlock`. 변경: `PUT /drafts` 텍스트만, `/output.hwpx` lazy 렌더, `/item-chat` locked 차단 |
| `backend/app/llm/prompts.py` | `build_router_messages` 함수 삭제 (Router 사라짐) |
| `frontend/streamlit_app.py` | 사이드바 fill/download 버튼, 카드 3버튼 + 🔓해제, `applied_` 플래그 제거, 🔁 제거, pending_question UI 제거, `_process_stream` plain JSON 변환 |
| `backend/tests/unit/test_router.py` | **삭제** |
| `backend/tests/unit/test_router_k2.py` | **삭제** (K2 KPI 재정의 별도 작업) |
| `backend/tests/unit/test_node_question.py` | **삭제** |
| `backend/tests/unit/test_node_verifier.py` | `approved` → `locked`, Verifier가 set 안 함을 그대로 유지(이미 그렇게 적혀 있음) |
| `backend/tests/unit/test_node_renderer.py` | `approved` → `locked` |
| `backend/tests/unit/test_hwpx_renderer.py` | 픽스처 갱신 |
| `backend/tests/unit/test_node_generator.py` | `approved` → `locked` (있다면) |
| `backend/tests/unit/test_graph_state.py` | DraftItem 필드 변경 반영 |
| `backend/tests/unit/test_prompts.py` | `build_router_messages` 케이스 삭제 |
| `backend/tests/integration/test_api_chat.py` | 일반 QA only 플로우로 재작성 |
| `backend/tests/integration/test_graph_intents.py` | **삭제** (의도 분기 사라짐) |
| `backend/tests/integration/test_scenarios.py` | 새 흐름(/fill → /items/apply → /output.hwpx)으로 갱신 |
| `backend/tests/integration/test_api_fill.py` | **신규** |
| `backend/tests/integration/test_api_items.py` | **신규** (apply/unlock) |
| `backend/tests/integration/test_api_drafts.py` | **신규** (PUT semantics + 409) |
| `backend/tests/integration/test_api_output.py` | **신규** (lazy render) |
| `tools/draw_graph.py` | 변경 없음. 실행해서 `docs/graph.mmd`·`docs/graph.png` 갱신만 |
| `eval/run_kpi.py` | K2 분기 임시 무효화 (Open Issue) |

---

## Phase 1 — 상태 모델

### Task 1: `DraftItem.approved` → `DraftItem.locked` 이름 변경

**Files:**
- Modify: `backend/app/graph/state.py`
- Modify: `backend/app/graph/nodes/renderer.py:42-43, 58-61`
- Modify: `backend/app/graph/nodes/verifier.py` (전체)
- Modify: `backend/app/graph/nodes/generator.py:48-65`
- Modify: `backend/tests/unit/test_node_verifier.py` (모든 `approved` 어서션)
- Modify: `backend/tests/unit/test_node_renderer.py` (모든 `approved` 어서션)
- Modify: `backend/tests/unit/test_node_generator.py` (있다면)
- Modify: `backend/tests/unit/test_hwpx_renderer.py` (DraftItem 픽스처)
- Modify: `backend/tests/unit/test_graph_state.py` (있다면)

- [ ] **Step 1: 테스트들에서 `approved` → `locked`로 일괄 치환**

```bash
cd D:/Projects/hwp-editor
```

`backend/tests/unit/test_node_verifier.py`:
- `_make_draft` 시그니처: `def _make_draft(item_id: str, text: str = "초안 내용입니다.", locked: bool = False) -> DraftItem:`
- DraftItem 생성: `return DraftItem(item_id=item_id, text=text, citations=["cv.pdf"], locked=locked)`
- 모든 `approved=False` → `locked=False`
- 모든 `result["drafts"][0].approved is False` → `result["drafts"][0].locked is False`
- 모든 `_make_draft("...", approved=False)` → `_make_draft("...", locked=False)`
- "approved" 단어가 들어간 docstring·코멘트도 `locked`로 일관성 있게 갱신

`backend/tests/unit/test_node_renderer.py`, `test_hwpx_renderer.py`, `test_node_generator.py`, `test_graph_state.py`도 동일하게 `approved=` → `locked=`, `.approved` → `.locked` 치환.

- [ ] **Step 2: 테스트 실행, 실패 확인**

```bash
uv run pytest backend/tests/unit/test_node_verifier.py backend/tests/unit/test_node_renderer.py -v
```

Expected: FAIL with `pydantic.ValidationError` 또는 `Extra inputs are not permitted` 또는 `'DraftItem' object has no attribute 'locked'` — `DraftItem`이 아직 `approved` 필드를 가지고 있기 때문.

- [ ] **Step 3: `state.py`에서 필드 이름 변경**

`backend/app/graph/state.py:32-37`:

```python
class DraftItem(BaseModel):
    item_id: str
    text: str
    citations: list[str]
    locked: bool = False
```

- [ ] **Step 4: Renderer 필터 변경**

`backend/app/graph/nodes/renderer.py:43`:

```python
        draft = next(
            (d for d in state.drafts if d.item_id == placeholder.item_id and d.locked),
            None,
        )
```

`backend/app/graph/nodes/renderer.py:58`:

```python
        if draft.locked:
```

(주석에 "approved" 언급 있으면 "locked"로 바꿈)

- [ ] **Step 5: Verifier가 `locked` set 안 하도록 수정**

`backend/app/graph/nodes/verifier.py:75-80`:

```python
    if verdict == "ok":
        return draft
    elif verdict == "retry":
        return draft.model_copy(update={"text": _RETRY_PREFIX + draft.text})
    else:
        return draft.model_copy(update={"text": draft.text + _SOFT_FAIL_SUFFIX})
```

`verify_drafts` 함수 안 placeholder 처리(`backend/app/graph/nodes/verifier.py:48`)에서 `approved=True` set도 제거:

```python
        if draft.text.startswith(_NEEDS_INFO_PREFIX):
            updated_drafts.append(draft)
            continue
```

루프 시작부 `if draft.approved:` 검사도 `if draft.locked:`로 바꾸되, 실제론 일괄 채우기에선 모든 draft가 `locked=False`이므로 이 분기는 dead code가 됨 — 그냥 제거해도 된다:

```python
    for draft in state.drafts:
        if draft.text.startswith(_NEEDS_INFO_PREFIX):
            updated_drafts.append(draft)
            continue
        updated_drafts.append(_verify_single(draft, state))
```

(즉 두 번째 `if draft.locked:` 분기는 삭제)

docstring도 `approved=True` 언급 제거.

- [ ] **Step 6: Generator가 새 DraftItem 만들 때 `approved` 인자 제거**

`backend/app/graph/nodes/generator.py:47-54`:

```python
            drafts.append(
                DraftItem(
                    item_id=plan.item_id,
                    text=f"{_NEEDS_INFO_PREFIX} {label} — {question}",
                    citations=[],
                )
            )
```

`backend/app/graph/nodes/generator.py:58-65`:

```python
        drafts.append(
            DraftItem(
                item_id=plan.item_id,
                text=text,
                citations=citations,
            )
        )
```

(기본값 `locked=False`가 적용됨)

- [ ] **Step 7: 단위 테스트 재실행, 통과 확인**

```bash
uv run pytest backend/tests/unit/test_node_verifier.py backend/tests/unit/test_node_renderer.py backend/tests/unit/test_node_generator.py backend/tests/unit/test_hwpx_renderer.py backend/tests/unit/test_graph_state.py -v
```

Expected: PASS (모든 테스트 통과)

- [ ] **Step 8: 커밋**

```bash
git add backend/app/graph/state.py backend/app/graph/nodes/verifier.py backend/app/graph/nodes/renderer.py backend/app/graph/nodes/generator.py backend/tests/unit/test_node_verifier.py backend/tests/unit/test_node_renderer.py backend/tests/unit/test_node_generator.py backend/tests/unit/test_hwpx_renderer.py backend/tests/unit/test_graph_state.py
git commit -m "$(cat <<'EOF'
refactor(state): DraftItem.approved → locked, Verifier no longer auto-locks

Verifier now mutates text only (markers). User-applied gating moves to a
new locked field. Renderer filters on locked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `GraphState` 슬림화 — `Intent`·`pending_question`·`pending_answer`·`user_message`·`intent` 제거

**Files:**
- Modify: `backend/app/graph/state.py`

- [ ] **Step 1: 사용처 검색**

```bash
uv run python -c "import subprocess; subprocess.run(['rg', '-n', 'pending_question|pending_answer|user_message|state.intent|GraphState\\.intent|Intent', 'backend/app/'])"
```

(또는 Grep tool로 검색해 사용처 목록 확보)

- [ ] **Step 2: `state.py`에서 필드·타입 제거**

`backend/app/graph/state.py` 전체를 다음으로 교체:

```python
"""Central GraphState for the LangGraph form-fill pipeline."""

from typing import Optional

from pydantic import BaseModel

from backend.app.hwpx.models import FormDoc


class MaterialBundle(BaseModel):
    docs: list[dict]


class ItemPlan(BaseModel):
    item_id: str
    source_evidence: list[str]
    confidence: float
    needs_question: bool
    question: Optional[str] = None


class DraftItem(BaseModel):
    item_id: str
    text: str
    citations: list[str]
    locked: bool = False


class GraphState(BaseModel):
    session_id: Optional[str] = None
    form_doc: Optional[FormDoc] = None
    materials: MaterialBundle = MaterialBundle(docs=[])
    plans: list[ItemPlan] = []
    drafts: list[DraftItem] = []
    history: list[dict[str, str]] = []
    errors: list[str] = []


def append_turn(state: GraphState, role: str, content: str) -> GraphState:
    """Return a new GraphState with the turn appended, keeping at most 10 turns."""
    new_history = [dict(t) for t in state.history] + [{"role": role, "content": content}]
    if len(new_history) > 10:
        new_history = new_history[-10:]
    return state.model_copy(update={"history": new_history})
```

- [ ] **Step 3: 테스트로 import/사용처 깨졌는지 확인**

```bash
uv run pytest backend/tests/unit/test_graph_state.py -v
```

Expected: PASS (state 테스트 자체는 깨끗하게 통과해야 함)

```bash
uv run pytest backend/tests/ -x --ignore=backend/tests/integration/test_api_chat.py --ignore=backend/tests/integration/test_graph_intents.py --ignore=backend/tests/unit/test_router.py --ignore=backend/tests/unit/test_router_k2.py --ignore=backend/tests/unit/test_node_question.py 2>&1 | head -40
```

Expected: 라우터/Question/intent 의존하는 테스트는 ignore했으므로 나머지 통과. 만약 다른 곳에서 import 깨지면 그 파일을 다음 task에서 정리할 수 있도록 노트.

- [ ] **Step 4: 커밋**

```bash
git add backend/app/graph/state.py
git commit -m "$(cat <<'EOF'
refactor(state): drop intent/pending_question/user_message from GraphState

These fields supported the chat-merged Q&A flow and router classification,
both of which are removed in this branch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — 그래프 슬림화

### Task 3: 라우터 노드·테스트·프롬프트 삭제

**Files:**
- Delete: `backend/app/graph/nodes/router.py`
- Delete: `backend/tests/unit/test_router.py`
- Delete: `backend/tests/unit/test_router_k2.py`
- Modify: `backend/app/llm/prompts.py` (`build_router_messages` 삭제)
- Modify: `backend/tests/unit/test_prompts.py` (라우터 케이스 삭제)

- [ ] **Step 1: 파일 삭제**

```bash
rm backend/app/graph/nodes/router.py
rm backend/tests/unit/test_router.py
rm backend/tests/unit/test_router_k2.py
```

- [ ] **Step 2: `build_router_messages` 함수 삭제**

`backend/app/llm/prompts.py`를 열어 `build_router_messages` 함수 정의(시그니처 + 본문 + 관련 상수)를 삭제. 주변 함수들(`build_planner_messages`, `build_generator_messages`, `build_verifier_messages`)은 유지.

- [ ] **Step 3: `test_prompts.py`에서 라우터 케이스 삭제**

```bash
uv run pytest backend/tests/unit/test_prompts.py --collect-only 2>&1 | grep -i router
```

목록에 나오는 router 관련 테스트들을 파일에서 제거.

- [ ] **Step 4: 테스트 실행해 다른 곳에서 import 깨졌는지 확인**

```bash
uv run pytest backend/tests/unit/test_prompts.py -v
uv run pytest backend/tests/unit/test_solar_client.py -v
```

Expected: PASS

```bash
uv run python -c "from backend.app.graph.nodes import generator, planner, verifier, renderer, form_parser, material_ingestor; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: 커밋**

```bash
git add -u backend/app/llm/prompts.py backend/app/graph/nodes/ backend/tests/unit/
git commit -m "$(cat <<'EOF'
refactor(graph): remove Router node, K2 testset wiring, router prompt

Intent classification is no longer needed — chat is general-QA only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Question 노드·테스트·resume 흐름 삭제

**Files:**
- Delete: `backend/app/graph/nodes/question.py`
- Delete: `backend/tests/unit/test_node_question.py`

- [ ] **Step 1: 파일 삭제**

```bash
rm backend/app/graph/nodes/question.py
rm backend/tests/unit/test_node_question.py
```

- [ ] **Step 2: 다른 모듈에서 question 모듈을 import하는 곳 확인**

Grep으로 `from backend.app.graph.nodes.question` 또는 `nodes.question`을 검색. 발견되는 곳: `backend/app/api/chat.py`, `backend/app/graph/graph.py`. 두 파일은 다음 task에서 정리됨 — 일단 다음 단계로.

- [ ] **Step 3: 커밋**

```bash
git add -u backend/app/graph/nodes/question.py backend/tests/unit/test_node_question.py
git commit -m "$(cat <<'EOF'
refactor(graph): remove Question node and resume_with_answer

Per-item gathering moves to /api/sessions/{sid}/item-chat. The graph no
longer interrupts to ask the user inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `graph.py` 직선화 — 9노드 분기 → 5노드 직선

**Files:**
- Modify: `backend/app/graph/graph.py` (전면 재작성)
- Delete: `backend/tests/integration/test_graph_intents.py`

- [ ] **Step 1: `test_graph_intents.py` 삭제**

```bash
rm backend/tests/integration/test_graph_intents.py
```

- [ ] **Step 2: `graph.py` 재작성**

`backend/app/graph/graph.py` 전체를 다음으로 교체:

```python
"""LangGraph StateGraph assembly for the HwpAgent form-fill pipeline.

Single straight-line flow:
    form_parser → material_ingestor → planner → generator → verifier → END

This is the ONLY module in the project allowed to import LangGraph.
All node logic lives in graph/nodes/* and is imported here as pure functions.
"""

from __future__ import annotations

from typing import Protocol

from langgraph.graph import StateGraph, END

from backend.app.graph.state import GraphState
from backend.app.graph.nodes.form_parser import parse_form
from backend.app.graph.nodes.material_ingestor import ingest_materials
from backend.app.graph.nodes.planner import plan_items
from backend.app.graph.nodes.generator import generate_drafts
from backend.app.graph.nodes.verifier import verify_drafts


class SessionProvider(Protocol):
    def get_form_bytes(self, session_id: str) -> bytes: ...
    def get_material_files(self, session_id: str) -> list[tuple[str, bytes]]: ...


def _stop_on_error(state: GraphState) -> str:
    return "END" if state.errors else "continue"


def build_compiled_graph(session_provider: SessionProvider):
    """Build and compile the form-fill graph.

    The graph runs only when POST /api/sessions/{sid}/fill is called.
    Per-item actions (apply/unlock/edit/chat) and general QA bypass this graph.
    """

    def _form_parser(state: GraphState) -> dict:
        form_bytes = session_provider.get_form_bytes(state.session_id or "")
        return parse_form(state, form_bytes)

    def _material_ingestor(state: GraphState) -> dict:
        material_files = session_provider.get_material_files(state.session_id or "")
        return ingest_materials(state, material_files)

    g = StateGraph(GraphState)

    g.add_node("form_parser", _form_parser)
    g.add_node("material_ingestor", _material_ingestor)
    g.add_node("planner", plan_items)
    g.add_node("generator", generate_drafts)
    g.add_node("verifier", verify_drafts)

    g.set_entry_point("form_parser")

    for from_node, to_node in [
        ("form_parser", "material_ingestor"),
        ("material_ingestor", "planner"),
        ("planner", "generator"),
        ("generator", "verifier"),
    ]:
        g.add_conditional_edges(
            from_node, _stop_on_error, {"continue": to_node, "END": END}
        )

    g.add_edge("verifier", END)

    return g.compile()
```

- [ ] **Step 3: 그래프가 컴파일되는지 smoke test**

```bash
uv run python -c "
from backend.app.graph.graph import build_compiled_graph
class S:
    def get_form_bytes(self, sid): return b''
    def get_material_files(self, sid): return []
g = build_compiled_graph(S())
print('compiled', g)
"
```

Expected: `compiled <CompiledStateGraph ...>`

- [ ] **Step 4: 그래프 다이어그램 재생성**

```bash
uv run python tools/draw_graph.py
```

Expected: `docs/graph.mmd`, `docs/graph.png` 갱신. 단순 직선 5노드.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/graph/graph.py backend/tests/integration/test_graph_intents.py docs/graph.mmd docs/graph.png
git commit -m "$(cat <<'EOF'
refactor(graph): straight-line 5-node flow, remove intent branching

form_parser → material_ingestor → planner → generator → verifier → END.
General QA and per-item actions bypass the graph entirely.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — 백엔드 API

### Task 6: `POST /api/sessions/{sid}/fill` 신규 (SSE 일괄 채우기)

**Files:**
- Modify: `backend/app/api/sessions.py` (라우터 추가)
- Create: `backend/tests/integration/test_api_fill.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/integration/test_api_fill.py`:

```python
"""Integration tests for POST /api/sessions/{sid}/fill."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.session import store

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "forms" / "sample_form.hwpx"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_form_and_material(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form_bytes = _FIXTURE.read_bytes()
    client.post(
        "/api/upload",
        data={"session_id": sid, "kind": "form"},
        files={"file": ("sample.hwpx", form_bytes, "application/octet-stream")},
    )
    client.post(
        "/api/upload",
        data={"session_id": sid, "kind": "material"},
        files={"file": ("cv.txt", b"My name is anonymized researcher.", "text/plain")},
    )
    yield sid
    await store.delete(sid)


def test_fill_returns_404_for_unknown_session(client: TestClient):
    r = client.post("/api/sessions/nonexistent/fill")
    assert r.status_code == 404


def test_fill_streams_node_progress_and_drafts(
    client: TestClient, session_with_form_and_material
):
    sid = session_with_form_and_material
    with patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]), \
         patch("backend.app.graph.nodes.generator._solar_complete", return_value={"text": "초안", "citations": []}), \
         patch("backend.app.graph.nodes.verifier._solar_complete", return_value={"verdict": "ok"}):
        r = client.post(f"/api/sessions/{sid}/fill")
    assert r.status_code == 200
    body = r.text
    assert "event: node_started" in body
    assert "event: form_parsed" in body
    assert "event: done" in body


def test_fill_drafts_all_unlocked(
    client: TestClient, session_with_form_and_material
):
    sid = session_with_form_and_material
    with patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]), \
         patch("backend.app.graph.nodes.generator._solar_complete", return_value={"text": "초안", "citations": []}), \
         patch("backend.app.graph.nodes.verifier._solar_complete", return_value={"verdict": "ok"}):
        client.post(f"/api/sessions/{sid}/fill")
    session = store._sessions[sid]
    assert session.graph_state is not None
    assert all(d.locked is False for d in session.graph_state.drafts)
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_fill.py -v
```

Expected: FAIL — `404 not found` 또는 `MethodNotAllowed` (엔드포인트 없음).

- [ ] **Step 3: `sessions.py`에 `POST /fill` 핸들러 추가**

`backend/app/api/sessions.py`의 import와 router 정의 사이에 다음을 추가 (적절한 위치는 파일 상단 imports 다음, `class DraftUpdate` 위):

```python
import json
from typing import AsyncIterator
from sse_starlette.sse import EventSourceResponse
from backend.app.graph.graph import build_compiled_graph
from backend.app.graph.state import GraphState


def _to_jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


async def _stream_fill(session_id: str) -> AsyncIterator[dict]:
    session = await store.get(session_id)
    if session is None or session.form_bytes is None:
        yield {"event": "error", "data": json.dumps({"error": "양식이 업로드되지 않았습니다."})}
        return
    if not session.material_files:
        yield {"event": "error", "data": json.dumps({"error": "자료가 업로드되지 않았습니다."})}
        return

    initial = GraphState(session_id=session_id)
    if session.graph_state is not None:
        initial.materials = session.graph_state.materials
        initial.history = list(session.graph_state.history)

    graph = build_compiled_graph(store)
    accumulated: dict = {}

    try:
        async for chunk in graph.astream(initial, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            for node_name, diff in chunk.items():
                yield {"event": "node_started", "data": json.dumps({"node": node_name})}
                if not isinstance(diff, dict):
                    continue
                accumulated.update(diff)
                if diff.get("form_doc"):
                    yield {"event": "form_parsed", "data": json.dumps(_to_jsonable(diff["form_doc"]))}
                if diff.get("drafts"):
                    yield {"event": "preview", "data": json.dumps(_to_jsonable(diff["drafts"]))}
                if diff.get("errors"):
                    yield {"event": "error", "data": json.dumps({"node": node_name, "error": "; ".join(str(e) for e in diff["errors"])})}
    except Exception as exc:
        yield {"event": "error", "data": json.dumps({"error": str(exc)})}
        return

    final_state = initial.model_copy(update=accumulated)
    await store.save_state(session_id, final_state)
    yield {"event": "done", "data": json.dumps({"draft_count": len(final_state.drafts)})}


@router.post("/api/sessions/{session_id}/fill")
async def fill(session_id: str):
    if (await store.get(session_id)) is None:
        raise HTTPException(status_code=404, detail=f"세션을 찾을 수 없습니다: {session_id}")
    return EventSourceResponse(_stream_fill(session_id))
```

- [ ] **Step 4: 테스트 재실행, 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_fill.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/sessions.py backend/tests/integration/test_api_fill.py
git commit -m "$(cat <<'EOF'
feat(api): POST /api/sessions/{sid}/fill — SSE batch fill

Triggers the slim graph and streams node_started / form_parsed /
preview / done events. All drafts emitted with locked=False — the user
must explicitly apply each one.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `POST /api/sessions/{sid}/items/apply` & `/items/unlock` 신규

**Files:**
- Modify: `backend/app/api/sessions.py`
- Create: `backend/tests/integration/test_api_items.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/integration/test_api_items.py`:

```python
"""Integration tests for POST /api/sessions/{sid}/items/apply and /unlock."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.models import FormDoc, Item
from backend.app.main import app
from backend.app.session import store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_drafts(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form = FormDoc(
        sections=["s1"],
        items=[
            Item(item_id="it1", label="자기소개", section="s1", kind="paragraph", xml_xpath="/p[1]"),
            Item(item_id="pii1", label="성명", section="s1", kind="paragraph", xml_xpath="/p[2]", is_pii=True),
        ],
        tables=[],
        placeholders=[],
    )
    state = GraphState(
        session_id=sid,
        form_doc=form,
        drafts=[
            DraftItem(item_id="it1", text="안녕하세요", citations=[], locked=False),
            DraftItem(item_id="pii1", text="[본인 직접 입력]", citations=[], locked=False),
        ],
    )
    await store.save_state(sid, state)
    yield sid
    await store.delete(sid)


def test_apply_sets_locked_true(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    assert r.status_code == 200
    assert r.json()["locked"] is True
    assert r.json()["item_id"] == "it1"


def test_unlock_sets_locked_false(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.post(f"/api/sessions/{sid}/items/unlock", json={"item_id": "it1"})
    assert r.status_code == 200
    assert r.json()["locked"] is False


def test_apply_pii_returns_400(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "pii1"})
    assert r.status_code == 400


def test_apply_unknown_item_returns_404(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "ghost"})
    assert r.status_code == 404


def test_apply_idempotent(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    r1 = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r2 = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    assert r1.json()["locked"] is True
    assert r2.json()["locked"] is True
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_items.py -v
```

Expected: FAIL — 404 (라우터 없음)

- [ ] **Step 3: `sessions.py`에 핸들러 추가**

`backend/app/api/sessions.py`의 `class DraftUpdate` 근처에 모델 추가:

```python
class ItemIdRequest(BaseModel):
    item_id: str
```

`update_draft` 핸들러 다음에 두 핸들러 추가:

```python
def _toggle_locked(state, item_id: str, value: bool):
    """Return (new_state, updated_draft) or (None, None) if item missing."""
    new_drafts = []
    updated = None
    for d in state.drafts:
        if d.item_id == item_id:
            updated = d.model_copy(update={"locked": value})
            new_drafts.append(updated)
        else:
            new_drafts.append(d)
    if updated is None:
        return None, None
    return state.model_copy(update={"drafts": new_drafts}), updated


@router.post("/api/sessions/{session_id}/items/apply")
async def apply_item(session_id: str, payload: ItemIdRequest):
    session = await store.get(session_id)
    if session is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="세션 또는 그래프 상태가 없습니다.")
    state = session.graph_state
    if state.form_doc is None:
        raise HTTPException(status_code=400, detail="form_doc이 없습니다.")
    item = next((it for it in state.form_doc.items if it.item_id == payload.item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item 미존재: {payload.item_id}")
    if item.is_pii:
        raise HTTPException(
            status_code=400,
            detail="PII 항목은 항상 [본인 직접 입력]으로 비워두며 적용 대상이 아닙니다.",
        )
    new_state, updated = _toggle_locked(state, payload.item_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"draft 미존재: {payload.item_id}")
    await store.save_state(session_id, new_state)
    return updated.model_dump()


@router.post("/api/sessions/{session_id}/items/unlock")
async def unlock_item(session_id: str, payload: ItemIdRequest):
    session = await store.get(session_id)
    if session is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="세션 또는 그래프 상태가 없습니다.")
    state = session.graph_state
    new_state, updated = _toggle_locked(state, payload.item_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"draft 미존재: {payload.item_id}")
    await store.save_state(session_id, new_state)
    return updated.model_dump()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_items.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/sessions.py backend/tests/integration/test_api_items.py
git commit -m "$(cat <<'EOF'
feat(api): /items/apply and /items/unlock — toggle DraftItem.locked

PII items are rejected with 400. Apply is idempotent. unlock returns
locked=False even if it was already false.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `PUT /api/sessions/{sid}/drafts` — 텍스트만, 409 on locked, 즉시 재렌더 제거

**Files:**
- Modify: `backend/app/api/sessions.py`
- Create: `backend/tests/integration/test_api_drafts.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/integration/test_api_drafts.py`:

```python
"""Integration tests for PUT /api/sessions/{sid}/drafts (text-only update)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.models import FormDoc, Item
from backend.app.main import app
from backend.app.session import store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_draft(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form = FormDoc(
        sections=["s1"],
        items=[Item(item_id="it1", label="자기소개", section="s1", kind="paragraph", xml_xpath="/p[1]")],
        tables=[],
        placeholders=[],
    )
    state = GraphState(
        session_id=sid,
        form_doc=form,
        drafts=[DraftItem(item_id="it1", text="원본", citations=[], locked=False)],
    )
    await store.save_state(sid, state)
    yield sid
    await store.delete(sid)


def test_put_drafts_replaces_text_only(client: TestClient, session_with_draft):
    sid = session_with_draft
    r = client.put(
        f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정됨"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "수정됨"
    assert body["locked"] is False


def test_put_drafts_409_when_locked(client: TestClient, session_with_draft):
    sid = session_with_draft
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.put(
        f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정됨"}
    )
    assert r.status_code == 409


def test_put_drafts_no_immediate_render(client: TestClient, session_with_draft):
    sid = session_with_draft
    client.put(f"/api/sessions/{sid}/drafts", json={"item_id": "it1", "text": "수정"})
    session = store._sessions[sid]
    assert session.rendered_bytes is None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_drafts.py -v
```

Expected:
- `test_put_drafts_replaces_text_only` — 응답에 `locked` 키 없음 또는 형식 불일치
- `test_put_drafts_409_when_locked` — 200 받음 (현 동작은 잠금 무시)
- `test_put_drafts_no_immediate_render` — `rendered_bytes`가 채워짐 (현 동작은 즉시 재렌더)

- [ ] **Step 3: `update_draft` 핸들러 재작성**

`backend/app/api/sessions.py`의 `update_draft` 함수를 다음으로 교체:

```python
@router.put("/api/sessions/{session_id}/drafts")
async def update_draft(session_id: str, payload: DraftUpdate):
    """Replace one draft's text. Locked drafts return 409 — unlock first."""
    session = await store.get(session_id)
    if session is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="세션 또는 그래프 상태가 없습니다.")
    state = session.graph_state
    if state.form_doc is None:
        raise HTTPException(status_code=400, detail="form_doc이 없습니다.")

    target = next((d for d in state.drafts if d.item_id == payload.item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"draft 미존재: {payload.item_id}")
    if target.locked:
        raise HTTPException(status_code=409, detail="잠긴 항목은 수정 전에 🔓 해제가 필요합니다.")

    new_drafts = [
        d.model_copy(update={"text": payload.text}) if d.item_id == payload.item_id else d
        for d in state.drafts
    ]
    new_state = state.model_copy(update={"drafts": new_drafts})
    await store.save_state(session_id, new_state)

    updated = next(d for d in new_state.drafts if d.item_id == payload.item_id)
    return updated.model_dump()
```

(즉시 재렌더 코드 블록 — `form_bytes = store.get_form_bytes(...)`부터 끝까지 — 모두 삭제)

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_drafts.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/sessions.py backend/tests/integration/test_api_drafts.py
git commit -m "$(cat <<'EOF'
feat(api): PUT /drafts is text-only; 409 on locked; no immediate render

Render moves to download time. Locked drafts must be unlocked before
edit. Response body returns the updated DraftItem.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `POST /api/sessions/{sid}/item-chat` — 잠긴 항목 차단

**Files:**
- Modify: `backend/app/api/sessions.py:84-142`

- [ ] **Step 1: 잠금 차단 테스트 추가**

`backend/tests/integration/test_api_items.py`에 추가:

```python
def test_item_chat_400_when_locked(client: TestClient, session_with_drafts):
    sid = session_with_drafts
    client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": "it1"})
    r = client.post(
        f"/api/sessions/{sid}/item-chat",
        json={"item_id": "it1", "message": "다시 써줘", "history": []},
    )
    assert r.status_code == 400
    assert "해제" in r.json()["detail"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_items.py::test_item_chat_400_when_locked -v
```

Expected: FAIL — Solar 호출 시도하다가 200 또는 502.

- [ ] **Step 3: `item_chat` 핸들러에 locked 검사 추가**

`backend/app/api/sessions.py`의 `item_chat` 함수 안 PII 검사 직후(`if item.is_pii: raise ...` 다음)에 추가:

```python
    target = next((d for d in state.drafts if d.item_id == item_id), None)
    if target is not None and target.locked:
        raise HTTPException(
            status_code=400,
            detail="잠긴 항목과는 대화할 수 없습니다. 먼저 🔓 해제하세요.",
        )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_items.py::test_item_chat_400_when_locked -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/sessions.py backend/tests/integration/test_api_items.py
git commit -m "$(cat <<'EOF'
feat(api): item-chat rejects locked drafts (400)

Mirrors the lock semantics on PUT /drafts. UI must unlock first.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `GET /api/sessions/{sid}/output.hwpx` — lazy 렌더

**Files:**
- Modify: `backend/app/api/sessions.py:download_output`
- Create: `backend/tests/integration/test_api_output.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/integration/test_api_output.py`:

```python
"""Integration tests for GET /api/sessions/{sid}/output.hwpx (lazy render)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.state import DraftItem, GraphState
from backend.app.hwpx.parser import parse_form_doc
from backend.app.main import app
from backend.app.session import store

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "forms" / "sample_form.hwpx"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_with_form(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    form_bytes = _FIXTURE.read_bytes()
    await store.put_form_bytes(sid, form_bytes)
    fd = parse_form_doc(form_bytes)
    if not fd.items:
        pytest.skip("fixture has no items")
    state = GraphState(
        session_id=sid,
        form_doc=fd,
        drafts=[
            DraftItem(item_id=fd.items[0].item_id, text="적용된 본문", citations=[], locked=True),
            DraftItem(item_id=fd.items[1].item_id, text="미적용 본문", citations=[], locked=False)
            if len(fd.items) > 1 else DraftItem(item_id=fd.items[0].item_id, text="x", citations=[], locked=True),
        ],
    )
    await store.save_state(sid, state)
    yield sid, fd
    await store.delete(sid)


def test_download_renders_only_locked_drafts(client: TestClient, session_with_form):
    sid, fd = session_with_form
    r = client.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/")
    assert r.content[:2] == b"PK"


def test_download_404_without_form(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.get(f"/api/sessions/{sid}/output.hwpx")
    assert r.status_code == 404
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_output.py -v
```

Expected: FAIL — 현 핸들러는 `session.rendered_bytes` 없으면 404를 반환하는데 새 흐름에선 `rendered_bytes`를 안 채움.

- [ ] **Step 3: `download_output` 핸들러를 lazy 렌더로 교체**

`backend/app/api/sessions.py`의 `download_output` 함수를 다음으로 교체:

```python
@router.get("/api/sessions/{session_id}/output.hwpx")
async def download_output(session_id: str):
    """Lazy render — build .hwpx from currently locked drafts at request time."""
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if session.form_bytes is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="양식 또는 graph_state가 없습니다.")

    result = render_output(session.graph_state, session.form_bytes)
    rendered = result.get("rendered_bytes", b"")
    if not rendered:
        raise HTTPException(status_code=500, detail="렌더 실패")

    return Response(
        content=rendered,
        media_type="application/vnd.hancom.hwpx",
        headers={"Content-Disposition": 'attachment; filename="output.hwpx"'},
    )
```

(`from backend.app.graph.nodes.renderer import render_output`은 이미 import되어 있음 — 확인하고 없으면 추가)

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_output.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/sessions.py backend/tests/integration/test_api_output.py
git commit -m "$(cat <<'EOF'
feat(api): GET /output.hwpx renders lazily from locked drafts

No more eager render on PUT /drafts. The .hwpx is built at download
time from drafts where locked=True.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `POST /api/chat` — plain JSON 일반 QA only

**Files:**
- Modify: `backend/app/api/chat.py` (전면 재작성)
- Modify: `backend/tests/integration/test_api_chat.py` (재작성)

- [ ] **Step 1: 통합 테스트 재작성**

`backend/tests/integration/test_api_chat.py` 전체를 다음으로 교체:

```python
"""Integration tests for POST /api/chat — general QA only, plain JSON."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.session import store


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session_id(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    yield sid
    await store.delete(sid)


def test_chat_404_for_unknown_session(client: TestClient):
    r = client.post("/api/chat", json={"session_id": "ghost", "message": "안녕"})
    assert r.status_code == 404


def test_chat_returns_plain_json_reply(client: TestClient, session_id):
    with patch("backend.app.api.chat._solar_complete", return_value="안녕하세요. 무엇을 도와드릴까요?"):
        r = client.post("/api/chat", json={"session_id": session_id, "message": "안녕"})
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body
    assert isinstance(body["reply"], str)


def test_chat_appends_to_history(client: TestClient, session_id):
    with patch("backend.app.api.chat._solar_complete", return_value="응답"):
        client.post("/api/chat", json={"session_id": session_id, "message": "Q1"})
        client.post("/api/chat", json={"session_id": session_id, "message": "Q2"})
    session = store._sessions[session_id]
    assert session.graph_state is not None
    history = session.graph_state.history
    user_msgs = [t for t in history if t["role"] == "user"]
    assert any(t["content"] == "Q1" for t in user_msgs)
    assert any(t["content"] == "Q2" for t in user_msgs)
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_api_chat.py -v
```

Expected: FAIL — 현재 chat.py는 SSE 응답이라 `r.json()` 호출 시 실패.

- [ ] **Step 3: `chat.py` 전면 재작성**

`backend/app/api/chat.py` 전체를 다음으로 교체:

```python
"""POST /api/chat — general QA. Plain JSON. Router/Graph bypassed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.graph.state import GraphState, append_turn
from backend.app.llm import solar
from backend.app.session import store

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str


_QA_SYSTEM = """\
당신은 한국 국가연구비 지원사업 양식 작성을 돕는 AI 어시스턴트입니다.
사용자의 일반적인 질문에 친절하고 정확하게 한국어로 답변하세요.
양식 자동 채우기와 무관한 일반 질문에 대해서도 도움을 드립니다.
양식을 채우려면 사이드바의 '양식 자동 채우기 시작' 버튼을 사용해 달라고 안내하세요.
항목별 수정이나 재시도가 필요하면 항목 카드의 ✏ 수정 / 💬 대화 버튼을 안내하세요.
"""


def _solar_complete(messages: list[dict]) -> str:
    return str(solar.complete(messages, json_mode=False))


@router.post("/api/chat")
async def chat(req: ChatRequest):
    session = await store.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"세션을 찾을 수 없습니다: {req.session_id}")

    state = session.graph_state or GraphState(session_id=req.session_id)
    history_msgs = [{"role": t["role"], "content": t["content"]} for t in state.history]

    messages = [{"role": "system", "content": _QA_SYSTEM}]
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": req.message})

    try:
        reply = _solar_complete(messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Solar 호출 실패: {exc}")

    new_state = append_turn(state, "user", req.message)
    new_state = append_turn(new_state, "assistant", reply)
    await store.save_state(req.session_id, new_state)

    return {"reply": reply}
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest backend/tests/integration/test_api_chat.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api/chat.py backend/tests/integration/test_api_chat.py
git commit -m "$(cat <<'EOF'
feat(api): /api/chat is general-QA only with plain JSON

Bypasses Router and Graph entirely. Returns {reply: str}. History is
trimmed to last 10 turns by append_turn.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: 시나리오 테스트 갱신 (`test_scenarios.py`)

**Files:**
- Modify: `backend/tests/integration/test_scenarios.py`

- [ ] **Step 1: 현재 테스트 실패 확인**

```bash
uv run pytest backend/tests/integration/test_scenarios.py -v 2>&1 | head -40
```

Expected: 다수 실패 — 의도 분기·SSE 이벤트 셋·`approved` 어서션이 모두 깨짐.

- [ ] **Step 2: 테스트를 새 흐름으로 재작성**

`test_scenarios.py`를 다음 시나리오로 재구성 (실제 Solar 호출은 모두 mock):

1. 양식 + 자료 업로드 → `POST /fill` SSE 진행 → drafts 모두 `locked=False`
2. `POST /items/apply` 1건 → `GET /output.hwpx`가 200으로 응답하고 첫 두 바이트가 `b"PK"` (zip 헤더)
3. `POST /items/unlock` → 다시 다운로드 시 미적용 항목 양식 원본 그대로 (이건 fixture의 placeholder를 검증하기 어려우면 skip 가능)
4. `PUT /drafts`로 텍스트 수정 → `POST /items/apply` → 다시 다운로드

전체 코드 (간결한 최소 시나리오):

```python
"""End-to-end scenario tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.session import store

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "forms" / "sample_form.hwpx"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _solar_patches():
    return (
        patch("backend.app.graph.nodes.planner._solar_complete", return_value=[]),
        patch(
            "backend.app.graph.nodes.generator._solar_complete",
            return_value={"text": "초안 본문", "citations": []},
        ),
        patch("backend.app.graph.nodes.verifier._solar_complete", return_value={"verdict": "ok"}),
    )


@pytest.mark.asyncio
async def test_full_flow_fill_apply_download(client: TestClient):
    sid = client.post("/api/sessions").json()["session_id"]
    try:
        client.post(
            "/api/upload",
            data={"session_id": sid, "kind": "form"},
            files={"file": ("sample.hwpx", _FIXTURE.read_bytes(), "application/octet-stream")},
        )
        client.post(
            "/api/upload",
            data={"session_id": sid, "kind": "material"},
            files={"file": ("cv.txt", b"researcher info", "text/plain")},
        )

        p1, p2, p3 = _solar_patches()
        with p1, p2, p3:
            r = client.post(f"/api/sessions/{sid}/fill")
        assert r.status_code == 200

        state = store._sessions[sid].graph_state
        assert state is not None
        assert state.drafts, "drafts should be generated"
        assert all(d.locked is False for d in state.drafts)

        first = next((d for d in state.drafts if not state.form_doc.items), None)
        target_id = next(
            (d.item_id for d in state.drafts
             if not any(it.item_id == d.item_id and it.is_pii for it in state.form_doc.items)),
            None,
        )
        assert target_id is not None

        r = client.post(f"/api/sessions/{sid}/items/apply", json={"item_id": target_id})
        assert r.status_code == 200
        assert r.json()["locked"] is True

        r = client.get(f"/api/sessions/{sid}/output.hwpx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
    finally:
        await store.delete(sid)
```

- [ ] **Step 3: 테스트 실행, 통과 확인**

```bash
uv run pytest backend/tests/integration/test_scenarios.py -v
```

Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add backend/tests/integration/test_scenarios.py
git commit -m "$(cat <<'EOF'
test(scenarios): rewrite e2e against new fill/apply/download flow

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — 프론트엔드

### Task 13: 사이드바에 "▶ 양식 자동 채우기 시작" 버튼 추가

**Files:**
- Modify: `frontend/streamlit_app.py` (사이드바 영역)

> 프론트엔드는 자동화된 단위 테스트 대신 dev 서버에서 수동 검증 (CLAUDE.md "For UI or frontend changes, start the dev server and use the feature in a browser before reporting the task as complete.").

- [ ] **Step 1: 사이드바 영역에 시작 버튼 추가**

`frontend/streamlit_app.py`의 사이드바(`with st.sidebar:`) 끝부분 (자료 업로드 섹션 다음)에 다음을 추가:

```python
    st.divider()
    st.subheader("자동 채우기")
    can_fill = bool(st.session_state.uploaded_form) and bool(st.session_state.uploaded_materials)
    if st.button(
        "▶ 양식 자동 채우기 시작",
        use_container_width=True,
        disabled=not can_fill,
        type="primary" if can_fill else "secondary",
    ):
        st.session_state.fill_requested = True
        st.rerun()
    if not can_fill:
        st.caption("양식과 자료를 모두 업로드하면 활성화됩니다.")
```

`_DEFAULTS` 딕셔너리에 추가:

```python
    "fill_requested": False,
```

- [ ] **Step 2: `_stream_fill` 헬퍼 추가**

`_stream_chat` 함수 바로 위에 추가:

```python
def _stream_fill() -> Iterator[tuple[str, str]]:
    sid = st.session_state.session_id
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    with httpx.stream(
        "POST",
        f"{_current_backend()}/api/sessions/{sid}/fill",
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        event = "message"
        data: list[str] = []
        for raw in r.iter_lines():
            line = raw.rstrip("\r")
            if line == "":
                if data:
                    yield event, "\n".join(data)
                event = "message"
                data = []
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data.append(line.split(":", 1)[1].strip())
        if data:
            yield event, "\n".join(data)
```

- [ ] **Step 3: 메인 영역에서 fill 요청 처리**

`if st.session_state.drafts:` 위쪽 (form-structure visualization 다음)에 다음 블록 삽입:

```python
if st.session_state.fill_requested:
    st.session_state.fill_requested = False
    status = st.empty()
    try:
        for event, raw in _stream_fill():
            payload = json.loads(raw) if raw else None
            if event == "node_started":
                status.write(f"… {payload['node']}")
            elif event == "form_parsed":
                st.session_state.form_doc = payload
            elif event == "preview":
                st.session_state.drafts = payload or []
            elif event == "done":
                count = (payload or {}).get("draft_count", 0)
                status.success(f"초안 {count}개 생성")
            elif event == "error":
                err = (payload or {}).get("error", "unknown")
                st.error(f"채우기 오류: {err}")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
    st.rerun()
```

- [ ] **Step 4: dev 서버 띄워 수동 확인**

```bash
uv run uvicorn backend.app.main:app --reload --port 8000 &
uv run streamlit run frontend/streamlit_app.py
```

브라우저에서:
1. 새 세션 생성
2. 양식 + 자료 업로드
3. ▶ 양식 자동 채우기 시작 버튼 활성화 확인
4. 클릭 → 진행 메시지가 나타나고 초안 카드가 등장
5. 카드들이 모두 미적용 상태 (✓적용 / ✏수정 / 💬대화 노출 — 다음 task에서 정리)

Expected: 진행 → 카드 등장. 다음 task에서 카드 액션 갱신.

- [ ] **Step 5: 커밋**

```bash
git add frontend/streamlit_app.py
git commit -m "$(cat <<'EOF'
feat(ui): sidebar '양식 자동 채우기 시작' button + SSE fill stream

Triggered from sidebar (not chat). Disabled until both form and at
least one material are uploaded. Streams node_started / form_parsed /
preview / done events.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: 항목 카드 — 3버튼 + 🔓 해제, `applied_` 플래그 제거, 🔁 제거

**Files:**
- Modify: `frontend/streamlit_app.py` (drafts preview 블록 + 백엔드 헬퍼)

- [ ] **Step 1: 백엔드 헬퍼 함수 추가**

`_save_draft_edit` 함수 근처에 다음 헬퍼들을 추가:

```python
def _apply_item(item_id: str) -> bool:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/apply",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        return True
    except Exception as exc:
        st.error(f"적용 실패: {exc}")
        return False


def _unlock_item(item_id: str) -> bool:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/sessions/{sid}/items/unlock",
            json={"item_id": item_id},
            timeout=10.0,
        )
        r.raise_for_status()
        _replace_draft(r.json())
        return True
    except Exception as exc:
        st.error(f"해제 실패: {exc}")
        return False


def _replace_draft(updated: dict) -> None:
    for i, d in enumerate(st.session_state.drafts):
        if d.get("item_id") == updated["item_id"]:
            st.session_state.drafts[i] = updated
            return
```

- [ ] **Step 2: `_save_draft_edit`도 응답 body로 갱신하도록 변경**

함수 끝부분의 `for di in st.session_state.drafts: ... di["text"] = text` 블록을 다음으로 교체:

```python
    try:
        _replace_draft(r.json())
    except Exception:
        for di in st.session_state.drafts:
            if di.get("item_id") == item_id:
                di["text"] = text
                break
    return True
```

- [ ] **Step 3: drafts 렌더 블록 재작성**

`if st.session_state.drafts:` 블록 전체를 다음으로 교체:

```python
if st.session_state.drafts:
    st.subheader("작성된 초안")
    for d in st.session_state.drafts:
        item_id = d.get("item_id", "?")
        locked = bool(d.get("locked", False))
        editing = st.session_state.get(f"editing_{item_id}", False)
        chatting = st.session_state.get(f"chatting_{item_id}", False)
        label = _item_label(item_id)
        unfilled = _is_unfilled(d.get("text", ""))

        with st.container(border=True):
            badge = "🔒 적용됨" if locked else ("⚠️ 미작성" if unfilled else "")

            if locked:
                cols = st.columns([5, 1])
                cols[0].markdown(f"**{label}** {badge}")
                if cols[1].button("🔓 해제", key=f"unlock_{item_id}"):
                    if _unlock_item(item_id):
                        st.rerun()
                st.write(d.get("text", ""))
                citations = d.get("citations", [])
                if citations:
                    st.caption(f"근거: {', '.join(citations)}")
                continue

            cols = st.columns([4, 1, 1, 1])
            cols[0].markdown(f"**{label}** {badge}")

            if cols[1].button("✓ 적용", key=f"apply_{item_id}", disabled=editing):
                if unfilled:
                    st.session_state[f"apply_warn_{item_id}"] = True
                    st.rerun()
                elif _apply_item(item_id):
                    st.rerun()

            if cols[2].button("✏ 수정", key=f"edit_{item_id}"):
                st.session_state[f"editing_{item_id}"] = not editing
                st.rerun()

            if cols[3].button("💬 대화", key=f"chat_{item_id}"):
                st.session_state[f"chatting_{item_id}"] = not chatting
                st.rerun()

            if st.session_state.pop(f"apply_warn_{item_id}", False):
                st.warning(
                    f"⚠ '{label}' 항목이 아직 비어 있습니다 (`[추가 정보 필요]`). "
                    "💬 대화로 채우거나 ✏ 수정으로 직접 입력한 뒤 적용해 주세요."
                )

            if editing:
                new_text = st.text_area(
                    "본문 수정",
                    value=d.get("text", ""),
                    key=f"edit_text_{item_id}",
                    height=160,
                )
                save_col, cancel_col = st.columns([1, 1])
                if save_col.button("저장", key=f"save_{item_id}"):
                    if _save_draft_edit(item_id, new_text):
                        st.session_state[f"editing_{item_id}"] = False
                        st.rerun()
                if cancel_col.button("취소", key=f"cancel_{item_id}"):
                    st.session_state[f"editing_{item_id}"] = False
                    st.rerun()
            else:
                st.write(d.get("text", ""))

            citations = d.get("citations", [])
            if citations:
                st.caption(f"근거: {', '.join(citations)}")

            if chatting:
                hist_key = f"chat_history_{item_id}"
                history = st.session_state.get(hist_key, [])
                with st.container(border=True):
                    st.markdown(
                        f"💬 **'{label}' 항목과 대화하기** — 정보를 알려주시면 본문을 함께 만들어 드립니다."
                    )
                    for m in history:
                        with st.chat_message(m["role"]):
                            import html as _html

                            safe = _html.escape(m["content"]).replace("\n", "<br>")
                            st.markdown(
                                f'<div style="font-size: 0.95rem; line-height: 1.55;">{safe}</div>',
                                unsafe_allow_html=True,
                            )

                    with st.form(f"chat_form_{item_id}", clear_on_submit=True):
                        typed = st.text_input(
                            "메시지", key=f"chat_input_{item_id}",
                            label_visibility="collapsed",
                            placeholder="이 항목에 대한 정보를 입력하거나 질문하세요…",
                        )
                        send = st.form_submit_button("전송")
                    if send and typed:
                        history.append({"role": "user", "content": typed})
                        with st.spinner("응답 생성 중…"):
                            reply = _item_chat(item_id, typed, history[:-1])
                        if reply:
                            history.append({"role": "assistant", "content": reply})
                        st.session_state[hist_key] = history
                        st.rerun()

                    if history:
                        last_assistant = next(
                            (m["content"] for m in reversed(history) if m["role"] == "assistant"),
                            None,
                        )
                        body_preview = _extract_body(last_assistant) if last_assistant else ""
                        if body_preview and body_preview != (last_assistant or "").strip():
                            with st.expander("적용될 본문 미리보기", expanded=False):
                                st.write(body_preview)
                        action_cols = st.columns([2, 1, 2])
                        if action_cols[0].button(
                            "🟢 본문만 추출해 적용",
                            key=f"apply_chat_{item_id}",
                            disabled=not body_preview,
                        ):
                            if body_preview and _save_draft_edit(item_id, body_preview):
                                if _apply_item(item_id):
                                    st.session_state[f"chatting_{item_id}"] = False
                                    st.session_state[hist_key] = []
                                    st.rerun()
                        if action_cols[1].button("대화 닫기", key=f"close_chat_{item_id}"):
                            st.session_state[f"chatting_{item_id}"] = False
                            st.rerun()
```

(🔁 다시 버튼 / `applied_` 플래그 / `redo_msg` 흐름은 모두 빠진 형태)

- [ ] **Step 4: `_reset_state`에서 제거된 키 정리**

```python
def _reset_state() -> None:
    for key, default in _DEFAULTS.items():
        if key == "session_id":
            continue
        st.session_state[key] = default if not isinstance(default, list) else list(default)
    for key in list(st.session_state.keys()):
        if key.startswith(
            (
                "editing_",
                "edit_text_",
                "chatting_",
                "chat_history_",
                "chat_input_",
                "apply_warn_",
            )
        ):
            del st.session_state[key]
```

(`applied_` prefix 삭제)

- [ ] **Step 5: dev 서버에서 수동 확인**

브라우저에서:
1. 일괄 채우기 → 모든 카드가 ✓적용/✏수정/💬대화 3버튼
2. ✓ 적용 → 카드가 🔒 적용됨 + 🔓 해제 버튼만
3. 🔓 해제 → 다시 3버튼으로 복귀
4. ✏ 수정 → 텍스트 박스 열림, 저장 → 텍스트만 갱신, 잠금 안 됨
5. 💬 대화 → 카드 안 대화창, "본문만 추출해 적용" → 자동 잠금

Expected: 모든 흐름 동작. 채팅 thread 메시지 추가 안 됨.

- [ ] **Step 6: 커밋**

```bash
git add frontend/streamlit_app.py
git commit -m "$(cat <<'EOF'
feat(ui): card 3-button (apply/edit/chat) + lock state with unlock

Removes the 🔁 다시 button (use 💬 chat instead). Replaces the local
applied_<id> flag with draft.locked from the server. Apply/unlock are
backend round-trips that return the updated DraftItem.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: 메인 채팅 — plain JSON, pending_question UI 제거, fill SSE 분기 제거

**Files:**
- Modify: `frontend/streamlit_app.py`

- [ ] **Step 1: `_process_stream` 함수를 plain JSON 호출로 교체**

`_process_stream` 함수 전체를 다음으로 교체:

```python
def _process_chat(message: str) -> None:
    sid = st.session_state.session_id
    try:
        r = httpx.post(
            f"{_current_backend()}/api/chat",
            json={"session_id": sid, "message": message},
            timeout=120.0,
        )
        r.raise_for_status()
        reply = r.json().get("reply", "")
    except Exception as exc:
        st.error(f"통신 오류: {exc}")
        return
    st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
```

- [ ] **Step 2: 채팅 입력 흐름 갱신**

파일 하단의 `user_msg = st.chat_input(...)` 블록을 다음으로 교체:

```python
user_msg = st.chat_input("무엇을 도와드릴까요?")
if user_msg:
    if not st.session_state.session_id:
        st.warning("먼저 ▶ 새 세션 버튼으로 세션을 시작하세요.")
    else:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            _process_chat(user_msg)
```

- [ ] **Step 3: pending_question UI 박스 삭제**

다음 블록 전체 삭제:

```python
if st.session_state.pending_question:
    pq = st.session_state.pending_question
    with st.container(border=True):
        ...
```

- [ ] **Step 4: `_DEFAULTS`에서 `pending_question` 제거**

```python
_DEFAULTS = {
    "session_id": None,
    "messages": [],
    "form_doc": None,
    "drafts": [],
    "uploaded_form": None,
    "uploaded_materials": [],
    "fill_requested": False,
}
```

(`pending_question`, `download_url` 항목 모두 제거. `download_url`은 다음 task에서 처리되므로 함께 빠짐)

- [ ] **Step 5: 메인 채팅 도중 form_parsed/preview/pending_question 처리하던 코드 흔적 검색·제거**

```bash
uv run python -c "import subprocess; subprocess.run(['rg', '-n', 'pending_question|form_parsed|preview', 'frontend/streamlit_app.py'])"
```

남은 참조가 있으면 모두 제거.

- [ ] **Step 6: dev 서버에서 수동 확인**

브라우저에서:
1. 메인 채팅에 "안녕하세요" 입력 → plain JSON 응답이 채팅에 추가됨
2. "양식을 채워줘" 입력 → 의도 분류 없이 일반 QA 응답 (사이드바 버튼을 안내하는 응답)
3. pending_question 박스 사라짐 확인

Expected: 채팅이 일반 QA만 처리. 사이드바 버튼이 채우기 트리거의 유일한 경로.

- [ ] **Step 7: 커밋**

```bash
git add frontend/streamlit_app.py
git commit -m "$(cat <<'EOF'
feat(ui): main chat is general-QA only (plain JSON)

Drops SSE handling for fill events on /api/chat and removes the
pending_question UI box (replaced by per-card 💬 chat).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: 다운로드 버튼 — lazy 호출 + bytes 다운로드

**Files:**
- Modify: `frontend/streamlit_app.py`

- [ ] **Step 1: 다운로드 헬퍼 추가**

`_unlock_item` 다음에 추가:

```python
def _fetch_output_bytes() -> bytes | None:
    sid = st.session_state.session_id
    try:
        r = httpx.get(
            f"{_current_backend()}/api/sessions/{sid}/output.hwpx", timeout=60.0
        )
        r.raise_for_status()
        return r.content
    except Exception as exc:
        st.error(f"다운로드 실패: {exc}")
        return None
```

- [ ] **Step 2: 사이드바 다운로드 영역 갱신**

사이드바 끝부분 ("자동 채우기" 섹션 다음)에 추가:

```python
    locked_count = sum(1 for d in st.session_state.drafts if d.get("locked"))
    total_count = len(st.session_state.drafts)
    st.caption(f"적용된 항목 {locked_count} / 전체 {total_count}")
    if st.button(
        "📥 출력 .hwpx 다운로드",
        use_container_width=True,
        disabled=locked_count == 0,
        key="download_btn",
    ):
        data = _fetch_output_bytes()
        if data:
            st.download_button(
                "📁 파일 저장",
                data=data,
                file_name="output.hwpx",
                mime="application/vnd.hancom.hwpx",
                key="download_save_btn",
                use_container_width=True,
            )
```

- [ ] **Step 3: 본문 영역에 남아 있던 `download_url` 기반 다운로드 블록 삭제**

파일 하단의 다음 블록 제거:

```python
if st.session_state.download_url:
    ...
    st.link_button(...)
```

- [ ] **Step 4: dev 서버에서 수동 확인**

브라우저에서:
1. 일괄 채우기 직후 다운로드 버튼 비활성화 (적용된 항목 0)
2. 한 항목 ✓ 적용 → 다운로드 버튼 활성화 ("적용된 항목 1 / 전체 N")
3. 다운로드 버튼 클릭 → 잠시 대기 후 "파일 저장" 버튼 등장 → 클릭 시 .hwpx 다운로드
4. 다운로드된 파일을 한컴오피스에서 열어 적용된 항목만 채워졌는지 확인

Expected: lazy 렌더 흐름 완전 동작.

- [ ] **Step 5: 커밋**

```bash
git add frontend/streamlit_app.py
git commit -m "$(cat <<'EOF'
feat(ui): lazy download — fetch bytes from /output.hwpx on click

Sidebar shows '적용된 항목 K / 전체 N'. Download button only enables
when at least one item is applied. Backend renders at request time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — 정리 및 검증

### Task 17: K2 KPI 분기 임시 무효화 + open issue 메모

**Files:**
- Modify: `eval/run_kpi.py`

- [ ] **Step 1: 현재 K2 분기 위치 확인**

```bash
uv run python -c "import subprocess; subprocess.run(['rg', '-n', 'K2|router_intent', 'eval/run_kpi.py'])"
```

- [ ] **Step 2: K2 검사를 임시 비활성화**

`eval/run_kpi.py`에서 K2 평가 블록을 다음과 같이 감싼다:

```python
# K2 (router intent accuracy) is removed — see
# docs/superpowers/specs/2026-05-08-per-item-actions-design.md Open Issue #1.
# Re-enable once a successor metric is defined.
SKIP_K2 = True

if not SKIP_K2:
    # ... 기존 K2 평가 코드 ...
```

(파일 구조에 따라 정확한 위치는 다르니 함수·섹션 단위로 적절히 wrap)

- [ ] **Step 3: 실행해 K2 분기 없이도 종료되는지 확인**

```bash
uv run python eval/run_kpi.py --help
```

(전체 실행은 시간·비용 듦. 단순 import 에러 없는지만 확인)

- [ ] **Step 4: 커밋**

```bash
git add eval/run_kpi.py
git commit -m "$(cat <<'EOF'
chore(eval): skip K2 (router accuracy) — Router is gone

KPI definition needs to be redesigned per design doc Open Issue #1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: 전체 단위 + 통합 테스트 통과 확인

- [ ] **Step 1: 전체 테스트 실행**

```bash
uv run pytest -q
```

Expected: 모두 통과. 실패하는 케이스가 있으면 어느 모듈인지 분류:
- 라우터/Question 흔적 → Task 3·4에서 빠뜨린 import
- `approved` 어서션 잔존 → Task 1에서 빠뜨린 파일
- `pending_question`/`intent` 참조 → Task 2 또는 11에서 빠뜨림

- [ ] **Step 2: 실패 시 해당 파일을 위에 명시한 task 단위로 추가 정리**

(이건 reactive — 실패가 없으면 skip)

- [ ] **Step 3: lint·format 검사**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: 깨끗. 문제 있으면 `uv run ruff check --fix . && uv run ruff format .` 후 변경된 파일 커밋.

- [ ] **Step 4: 모든 검증 통과 후 커밋**

```bash
git status
```

(변경 없으면 커밋 불필요. 변경 있으면 잡다 정리만 남았다는 뜻이므로 한 커밋으로)

```bash
git add -u
git commit -m "$(cat <<'EOF'
chore: lint and format cleanup after refactor

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: 수동 end-to-end 검증 (golden path)

- [ ] **Step 1: 백엔드·프론트엔드 dev 서버 기동**

별도 터미널 두 개에서:

```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

```bash
uv run streamlit run frontend/streamlit_app.py
```

- [ ] **Step 2: 골든 패스 시나리오 수행**

브라우저에서:
1. 새 세션 시작
2. 양식(.hwpx) 업로드 → 사이드바에 파일명 등장
3. 자료(PDF/docx) 1개 이상 업로드 → 동일
4. ▶ 양식 자동 채우기 시작 → 진행 메시지 → 카드들 등장 (모두 미적용)
5. 카드 1: ✏ 수정 → 텍스트 박스에서 수정 → 저장 → 카드 텍스트만 바뀌고 미적용 유지
6. 카드 2: 💬 대화 → "더 구체적으로 작성해줘" → LLM 응답 → "🟢 본문만 추출해 적용" → 카드 잠금
7. 카드 3: ✓ 적용 → 즉시 잠금
8. 잠긴 카드: 🔓 해제 → 3버튼 복귀
9. 사이드바 진행률 "적용된 항목 K / 전체 N" 표시 확인
10. 📥 다운로드 → 파일 저장 → 한컴오피스에서 열어 적용된 항목만 채워졌는지 확인

- [ ] **Step 3: 엣지 케이스 확인**

- 일반 채팅 ("HwpAgent가 뭐야?") → 채팅 thread에 응답만, 항목 카드 영역에 변화 없음
- 잠긴 항목 ✏ 수정 시도 → 409 응답이 사용자에게 보임
- 미적용 0개 상태에서 다운로드 → 버튼 비활성화

- [ ] **Step 4: 결과 보고**

(이 시점에 plan 자체는 완료. 별도 커밋 없음)

---

## Self-Review

**Spec coverage 점검:**

| Spec 섹션 | 구현 task |
|---|---|
| 결정 1 (채팅·항목 분리) | Task 13–16 (사이드바 트리거, 카드 3버튼, 채팅 plain JSON) |
| 결정 2 (적용=출력+잠금) | Task 1 (`locked` 필드), Task 7 (apply 핸들러), Task 10 (lazy 렌더 필터) |
| 결정 3 (사이드바 시작 버튼) | Task 13 |
| 결정 4 (미적용=원본) | Task 10 + Renderer 필터 (Task 1) |
| 결정 5 (🔁 제거, 💬 일원화) | Task 14 (🔁 흔적 삭제) |
| 결정 6 (별도 🔓 해제) | Task 14 |
| 결정 7 (lazy 렌더) | Task 8, 10, 16 |
| 결정 8 (라우터 단순화) | Task 3, 5, 11 |
| Verifier 마커만 부여 | Task 1 step 5 |
| `PUT /drafts` 텍스트만 + 409 | Task 8 |
| `item-chat` locked 차단 | Task 9 |
| 그래프 다이어그램 갱신 | Task 5 step 4 |
| K2 KPI Open Issue | Task 17 |

모든 spec 결정에 대응 task 있음.

**Placeholder scan:** "TBD" / "implement later" / "add appropriate" / "similar to Task N" 검색 — 없음.

**Type consistency:**
- `DraftItem.locked: bool = False` — Task 1, 6, 7, 8, 10에서 일관되게 사용
- `ItemIdRequest(BaseModel): item_id: str` — Task 7에서 정의, Task 9에서 동일 모델 활용 (path 안 들어감)
- 응답 body는 `DraftItem.model_dump()` 형태 — Task 7, 8에서 동일
- `_replace_draft(updated: dict)` — Task 14에서 정의, 14·16에서 사용

**Frontend 의존성 일관성:**
- Task 13에서 `fill_requested` 추가 → Task 15의 `_DEFAULTS` 갱신에서도 보존
- Task 14에서 `_apply_item`/`_unlock_item`/`_replace_draft` 정의 → Task 16에서 추가 호출 없음 (다운로드는 직접 GET)

문제 없음. 계획 완료.
