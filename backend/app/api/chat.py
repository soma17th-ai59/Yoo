"""POST /api/chat — drive the LangGraph pipeline and stream events as SSE.

Events emitted:
  - intent           : {"intent": str}                    after Router
  - node_started     : {"node": str}                      before each node
  - preview          : list[DraftItem.model_dump()]       when drafts updated
  - pending_question : PendingQuestion.model_dump()       when Question fires
  - done             : {"download_url": str | None}       at end
  - error            : {"error": str}                     on exception

The graph runs against the in-memory SessionStore as its SessionProvider.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.app.graph.graph import build_compiled_graph
from backend.app.graph.state import GraphState
from backend.app.session import store

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str


def _to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, bytes):
        return f"<{len(obj)} bytes>"
    return obj


async def _stream_graph(session_id: str, message: str) -> AsyncIterator[dict]:
    initial = GraphState(user_message=message, session_id=session_id)
    session = await store.get(session_id)
    if session and session.graph_state is not None:
        prior = session.graph_state
        initial.form_doc = prior.form_doc
        initial.plans = list(prior.plans)
        initial.materials = prior.materials
        initial.history = list(prior.history)

    graph = build_compiled_graph(store)

    try:
        async for chunk in graph.astream(initial, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            for node_name, diff in chunk.items():
                yield {"event": "node_started", "data": json.dumps({"node": node_name})}
                if not isinstance(diff, dict):
                    continue
                if diff.get("intent"):
                    yield {
                        "event": "intent",
                        "data": json.dumps({"intent": diff["intent"]}),
                    }
                if diff.get("form_doc"):
                    yield {
                        "event": "form_parsed",
                        "data": json.dumps(_to_jsonable(diff["form_doc"])),
                    }
                if diff.get("drafts"):
                    yield {
                        "event": "preview",
                        "data": json.dumps(_to_jsonable(diff["drafts"])),
                    }
                if diff.get("pending_question"):
                    yield {
                        "event": "pending_question",
                        "data": json.dumps(_to_jsonable(diff["pending_question"])),
                    }
    except Exception as exc:
        yield {"event": "error", "data": json.dumps({"error": str(exc)})}
        return

    sess = await store.get(session_id)
    download_url = (
        f"/api/sessions/{session_id}/output.hwpx"
        if sess and sess.rendered_bytes
        else None
    )
    yield {"event": "done", "data": json.dumps({"download_url": download_url})}


@router.post("/api/chat")
async def chat(req: ChatRequest):
    if (await store.get(req.session_id)) is None:
        raise HTTPException(
            status_code=404, detail=f"세션을 찾을 수 없습니다: {req.session_id}"
        )
    return EventSourceResponse(_stream_graph(req.session_id, req.message))
