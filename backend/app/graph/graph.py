"""LangGraph StateGraph assembly for the HwpAgent form-fill pipeline.

This is the ONLY module in the project allowed to import LangGraph.
All node logic lives in graph/nodes/* and is imported here as pure functions.

Adaptive routing:
  start_fill      → FormParser → MaterialIngestor → Planner → Generator → [Question?] → Verifier → Renderer
  rewrite_item    → Generator → Verifier → Renderer
  change_tone     → Generator → Verifier → Renderer
  add_material    → MaterialIngestor → Planner → Generator → [Question?] → Verifier → Renderer
  general_qa      → GeneralQaResponder → END
  upload_form     → FormParser → END
  upload_material → MaterialIngestor → END
"""

from __future__ import annotations

from typing import Optional, Protocol

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from backend.app.graph.state import GraphState
from backend.app.graph.nodes.router import route
from backend.app.graph.nodes.form_parser import parse_form
from backend.app.graph.nodes.material_ingestor import ingest_materials
from backend.app.graph.nodes.planner import plan_items
from backend.app.graph.nodes.generator import generate_drafts
from backend.app.graph.nodes.question import ask_question, resume_with_answer
from backend.app.graph.nodes.verifier import verify_drafts
from backend.app.graph.nodes.renderer import render_output
from backend.app.llm import solar as _solar_mod


# ---------------------------------------------------------------------------
# SessionProvider Protocol
# ---------------------------------------------------------------------------


class SessionProvider(Protocol):
    def get_form_bytes(self, session_id: str) -> bytes: ...
    def get_material_files(self, session_id: str) -> list[tuple[str, bytes]]: ...
    def put_rendered_bytes(self, session_id: str, data: bytes) -> None: ...


# ---------------------------------------------------------------------------
# General QA system prompt (graph-layer concern)
# ---------------------------------------------------------------------------

_GENERAL_QA_SYSTEM = """\
당신은 한국 국가연구비 지원사업 양식 작성을 돕는 AI 어시스턴트입니다.
사용자의 일반적인 질문에 친절하고 정확하게 한국어로 답변하세요.
양식 자동 채우기와 무관한 일반 질문에 대해서도 도움을 드립니다."""


def _general_qa_responder(state: GraphState) -> dict:
    """Graph-layer node: respond to general QA with a Korean chat reply.

    Calls Solar directly with a minimal chat prompt.
    Does not use Renderer — general_qa has no output bytes.
    """
    user_msg = state.user_message or ""
    history_msgs = [{"role": t["role"], "content": t["content"]} for t in state.history]

    messages = [{"role": "system", "content": _GENERAL_QA_SYSTEM}]
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": user_msg})

    try:
        response = _solar_mod.complete(messages, json_mode=False)
        reply = str(response)
    except Exception as exc:
        reply = f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {exc}"

    new_history = list(state.history) + [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]
    if len(new_history) > 10:
        new_history = new_history[-10:]

    return {"history": new_history}


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------


def _route_intent(state: GraphState) -> str:
    if state.errors:
        return "END"
    return state.intent or "END"


def _after_form_parser(state: GraphState) -> str:
    """After FormParser: upload_form goes to END; otherwise continue to material_ingestor."""
    if state.errors:
        return "END"
    if state.intent == "upload_form":
        return "END"
    return "material_ingestor"


def _after_material_ingestor(state: GraphState) -> str:
    """After MaterialIngestor: upload_material goes to END; otherwise continue to planner."""
    if state.errors:
        return "END"
    if state.intent == "upload_material":
        return "END"
    return "planner"


def _after_planner(state: GraphState) -> str:
    if state.errors:
        return "END"
    return "generator"


def _after_generator(state: GraphState) -> str:
    """After Generator: check if any plan still needs_question."""
    if state.errors:
        return "END"
    drafted_ids = {d.item_id for d in state.drafts}
    for plan in state.plans:
        if plan.needs_question and plan.item_id not in drafted_ids:
            return "ask_question"
    return "verifier"


def _after_verifier(state: GraphState) -> str:
    if state.errors:
        return "END"
    return "renderer"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_compiled_graph(session_provider: SessionProvider):
    """Build and compile the LangGraph StateGraph with adaptive routing.

    Args:
        session_provider: Provides form bytes and material files for the session.

    Returns:
        A compiled LangGraph StateGraph ready for .invoke() or .stream().
    """

    # --- Wrapper nodes that inject bytes from the session provider -----------

    def _form_parser(state: GraphState) -> dict:
        form_bytes = session_provider.get_form_bytes(state.session_id or "")
        return parse_form(state, form_bytes)

    def _material_ingestor(state: GraphState) -> dict:
        material_files = session_provider.get_material_files(state.session_id or "")
        return ingest_materials(state, material_files)

    def _renderer(state: GraphState) -> dict:
        form_bytes = session_provider.get_form_bytes(state.session_id or "")
        result = render_output(state, form_bytes)
        rendered = result.get("rendered_bytes", b"")
        if rendered and state.session_id:
            session_provider.put_rendered_bytes(state.session_id, rendered)
        return result

    # --- Question node with interrupt/resume ---------------------------------

    def _ask_question_node(state: GraphState) -> dict:
        result = ask_question(state)
        if result.get("pending_question") is None:
            return result
        answer = interrupt(result["pending_question"].model_dump())
        resume_result = resume_with_answer(
            state.model_copy(update=result),
            answer,
        )
        return {**result, **resume_result}

    # --- Build graph ---------------------------------------------------------

    g = StateGraph(GraphState)

    g.add_node("router", route)
    g.add_node("form_parser", _form_parser)
    g.add_node("material_ingestor", _material_ingestor)
    g.add_node("planner", plan_items)
    g.add_node("generator", generate_drafts)
    g.add_node("ask_question", _ask_question_node)
    g.add_node("verifier", verify_drafts)
    g.add_node("renderer", _renderer)
    g.add_node("general_qa_responder", _general_qa_responder)

    g.set_entry_point("router")

    g.add_conditional_edges(
        "router",
        _route_intent,
        {
            "start_fill": "form_parser",
            "rewrite_item": "generator",
            "change_tone": "generator",
            "add_material": "material_ingestor",
            "general_qa": "general_qa_responder",
            "upload_form": "form_parser",
            "upload_material": "material_ingestor",
            "END": END,
        },
    )

    g.add_conditional_edges(
        "form_parser",
        _after_form_parser,
        {
            "material_ingestor": "material_ingestor",
            "END": END,
        },
    )

    g.add_conditional_edges(
        "material_ingestor",
        _after_material_ingestor,
        {
            "planner": "planner",
            "END": END,
        },
    )

    g.add_conditional_edges(
        "planner",
        _after_planner,
        {
            "generator": "generator",
            "END": END,
        },
    )

    g.add_conditional_edges(
        "generator",
        _after_generator,
        {
            "ask_question": "ask_question",
            "verifier": "verifier",
            "END": END,
        },
    )

    g.add_edge("ask_question", "generator")

    g.add_conditional_edges(
        "verifier",
        _after_verifier,
        {
            "renderer": "renderer",
            "END": END,
        },
    )

    g.add_edge("renderer", END)
    g.add_edge("general_qa_responder", END)

    return g.compile()
