"""Generator node — produce draft text for each non-PII, non-question ItemPlan.

Applies output-guard retry: if scan() detects PII in the generated text, retries
up to 2 more times; on persistent failure, marks text as "[확인 필요]".
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState, DraftItem, ItemPlan
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_generator_messages
from backend.app.pii import scan

_MAX_ATTEMPTS = 3
_FALLBACK_TEXT = "[확인 필요]"


def _solar_complete(messages: list[dict]) -> object:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)


def generate_drafts(state: GraphState) -> dict:
    """Generate DraftItem for each eligible ItemPlan.

    Skips PII items (is_pii=True on the matching FormDoc item) and plans
    where needs_question=True.  Returns {"drafts": list[DraftItem]}.
    """
    if state.form_doc is None:
        return {"drafts": []}

    pii_item_ids = {item.item_id for item in state.form_doc.items if item.is_pii}
    drafts: list[DraftItem] = []

    for plan in state.plans:
        if plan.item_id in pii_item_ids:
            continue
        if plan.needs_question:
            continue

        text, citations = _generate_with_guard(plan, state)
        drafts.append(
            DraftItem(
                item_id=plan.item_id,
                text=text,
                citations=citations,
                approved=False,
            )
        )

    return {"drafts": drafts}


def _generate_with_guard(
    plan: ItemPlan,
    state: GraphState,
) -> tuple[str, list[str]]:
    """Call Solar and retry on PII detection, up to _MAX_ATTEMPTS total."""
    messages = build_generator_messages(
        plan.model_dump(),
        state.materials.docs,
        state.form_doc,  # type: ignore[arg-type]
    )

    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = _solar_complete(messages)
            if not isinstance(response, dict):
                text = str(response)
                citations: list[str] = []
            else:
                text = response.get("text", "")
                citations = response.get("citations", [])
        except Exception:
            text = _FALLBACK_TEXT
            citations = []
            break

        clean, _ = scan(text)
        if clean:
            return text, citations

        # PII detected — retry (messages already built; Solar will produce new output)

    # All attempts exhausted with PII still present
    return _FALLBACK_TEXT, []
