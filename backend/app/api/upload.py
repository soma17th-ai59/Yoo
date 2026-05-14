"""POST /api/upload — multipart file upload (form or material) into the session store.

Memory-only: bytes go directly into the in-memory SessionStore.
Size limit is 20 MB per file (spec §6 / KPI safety).
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.app.session import store

router = APIRouter()

_MAX_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/api/upload")
async def upload_file(
    session_id: str = Form(...),
    kind: str = Form(...),
    file: UploadFile = File(...),
):
    if kind not in ("form", "material"):
        raise HTTPException(
            status_code=400,
            detail=f"kind는 'form' 또는 'material'이어야 합니다: {kind!r}",
        )

    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"세션을 찾을 수 없습니다: {session_id}")

    data = await file.read()
    if len(data) > _MAX_SIZE:
        raise HTTPException(status_code=413, detail="파일이 20MB 제한을 초과합니다.")

    if kind == "form":
        await store.put_form_bytes(session_id, data, file.filename or "unknown")
    else:
        await store.put_material_file(session_id, file.filename or "unknown", data)

    return {"ok": True, "session_id": session_id, "kind": kind}
