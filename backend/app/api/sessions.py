from fastapi import APIRouter
from backend.app.session import store

router = APIRouter()


@router.post("/api/sessions")
async def create_session():
    session_id = await store.create()
    return {"session_id": session_id}
