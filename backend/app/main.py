"""FastAPI entry point. Mounts session, upload, and chat routers.

Sessions are in-memory only — see backend.app.session for the store.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api import chat as chat_api
from backend.app.api import sessions as sessions_api
from backend.app.api import upload as upload_api

app = FastAPI(title="HwpAgent", version="0.1.0")

app.include_router(sessions_api.router)
app.include_router(upload_api.router)
app.include_router(chat_api.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
