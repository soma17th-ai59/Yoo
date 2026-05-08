"""Central GraphState for the LangGraph form-fill pipeline."""

from typing import Literal, Optional

from pydantic import BaseModel

from backend.app.hwpx.models import FormDoc

Intent = Literal[
    "upload_form",
    "upload_material",
    "start_fill",
    "rewrite_item",
    "change_tone",
    "add_material",
    "general_qa",
]


class MaterialBundle(BaseModel):
    docs: list[dict]  # {filename, summary, masked_text, raw_len}


class ItemPlan(BaseModel):
    item_id: str
    source_evidence: list[str]  # material doc ids / spans
    confidence: float
    needs_question: bool
    question: Optional[str] = None


class DraftItem(BaseModel):
    item_id: str
    text: str
    citations: list[str]
    locked: bool = False


class PendingQuestion(BaseModel):
    item_id: str
    question: str


class GraphState(BaseModel):
    session_id: Optional[str] = None
    intent: Optional[Intent] = None
    user_message: Optional[str] = None
    form_doc: Optional[FormDoc] = None
    materials: MaterialBundle = MaterialBundle(docs=[])
    plans: list[ItemPlan] = []
    drafts: list[DraftItem] = []
    pending_question: Optional[PendingQuestion] = None
    pending_answer: Optional[str] = None
    history: list[dict[str, str]] = []  # last 10 turns
    errors: list[str] = []


def append_turn(state: GraphState, role: str, content: str) -> GraphState:
    """Return a new GraphState with the turn appended, keeping at most 10 turns."""
    new_history = [dict(t) for t in state.history] + [{"role": role, "content": content}]
    if len(new_history) > 10:
        new_history = new_history[-10:]
    return state.model_copy(update={"history": new_history})
