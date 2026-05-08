"""POST /api/chat — general QA. Plain JSON. Router/Graph bypassed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.graph.state import GraphState, append_turn
from backend.app.llm import solar
from backend.app.pii import mask_all
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
    safe_history = [
        {"role": t["role"], "content": mask_all(t["content"])} for t in state.history
    ]
    safe_user_message = mask_all(req.message)

    messages = [{"role": "system", "content": _QA_SYSTEM}]
    messages.extend(safe_history)
    messages.append({"role": "user", "content": safe_user_message})

    try:
        reply = _solar_complete(messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Solar 호출 실패: {exc}") from exc

    new_state = append_turn(state, "user", req.message)
    new_state = append_turn(new_state, "assistant", reply)
    await store.save_state(req.session_id, new_state)

    return {"reply": reply}
