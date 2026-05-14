"""POST /api/sessions, draft-edit PUT, GET /api/sessions/{id}/output.hwpx."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.app.graph.graph import build_compiled_graph
from backend.app.graph.nodes.renderer import render_output
from backend.app.graph.state import GraphState
from backend.app.llm import solar
from backend.app.pii import mask_all
from backend.app.session import store

router = APIRouter()


def _session_summary(session) -> dict:
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "has_form": session.form_bytes is not None,
        "uploaded_form": session.form_filename,
        "uploaded_materials": [filename for filename, _ in session.material_files],
        "material_count": len(session.material_files),
        "has_rendered": session.rendered_bytes is not None,
        "has_state": session.graph_state is not None,
    }


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
                    yield {
                        "event": "form_parsed",
                        "data": json.dumps(_to_jsonable(diff["form_doc"])),
                    }
                if diff.get("drafts"):
                    yield {"event": "preview", "data": json.dumps(_to_jsonable(diff["drafts"]))}
                if diff.get("errors"):
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"node": node_name, "error": "; ".join(str(e) for e in diff["errors"])}
                        ),
                    }
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


class DraftUpdate(BaseModel):
    item_id: str
    text: str


class ItemIdRequest(BaseModel):
    item_id: str


def _toggle_locked(state, item_id: str, value: bool):
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


class ItemChatRequest(BaseModel):
    item_id: str
    message: str
    history: list[dict[str, str]] = []


_ITEM_CHAT_SYS = """\
당신은 한국 국가연구비 신청 양식의 한 항목을 사용자와 대화하며 함께 작성하는 보조자입니다.
사용자에게 짧고 구체적인 follow-up 질문을 던져 필요한 정보를 모으고, 모인 정보를 학술 문어체로 정리한 본문을 제안하세요.

대화 규칙:
1. 한 번에 하나의 명확한 질문만 합니다. 한꺼번에 여러 질문 금지.
2. 사용자가 답한 사실만 사용하세요 — 추측·일반론 금지.
3. PII(이름·주민번호·연락처·이메일·주소·계좌·학번 등)는 절대 받지도 본문에 포함하지도 마세요. 사용자가 PII를 알려줘도 "[본인 직접 입력]"으로 마스킹합니다.
4. 충분한 정보가 모이면 다음 형식으로 본문을 제안하세요:
   "정리해 드리면 다음과 같습니다.
   ---
   {정리된 본문}
   ---
   이대로 적용하시겠어요? 수정할 부분이 있으면 말씀해 주세요."
