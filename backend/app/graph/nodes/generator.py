"""Generator node — produce draft text for each fillable ItemPlan.

PII items get an empty DraftItem with status="pii" and is_pii=True — the LLM
is never called for them, but the user can type their own value via the UI.
Non-PII items with needs_question=True become status="needs_info" placeholders.
output_guard catches PII leakage in LLM output and retries up to 2× more;
persistent failure → status="needs_check" with empty text (so leaked PII does
not reach the UI).

Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import DraftItem, GraphState, ItemPlan
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_generator_messages
from backend.app.pii import scan

_MAX_ATTEMPTS = 3


def _solar_complete(messages: list[dict]) -> object:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)


def generate_drafts(state: GraphState) -> dict:
    """Generate DraftItem for every fillable item.

    PII items get an empty draft (status="pii", is_pii=True); the user is
    expected to type a value via the UI — the LLM never sees PII fields.
    Non-PII items follow the existing plan→generate→guard flow.
    Returns {"drafts": list[DraftItem]}.
    """
    if state.form_doc is None:
        return {"drafts": []}

    pii_item_ids = {item.item_id for item in state.form_doc.items if item.is_pii}
    non_fillable_ids = {item.item_id for item in state.form_doc.items if not item.fillable}
    drafts: list[DraftItem] = []

    for plan in state.plans:
        if plan.item_id in non_fillable_ids:
            continue

        if plan.item_id in pii_item_ids:
            drafts.append(
                DraftItem(
                    item_id=plan.item_id,
                    text="",
                    citations=[],
                    status="pii",
                    is_pii=True,
                )
            )
            continue

        if plan.needs_question:
            drafts.append(
                DraftItem(
                    item_id=plan.item_id,
                    text="",
                    citations=[],
                    status="needs_info",
                )
            )
            continue

        text, citations, status = _generate_with_guard(plan, state)
        drafts.append(
            DraftItem(
                item_id=plan.item_id,
                text=text,
                citations=citations,
                status=status,
            )
        )

    return {"drafts": drafts}


def _generate_with_guard(
    plan: ItemPlan,
    state: GraphState,
) -> tuple[str, list[str], str]:
    """Call Solar and retry on PII detection, up to _MAX_ATTEMPTS total.

    Returns (text, citations, status).
    """
    messages = build_generator_messages(
        plan.model_dump(),
        state.materials.docs,
        state.form_doc,  # type: ignore[arg-type]
    )

    for _ in range(_MAX_ATTEMPTS):
        try:
            response = _solar_complete(messages)
            if not isinstance(response, dict):
                text = str(response)
                citations: list[str] = []
            else:
                text = response.get("text", "")
                citations = response.get("citations", [])
        except Exception:
            return "", [], "needs_check"

        clean, _ = scan(text)
        if clean:
            return text, citations, "ok"

    return "", [], "needs_check"
