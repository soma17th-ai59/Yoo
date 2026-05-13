"""Central GraphState for the LangGraph form-fill pipeline."""

from typing import Literal

from pydantic import BaseModel

from backend.app.hwpx.models import FormDoc

DraftStatus = Literal["ok", "needs_review", "needs_info", "needs_check", "pii"]


class MaterialBundle(BaseModel):
    docs: list[dict]


class ItemPlan(BaseModel):
    item_id: str
    source_evidence: list[str]
    confidence: float
    needs_question: bool
    question: str | None = None


class DraftItem(BaseModel):
    item_id: str
    text: str
    citations: list[str]
    locked: bool = False
    status: DraftStatus = "ok"
    is_pii: bool = False


class GraphState(BaseModel):
    session_id: str | None = None
    form_doc: FormDoc | None = None
    materials: MaterialBundle = MaterialBundle(docs=[])
    plans: list[ItemPlan] = []
    drafts: list[DraftItem] = []
    history: list[dict[str, str]] = []
    errors: list[str] = []


def append_turn(state: GraphState, role: str, content: str) -> GraphState:
    """Return a new GraphState with the turn appended, keeping at most 10 turns."""
    new_history = [dict(t) for t in state.history] + [{"role": role, "content": content}]
    if len(new_history) > 10:
        new_history = new_history[-10:]
    return state.model_copy(update={"history": new_history})
