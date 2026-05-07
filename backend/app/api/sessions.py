"""POST /api/sessions, draft-edit PUT, GET /api/sessions/{id}/output.hwpx."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.app.graph.nodes.renderer import render_output
from backend.app.session import store

router = APIRouter()


class DraftUpdate(BaseModel):
    item_id: str
    text: str


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
        d.model_copy(update={"text": payload.text, "approved": True})
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
        "intent": state.intent,
        "errors": state.errors,
        "form_doc": {
            "items": [
                {"item_id": it.item_id, "label": it.label, "is_pii": it.is_pii}
                for it in (state.form_doc.items if state.form_doc else [])
            ],
        },
        "plans": [p.model_dump() for p in state.plans],
        "drafts": [d.model_dump() for d in state.drafts],
        "pending_question": state.pending_question.model_dump() if state.pending_question else None,
        "materials_count": len(state.materials.docs),
        "materials": [
            {"doc_id": d.get("doc_id"), "filename": d.get("filename"), "summary": d.get("summary", "")[:160]}
            for d in state.materials.docs
        ],
    }
