"""POST /api/sessions, draft-edit PUT, GET /api/sessions/{id}/output.hwpx."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.app.graph.nodes.renderer import render_output
from backend.app.llm import solar
from backend.app.pii import mask_all
from backend.app.session import store

router = APIRouter()


class DraftUpdate(BaseModel):
    item_id: str
    text: str


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


@router.put("/api/sessions/{session_id}/drafts")
async def update_draft(session_id: str, payload: DraftUpdate):
    """Replace one draft's text in the saved graph state and re-render output."""
    session = await store.get(session_id)
    if session is None or session.graph_state is None:
        raise HTTPException(status_code=404, detail="세션 또는 그래프 상태가 없습니다.")
    state = session.graph_state
    if state.form_doc is None:
        raise HTTPException(status_code=400, detail="form_doc이 없어 재렌더링 불가.")

    if not any(d.item_id == payload.item_id for d in state.drafts):
        raise HTTPException(status_code=404, detail=f"draft 미존재: {payload.item_id}")

    new_drafts = [
        d.model_copy(update={"text": payload.text, "locked": True})
        if d.item_id == payload.item_id
        else d
        for d in state.drafts
    ]
    new_state = state.model_copy(update={"drafts": new_drafts})
    await store.save_state(session_id, new_state)

    form_bytes = store.get_form_bytes(session_id)
    if form_bytes:
        result = render_output(new_state, form_bytes)
        rendered = result.get("rendered_bytes", b"")
        if rendered:
            store.put_rendered_bytes(session_id, rendered)

    return {"ok": True, "item_id": payload.item_id}


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
            detail="PII 항목은 [본인 직접 입력]으로 비워두며 대화 작성을 지원하지 않습니다.",
        )

    plan = next((p for p in state.plans if p.item_id == item_id), None)
    materials_brief = "\n".join(
        f"- {m['filename']}: {m.get('summary', '')[:300]}"
        for m in state.materials.docs[:6]
    ) or "(자료 없음)"

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
async def download_output(session_id: str):
    session = await store.get(session_id)
    if session is None or not session.rendered_bytes:
        raise HTTPException(status_code=404, detail="렌더된 출력이 없습니다.")
    return Response(
        content=session.rendered_bytes,
        media_type="application/vnd.hancom.hwpx",
        headers={"Content-Disposition": 'attachment; filename="output.hwpx"'},
    )


@router.get("/api/sessions/_debug/list")
async def session_list():
    """Diagnostic: list current session IDs and their TTL state."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "has_form": s.form_bytes is not None,
                "material_count": len(s.material_files),
                "has_rendered": s.rendered_bytes is not None,
                "has_state": s.graph_state is not None,
            }
            for sid, s in store._sessions.items()
        ]
    }


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
            {"doc_id": d.get("doc_id"), "filename": d.get("filename"), "summary": d.get("summary", "")[:160]}
            for d in state.materials.docs
        ],
    }
