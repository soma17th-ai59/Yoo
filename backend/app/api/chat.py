"""POST /api/chat — drive the LangGraph pipeline and stream events as SSE.

Events emitted:
  - node_started     : {"node": str}                      before each node
  - preview          : list[DraftItem.model_dump()]       when drafts updated
  - done             : {"download_url": str | None}       at end
  - error            : {"error": str}                     on exception

The graph runs against the in-memory SessionStore as its SessionProvider.
NOTE: This module is being rewritten in Bundle D. It is intentionally minimal.
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
    initial = GraphState(session_id=session_id)
    session = await store.get(session_id)
    if session and session.graph_state is not None:
        prior = session.graph_state
        initial = prior.model_copy(update={"session_id": session_id})

    graph = build_compiled_graph(store)
    accumulated: dict[str, object] = {}

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
                    yield {
                        "event": "preview",
                        "data": json.dumps(_to_jsonable(diff["drafts"])),
                    }
    except Exception as exc:
        yield {"event": "error", "data": json.dumps({"error": str(exc)})}
        return

    try:
        final_state = initial.model_copy(update=accumulated)
        await store.save_state(session_id, final_state)
    except Exception:
        pass

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
