"""Renderer node — pack locked drafts + PII placeholders into output HWPX bytes.

PII items always render as "[본인 직접 입력]" regardless of draft state.
Non-PII locked drafts are written as-is.
Also produces a markdown preview string for the frontend.
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import GraphState, DraftItem as StateDraftItem
from backend.app.hwpx.renderer import apply_drafts
from backend.app.hwpx.renderer import DraftItem as RendererDraftItem

_PII_DISPLAY_TEXT = "[본인 직접 입력]"


def render_output(state: GraphState, form_bytes: bytes) -> dict:
    """Build the final HWPX bytes and a markdown preview.

    Returns {"rendered_bytes": bytes, "preview_md": str}.
    """
    if state.form_doc is None:
        return {"rendered_bytes": form_bytes, "preview_md": ""}

    pii_item_ids = {item.item_id for item in state.form_doc.items if item.is_pii}

    renderer_drafts: list[RendererDraftItem] = []

    # PII items — always "[본인 직접 입력]"
    for item in state.form_doc.items:
        if item.is_pii:
            renderer_drafts.append(
                RendererDraftItem(item_id=item.item_id, text=_PII_DISPLAY_TEXT, is_pii=True)
            )

    # Also handle placeholders that are marked as PII
    for placeholder in state.form_doc.placeholders:
        if placeholder.item_id in pii_item_ids:
            continue  # already handled above
        # Non-PII placeholders: look for a matching locked draft
        draft = next(
            (d for d in state.drafts if d.item_id == placeholder.item_id and d.locked),
            None,
        )
        if draft is not None:
            renderer_drafts.append(
                RendererDraftItem(item_id=placeholder.item_id, text=draft.text, is_pii=False)
            )

    # Non-PII approved drafts (items not PII and not already handled via placeholders)
    handled_ids = {rd.item_id for rd in renderer_drafts}
    for draft in state.drafts:
        if draft.item_id in handled_ids:
            continue
        if draft.item_id in pii_item_ids:
            continue
        if draft.locked:
            renderer_drafts.append(
                RendererDraftItem(item_id=draft.item_id, text=draft.text, is_pii=False)
            )

    rendered_bytes = apply_drafts(form_bytes, renderer_drafts)
    preview_md = _build_preview(state, pii_item_ids)

    return {"rendered_bytes": rendered_bytes, "preview_md": preview_md}


def _build_preview(state: GraphState, pii_item_ids: set[str]) -> str:
    """Build a markdown preview listing each item with its draft text."""
    lines: list[str] = ["## 양식 자동 채우기 결과\n"]

    item_labels: dict[str, str] = {}
    if state.form_doc is not None:
        item_labels = {item.item_id: item.label for item in state.form_doc.items}

    draft_map: dict[str, StateDraftItem] = {d.item_id: d for d in state.drafts}

    if state.form_doc is not None:
        for item in state.form_doc.items:
            label = item.label
            if item.is_pii:
                lines.append(f"- **{label}**: {_PII_DISPLAY_TEXT}")
            else:
                draft = draft_map.get(item.item_id)
                text = draft.text if draft is not None else "(미작성)"
                lines.append(f"- **{label}**: {text}")

    return "\n".join(lines)