5. 항상 한국어 학술 문어체로 응답하세요.
"""


@router.post("/api/sessions")
async def create_session():
    session_id = await store.create()
    return {"session_id": session_id}


@router.get("/api/sessions")
async def list_sessions():
    return {"sessions": [_session_summary(session) for session in store.list_sessions()]}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    state = session.graph_state
    return {
        **_session_summary(session),
        "form_doc": state.form_doc.model_dump() if state and state.form_doc else None,
        "drafts": [draft.model_dump() for draft in state.drafts] if state else [],
        "history": list(state.history) if state else [],
    }


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


@router.post("/api/sessions/{session_id}/item-chat")
async def item_chat(session_id: str, payload: ItemChatRequest):
    """Conversational fill — talk through one form item with the LLM.

    item_id moves into the body because parser-generated item_ids contain
    slashes ("Contents/section0.xml:p2") which collide with URL path
    segmentation. The conversation never persists in graph_state; the UI
    keeps the history locally and resends it each turn. PII in user input
    is masked before being forwarded to Solar, matching spec §7 rule 1.
    """
    item_id = payload.item_id
    session = await store.get(session_id)
    if session is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="세션 또는 그래프 상태가 없습니다.")
    state = session.graph_state
    if state.form_doc is None:
        raise HTTPException(status_code=400, detail="form_doc이 없어 대화 불가.")

    item = next((it for it in state.form_doc.items if it.item_id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item 미존재: {item_id}")
    if item.is_pii:
        raise HTTPException(
            status_code=400,
            detail="PII 항목은 LLM 경로를 거치지 않습니다. ✏ 수정으로 직접 입력해 주세요.",
        )

    target = next((d for d in state.drafts if d.item_id == item_id), None)
    if target is not None and target.locked:
        raise HTTPException(
            status_code=400,
            detail="잠긴 항목과는 대화할 수 없습니다. 먼저 🔓 해제하세요.",
        )

    plan = next((p for p in state.plans if p.item_id == item_id), None)
    materials_brief = (
        "\n".join(
            f"- {m['filename']}: {m.get('summary', '')[:300]}" for m in state.materials.docs[:6]
        )
        or "(자료 없음)"
    )

    context = (
        f"## 작성 대상 항목\n"
        f"라벨: {item.label}\n"
        + (f"기존 가이드 질문: {plan.question}\n" if plan and plan.question else "")
        + f"현재까지 작성된 초안: {next((d.text for d in state.drafts if d.item_id == item_id), '(없음)')}\n\n"
        f"## 참고자료 요약\n{materials_brief}"
    )

    safe_history = [
        {"role": m.get("role", "user"), "content": mask_all(m.get("content", ""))}
        for m in payload.history
    ]
    safe_user_message = mask_all(payload.message)

    messages = [
        {"role": "system", "content": _ITEM_CHAT_SYS},
        {"role": "user", "content": context},
        *safe_history,
        {"role": "user", "content": safe_user_message},
    ]

    try:
        reply = solar.complete(messages, json_mode=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Solar 호출 실패: {exc}")

    return {"reply": str(reply)}


@router.get("/api/sessions/{session_id}/output.hwpx")
async def download_output(session_id: str, include_unlocked: bool = False):
    """Lazy render — build .hwpx at request time.

    Default: only locked drafts (user-approved) land in the output.
    `?include_unlocked=true`: every generated draft is also written, for the
    "비어 있어도 그대로 다운로드" path.
    """
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if session.form_bytes is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="양식 또는 graph_state가 없습니다.")

    result = render_output(
        session.graph_state, session.form_bytes, include_unlocked=include_unlocked
    )
    rendered = result.get("rendered_bytes", b"")
    if not rendered:
        raise HTTPException(status_code=500, detail="렌더 실패")

    return Response(
        content=rendered,
        media_type="application/vnd.hancom.hwpx",
        headers={"Content-Disposition": 'attachment; filename="output.hwpx"'},
    )


@router.get("/api/sessions/_debug/list")
async def session_list():
    """Diagnostic: list current session IDs and their TTL state."""
    return {"sessions": [_session_summary(session) for session in store.list_sessions()]}


@router.get("/api/sessions/{session_id}/debug")
async def session_debug(session_id: str):
    """Diagnostic: dump plan / draft / error counts for the saved graph state.

    Accepts either a full UUID or any unique prefix of one.
    """
    session = await store.get(session_id)
    if session is None:
        # Fall back to prefix match
        matches = [sid for sid in store._sessions if sid.startswith(session_id)]
        if len(matches) == 1:
            session = await store.get(matches[0])
            session_id = matches[0]
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    state = session.graph_state
    if state is None:
        return {"saved_state": False}
    return {
        "saved_state": True,
        "errors": state.errors,
        "form_doc": {
            "items": [
                {"item_id": it.item_id, "label": it.label, "is_pii": it.is_pii}
                for it in (state.form_doc.items if state.form_doc else [])
            ],
        },
        "plans": [p.model_dump() for p in state.plans],
        "drafts": [d.model_dump() for d in state.drafts],
        "materials_count": len(state.materials.docs),
        "materials": [
            {
                "doc_id": d.get("doc_id"),
                "filename": d.get("filename"),
                "summary": d.get("summary", "")[:160],
            }
            for d in state.materials.docs
        ],
    }
