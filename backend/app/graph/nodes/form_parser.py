"""FormParser node — parses HWPX bytes and flags PII items.

parse_form(state: GraphState, form_bytes: bytes) -> dict
  Calls hwpx.parse_hwpx to produce a FormDoc, then pii.form_detector.flag_pii_items
  to set is_pii on each Item.  Generates one Placeholder("[본인 직접 입력]") for every
  PII-flagged item and attaches them to the returned FormDoc.
  No LLM call.  No disk I/O.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState
from backend.app.hwpx.models import FormDoc, Placeholder
from backend.app.hwpx.parser import parse_hwpx
from backend.app.pii.form_detector import flag_pii_items

_PII_PLACEHOLDER_TEXT = "[본인 직접 입력]"


def parse_form(state: GraphState, form_bytes: bytes) -> dict:
    """Parse HWPX bytes and update state with form_doc.

    state is intentionally unused here: this node always parses fresh from bytes.
    It is accepted so the graph can call all nodes with a uniform (state, **kwargs) signature.
    """
    raw_doc: FormDoc = parse_hwpx(form_bytes)
    flagged_doc: FormDoc = flag_pii_items(raw_doc)

    placeholders: list[Placeholder] = [
        Placeholder(item_id=item.item_id, placeholder_text=_PII_PLACEHOLDER_TEXT)
        for item in flagged_doc.items
        if item.is_pii
    ]

    final_doc = flagged_doc.model_copy(update={"placeholders": placeholders})
    return {"form_doc": final_doc}
