"""POST /api/sessions and GET /api/sessions/{id}/output.hwpx."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from backend.app.session import store

router = APIRouter()


@router.post("/api/sessions")
async def create_session():
    session_id = await store.create()
    return {"session_id": session_id}


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
