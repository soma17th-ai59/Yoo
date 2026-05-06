"""Router node — classifies user intent from state.user_message.

Calls Solar with build_router_messages and parses {"intent": ..., "confidence": ...}.
Returns a partial GraphState dict; never raises (errors surface in state.errors).
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState, Intent, append_turn
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_router_messages

_VALID_INTENTS: frozenset[str] = frozenset(
    [
        "upload_form",
        "upload_material",
        "start_fill",
        "rewrite_item",
        "change_tone",
        "add_material",
        "general_qa",
    ]
)

_CONFIDENCE_THRESHOLD: float = 0.7


def _solar_complete(messages: list[dict]) -> dict:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)  # type: ignore[return-value]


def route(state: GraphState) -> dict:
    """Classify user intent from state.user_message."""
    if not state.user_message:
        return {"errors": ["사용자 메시지가 없습니다."]}

    messages = build_router_messages(state.history, state.user_message)

    try:
        response: dict = _solar_complete(messages)
    except Exception as exc:
        return {"errors": [f"라우터 오류: {exc}"]}

    intent_raw = response.get("intent")
    confidence = response.get("confidence")

    if intent_raw is None or confidence is None:
        return {"errors": ["Solar 응답에 intent 또는 confidence 필드가 없습니다."]}

    if intent_raw not in _VALID_INTENTS:
        return {"errors": [f"알 수 없는 의도입니다: {intent_raw!r}"]}

    intent: Intent = intent_raw  # type: ignore[assignment]

    if confidence < _CONFIDENCE_THRESHOLD:
        disambiguation = response.get(
            "disambiguation",
            "의도를 명확히 알 수 없습니다. 다시 한번 말씀해 주시겠어요?",
        )
        return {"errors": [disambiguation]}

    new_state = append_turn(state, "user", state.user_message)
    return {"intent": intent, "history": new_state.history}
