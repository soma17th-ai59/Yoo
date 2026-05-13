"""Verifier node — review each draft and set its status field.

Verdict → status mapping:
  ok        → status="ok"
  retry     → status="needs_review"
  soft_fail → status="needs_check"
  invalid   → treated as soft_fail

Drafts with status in {"pii", "needs_info", "needs_check"} are passed through
unchanged — the LLM has no claims to verify for them.
locked is never set here; it is set only when the user presses ✓ apply.
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

from backend.app.graph.state import DraftItem, GraphState
from backend.app.llm import solar as _solar_mod
from backend.app.llm.prompts import build_verifier_messages

_VALID_VERDICTS = frozenset(["ok", "retry", "soft_fail"])
_PASSTHROUGH_STATUSES = frozenset(["pii", "needs_info", "needs_check"])
_VERDICT_TO_STATUS = {
    "ok": "ok",
    "retry": "needs_review",
    "soft_fail": "needs_check",
}


def _solar_complete(messages: list[dict]) -> object:
    """Thin wrapper so tests can patch a single symbol."""
    return _solar_mod.complete(messages, json_mode=True)


def verify_drafts(state: GraphState) -> dict:
    """Verify every draft and return updated list with status field set.

    Returns {"drafts": list[DraftItem]}. locked and text are never mutated;
    only status changes.
    """
    if state.form_doc is None:
        return {"drafts": list(state.drafts)}

    updated_drafts: list[DraftItem] = []

    for draft in state.drafts:
        if draft.status in _PASSTHROUGH_STATUSES:
            updated_drafts.append(draft)
            continue

        updated_drafts.append(_verify_single(draft, state))

    return {"drafts": updated_drafts}


def _verify_single(draft: DraftItem, state: GraphState) -> DraftItem:
    """Call Solar to verify one draft and apply verdict → status."""
    messages = build_verifier_messages(
        draft.model_dump(),
        state.form_doc,  # type: ignore[arg-type]
        state.materials.docs,
    )

    try:
        response = _solar_complete(messages)
        if not isinstance(response, dict):
            verdict = "soft_fail"
        else:
            verdict = response.get("verdict", "soft_fail")
            if verdict not in _VALID_VERDICTS:
                verdict = "soft_fail"
    except Exception:
        verdict = "soft_fail"

    return draft.model_copy(update={"status": _VERDICT_TO_STATUS[verdict]})
