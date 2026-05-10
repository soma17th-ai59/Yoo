"""LangGraph StateGraph assembly for the HwpAgent form-fill pipeline.

Single straight-line flow:
    form_parser → material_ingestor → planner → generator → verifier → END

This is the ONLY module in the project allowed to import LangGraph.
All node logic lives in graph/nodes/* and is imported here as pure functions.
"""

from __future__ import annotations

from typing import Protocol

from langgraph.graph import END, StateGraph

from backend.app.graph.nodes.form_parser import parse_form
from backend.app.graph.nodes.generator import generate_drafts
from backend.app.graph.nodes.material_ingestor import ingest_materials
from backend.app.graph.nodes.planner import plan_items
from backend.app.graph.nodes.verifier import verify_drafts
from backend.app.graph.state import GraphState


class SessionProvider(Protocol):
    def get_form_bytes(self, session_id: str) -> bytes: ...
    def get_material_files(self, session_id: str) -> list[tuple[str, bytes]]: ...


def _stop_on_error(state: GraphState) -> str:
    return "END" if state.errors else "continue"


def build_compiled_graph(session_provider: SessionProvider):
    """Build and compile the form-fill graph.

    The graph runs only when POST /api/sessions/{sid}/fill is called.
    Per-item actions (apply/unlock/edit/chat) and general QA bypass this graph.
    """

    def _form_parser(state: GraphState) -> dict:
        form_bytes = session_provider.get_form_bytes(state.session_id or "")
        return parse_form(state, form_bytes)

    def _material_ingestor(state: GraphState) -> dict:
        material_files = session_provider.get_material_files(state.session_id or "")
        return ingest_materials(state, material_files)

    g = StateGraph(GraphState)

    g.add_node("form_parser", _form_parser)
    g.add_node("material_ingestor", _material_ingestor)
    g.add_node("planner", plan_items)
    g.add_node("generator", generate_drafts)
    g.add_node("verifier", verify_drafts)

    g.set_entry_point("form_parser")

    for from_node, to_node in [
        ("form_parser", "material_ingestor"),
        ("material_ingestor", "planner"),
        ("planner", "generator"),
        ("generator", "verifier"),
    ]:
        g.add_conditional_edges(from_node, _stop_on_error, {"continue": to_node, "END": END})

    g.add_edge("verifier", END)

    return g.compile()
