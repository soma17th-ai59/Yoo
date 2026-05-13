"""Renderer node — pack locked drafts into output HWPX bytes.

Locked drafts (whether PII or not) are written as-is. PII content typed by
the user never reaches the LLM (Generator skips PII; ItemChat rejects PII
items); the user's input only flows from the UI → PUT /drafts → state →
renderer → output file.

Also produces a markdown preview string for the frontend.
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import DraftItem as StateDraftItem
from backend.app.graph.state import GraphState
from backend.app.hwpx.renderer import DraftItem as RendererDraftItem
from backend.app.hwpx.renderer import apply_drafts


def render_output(state: GraphState, form_bytes: bytes, *, include_unlocked: bool = False) -> dict:
    """Build the final HWPX bytes and a markdown preview.

    By default only locked drafts land in the output (lock = user approval).
    When `include_unlocked=True`, every generated draft is written too.

    Returns {"rendered_bytes": bytes, "preview_md": str}.
    """
    if state.form_doc is None:
        return {"rendered_bytes": form_bytes, "preview_md": ""}

    renderer_drafts: list[RendererDraftItem] = []
    pii_item_ids = {item.item_id for item in state.form_doc.items if item.is_pii}

    for draft in state.drafts:
        if not (draft.locked or include_unlocked):
            continue
        if not draft.text:
            continue
        renderer_drafts.append(
            RendererDraftItem(
                item_id=draft.item_id,
                text=draft.text,
                is_pii=draft.item_id in pii_item_ids,
            )
        )

    rendered_bytes = apply_drafts(form_bytes, renderer_drafts)
    preview_md = _build_preview(state, pii_item_ids)

    return {"rendered_bytes": rendered_bytes, "preview_md": preview_md}


def _build_preview(state: GraphState, pii_item_ids: set[str]) -> str:
    """Build a markdown preview listing each item with its draft text."""
    lines: list[str] = ["## 양식 자동 채우기 결과\n"]

    draft_map: dict[str, StateDraftItem] = {d.item_id: d for d in state.drafts}

    if state.form_doc is not None:
        for item in state.form_doc.items:
            label = item.label
            draft = draft_map.get(item.item_id)
            if draft is None or not draft.text:
                tag = " _[직접 입력 필요]_" if item.item_id in pii_item_ids else ""
                lines.append(f"- **{label}**{tag}: (미작성)")
            else:
                lines.append(f"- **{label}**: {draft.text}")

    return "\n".join(lines)
